"""
FileUploader — validation + delegation to a StorageBackend.

Responsibilities:
  - Validate file size and extension
  - Generate a unique file_id
  - Sanitize the filename (path traversal, dangerous characters)
  - Delegate I/O to the backend (local, S3, R2, Supabase...)
  - Delegate URL generation (public / temporary signed) to the backend

Storage key: "{namespace}/{stored_name}". `namespace` is caller-defined —
e.g. a plugin name plus an owning entity id ("xform/form-123",
"xstock/batch-456") — so unrelated plugins/entities never collide.

IMPORTANT — `stored_name` is required for read/delete/exists/URL methods.
The physical key is "{namespace}/{file_id}{ext}", not "{namespace}/{file_id}".
Callers MUST persist `UploadedFile.stored_name` (e.g. in their DB row) and
pass it back in; there is no reliable way to recover the extension from
file_id alone.
"""
from __future__ import annotations

import logging
import mimetypes
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from .backends import StorageBackend

logger = logging.getLogger("xcore.services.storage")

DEFAULT_ALLOWED_EXT = {
    ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt",
    ".xls", ".xlsx", ".csv", ".ods",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".ppt", ".pptx", ".odp",
}

BLOCKED_EXT = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".dll", ".sys", ".vbs",
    ".ps1", ".sh", ".bash", ".zsh", ".fish", ".rb", ".py", ".pl",
    ".php", ".asp", ".aspx", ".jsp", ".cgi", ".scr", ".pif", ".hta",
    ".js", ".ts", ".jar", ".class", ".war", ".ear",
}

# Zip-based Office/OpenDocument formats — all share the PK\x03\x04 magic
# bytes, so the real MIME type has to be disambiguated by extension.
_ZIP_BASED_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}


class FileStorageError(Exception):
    pass


class FileTooLargeError(FileStorageError):
    pass


class FileTypeNotAllowedError(FileStorageError):
    pass


class UploadedFile:
    def __init__(
        self,
        file_id: str,
        original_name: str,
        stored_name: str,
        namespace: str,
        size_bytes: int,
        mime_type: str,
        key: str,
    ):
        self.file_id = file_id
        self.original_name = original_name
        self.stored_name = stored_name
        self.namespace = namespace
        self.size_bytes = size_bytes
        self.mime_type = mime_type
        self.key = key  # backend key: {namespace}/{stored_name}
        self.uploaded_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "original_name": self.original_name,
            "stored_name": self.stored_name,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
            "namespace": self.namespace,
            "uploaded_at": self.uploaded_at.isoformat(),
        }


class FileUploader:
    """
    Validates and stores files through the configured backend.

    Usage:
        uploader = FileUploader(backend, max_size_mb=10)
        result   = await uploader.save(content, filename, namespace="xstock/batch-456")
        content  = await uploader.read(result.file_id, namespace, stored_name=result.stored_name)
        await uploader.delete(result.file_id, namespace, stored_name=result.stored_name)
        url      = await uploader.get_signed_url(result.file_id, namespace, result.stored_name)
    """

    def __init__(
        self,
        backend: StorageBackend,
        max_size_mb: int = 10,
        allowed_ext: Optional[set] = None,
        blocked_ext: Optional[set] = None,
    ) -> None:
        if max_size_mb <= 0:
            raise ValueError(f"max_size_mb must be > 0, got {max_size_mb!r}")
        self._backend = backend
        self._max_bytes = max_size_mb * 1024 * 1024
        self._allowed = {e.lower() for e in (allowed_ext or DEFAULT_ALLOWED_EXT)}
        self._blocked = {e.lower() for e in (blocked_ext or BLOCKED_EXT)}

    # ── Upload ────────────────────────────────────────────────

    async def save(self, content: bytes, filename: str, namespace: str) -> UploadedFile:
        size = len(content)
        if size == 0:
            raise FileStorageError("the file is empty.")

        if size > self._max_bytes:
            raise FileTooLargeError(
                f"file too large ({size // (1024*1024)}MB). "
                f"Maximum: {self._max_bytes // (1024*1024)}MB."
            )

        safe_name = self._sanitize(filename)
        ext = Path(safe_name).suffix.lower()

        if ext in self._blocked:
            raise FileTypeNotAllowedError(f"this file type is forbidden for security reasons: {ext}")
        if self._allowed and ext not in self._allowed:
            raise FileTypeNotAllowedError(
                f"extension '{ext}' not allowed. Accepted formats: {', '.join(sorted(self._allowed))}"
            )

        mime = self._detect_mime(content, safe_name)
        file_id = uuid4().hex
        stored_name = f"{file_id}{ext}"
        key = f"{namespace}/{stored_name}"

        await self._backend.put(key, content)

        logger.info(
            "Upload OK: namespace=%s file_id=%s name=%s size=%d mime=%s",
            namespace, file_id, safe_name, size, mime,
        )
        return UploadedFile(
            file_id=file_id,
            original_name=filename,
            stored_name=stored_name,
            namespace=namespace,
            size_bytes=size,
            mime_type=mime,
            key=key,
        )

    # ── Read / delete ─────────────────────────────────────────

    def _key(self, file_id: str, namespace: str, stored_name: Optional[str]) -> str:
        """
        Rebuild the backend key. `stored_name` is required: the physical key
        is "{namespace}/{file_id}{ext}", and the extension cannot be
        recovered from `file_id` alone. Passing None here would silently
        build a key that never matches what save() actually wrote.
        """
        if not stored_name:
            raise FileStorageError(
                "stored_name is required (persist UploadedFile.stored_name and "
                "pass it back in — it cannot be reconstructed from file_id alone)."
            )
        return f"{namespace}/{stored_name}"

    async def read(self, file_id: str, namespace: str, stored_name: Optional[str] = None) -> Optional[bytes]:
        return await self._backend.get(self._key(file_id, namespace, stored_name))

    async def delete(self, file_id: str, namespace: str, stored_name: Optional[str] = None) -> bool:
        return await self._backend.delete(self._key(file_id, namespace, stored_name))

    async def list(self, namespace: str) -> list[dict]:
        """
        Énumère les fichiers d'un namespace. Le nom d'origine n'est PAS
        récupérable (seul {file_id}{ext} est physiquement stocké) — le
        `stored_name` fait office de nom faute de mieux pour ce qui n'a pas
        été uploadé via save() (donc jamais tracé ailleurs avec son vrai nom).
        """
        stored_names = await self._backend.list_prefix(namespace)
        return [
            {
                "file_id": Path(name).stem,
                "stored_name": name,
                "namespace": namespace,
            }
            for name in stored_names
        ]

    async def delete_namespace(self, namespace: str) -> int:
        return await self._backend.delete_prefix(f"{namespace}/")

    async def exists(self, file_id: str, namespace: str, stored_name: Optional[str] = None) -> bool:
        return await self._backend.exists(self._key(file_id, namespace, stored_name))

    # ── URLs ──────────────────────────────────────────────────
    # Every backend implements these (default None), so no hasattr() needed.

    async def get_public_url(
        self, file_id: str, namespace: str, stored_name: Optional[str] = None
    ) -> Optional[str]:
        """Permanent public URL, or None if the backend/bucket doesn't support it."""
        return await self._backend.get_public_url(self._key(file_id, namespace, stored_name))

    async def get_signed_url(
        self, file_id: str, namespace: str, stored_name: Optional[str] = None, expires_in: int = 3600
    ) -> Optional[str]:
        """Temporary signed URL valid for `expires_in` seconds, or None if unsupported."""
        return await self._backend.get_signed_url(
            self._key(file_id, namespace, stored_name), expires_in
        )

    async def close(self) -> None:
        await self._backend.close()

    # ── Private helpers ───────────────────────────────────────

    @staticmethod
    def _sanitize(filename: str) -> str:
        name = unicodedata.normalize("NFKD", filename)
        name = name.encode("ascii", "ignore").decode("ascii")
        name = Path(name).name
        stem = re.sub(r"[^\w\s.-]", "", Path(name).stem)
        stem = re.sub(r"\s+", "_", stem.strip())[:200]
        suffix = Path(name).suffix.lower()
        return f"{stem}{suffix}" if stem else f"file{suffix}"

    @staticmethod
    def _detect_mime(content: bytes, filename: str) -> str:
        MAGIC = [
            (b"%PDF", "application/pdf"),
            (b"\xff\xd8\xff", "image/jpeg"),
            (b"\x89PNG\r\n", "image/png"),
            (b"GIF87a", "image/gif"),
            (b"GIF89a", "image/gif"),
            (b"PK\x03\x04", "application/zip"),
        ]
        for magic, mime in MAGIC:
            if content[: len(magic)] == magic:
                if mime == "application/zip":
                    ext = Path(filename).suffix.lower()
                    return _ZIP_BASED_MIME.get(ext, "application/zip")
                return mime
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or "application/octet-stream"