"""
xstorage — xcore file storage extension. Extracted from xform's internal
storage code so any plugin (xform, xstock, xassets, xfleet...) can share the
same blob storage backend instead of re-implementing it.

Configuration in int.yaml:
    services:
      extensions:
        storage:
          module: extensions.xstorage.main:StorageService
          config:
            backend: local        # local | s3 | r2 | supabase
            max_size_mb: 10
            local:
              path: data/storage        # relative to the kernel's data_dir
              public_base_url: null     # e.g. https://files.example.com (optional)
              url_secret: ${STORAGE_URL_SECRET}   # required for get_signed_url() (optional)
            s3:
              bucket: ...
              region: ...
              access_key_id: ${S3_ACCESS_KEY_ID}
              secret_access_key: ${S3_SECRET_ACCESS_KEY}
              prefix: xstorage/
              endpoint_url: null
              public: false              # true to allow get_public_url()
              public_base_url: null       # e.g. a CDN domain in front of the bucket
            supabase:
              url: ${SUPABASE_URL}
              key: ${SUPABASE_SERVICE_KEY}
              bucket: ...
              public: false

Access from a plugin:
    storage = self.get_service("ext.storage")
    uploaded = await storage.save(content, filename, namespace="xstock/batch-123")
    content  = await storage.read(uploaded.file_id, "xstock/batch-123", uploaded.stored_name)
    url      = await storage.get_signed_url(uploaded.file_id, "xstock/batch-123", uploaded.stored_name)
    await storage.delete(uploaded.file_id, "xstock/batch-123", uploaded.stored_name)

`namespace` is caller-defined and should be scoped per plugin + owning entity
(e.g. "xstock/batch-123", "xform/form-456") so different plugins/entities
never collide on the same backend. Metadata persistence (which file belongs
to which DB row) stays the responsibility of the consuming plugin — this
service is blob I/O only, no ORM.

IMPORTANT: always persist `UploadedFile.stored_name` from `save()`'s return
value. It's required by read()/delete()/exists()/get_public_url()/
get_signed_url() — the backend key can't be rebuilt from file_id alone.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from xcore.services.base import BaseService, ServiceStatus

from .backends import build_backend
from .uploader import FileStorageError, FileTooLargeError, FileTypeNotAllowedError, FileUploader, UploadedFile

__all__ = [
    "StorageService",
    "FileStorageError",
    "FileTooLargeError",
    "FileTypeNotAllowedError",
    "UploadedFile",
]


class StorageNotReadyError(FileStorageError):
    """Raised when the service is used before init() or after shutdown()."""


class StorageService(BaseService):
    """
    File storage service (upload validation + backend I/O + URL generation).

      save()             → validate + store, returns UploadedFile
      read()              → returns bytes or None
      delete()             → returns True if the file existed
      delete_namespace()   → bulk delete, returns count removed
      exists()             → returns bool
      get_public_url()     → permanent URL, None if unsupported/private
      get_signed_url()     → temporary URL, None if unsupported
    """

    name = "storage"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._cfg = config or {}
        self._uploader: Optional[FileUploader] = None

    async def init(self) -> None:
        self._status = ServiceStatus.INITIALIZING
        data_dir = Path(self._cfg.get("data_dir") or ".")
        backend = build_backend(self._cfg, data_dir)
        max_size_mb = int(self._cfg.get("max_size_mb") or 10)
        allowed_ext = set(self._cfg["allowed_extensions"]) if self._cfg.get("allowed_extensions") else None
        blocked_ext = set(self._cfg["blocked_extensions"]) if self._cfg.get("blocked_extensions") else None
        self._uploader = FileUploader(
            backend=backend, max_size_mb=max_size_mb, allowed_ext=allowed_ext, blocked_ext=blocked_ext
        )
        self._status = ServiceStatus.READY

    async def shutdown(self) -> None:
        if self._uploader is not None:
            await self._uploader.close()
        self._uploader = None
        self._status = ServiceStatus.STOPPED

    async def health_check(self) -> tuple[bool, str]:
        if self._uploader is None:
            return False, "storage backend not initialized"
        return True, f"backend={self._cfg.get('backend', 'local')}"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self._status.value,
            "backend": self._cfg.get("backend", "local"),
        }

    def _require_uploader(self) -> FileUploader:
        if self._uploader is None:
            raise StorageNotReadyError(
                "storage service is not ready (call init() first, or it was already shut down)."
            )
        return self._uploader

    # ── Public API ───────────────────────────────────────────

    def backend(self) -> str:
        return self._cfg.get("backend", "no-know")

    async def save(self, content: bytes, filename: str, namespace: str) -> UploadedFile:
        return await self._require_uploader().save(content, filename, namespace)

    async def read(self, file_id: str, namespace: str, stored_name: Optional[str] = None) -> Optional[bytes]:
        return await self._require_uploader().read(file_id, namespace, stored_name)

    async def delete(self, file_id: str, namespace: str, stored_name: Optional[str] = None) -> bool:
        return await self._require_uploader().delete(file_id, namespace, stored_name)

    async def delete_namespace(self, namespace: str) -> int:
        return await self._require_uploader().delete_namespace(namespace)

    async def exists(self, file_id: str, namespace: str, stored_name: Optional[str] = None) -> bool:
        return await self._require_uploader().exists(file_id, namespace, stored_name)

    async def list(self, namespace: str) -> list[dict]:
        return await self._require_uploader().list(namespace)

    async def get_public_url(self, file_id: str, namespace: str, stored_name: Optional[str] = None) -> Optional[str]:
        return await self._require_uploader().get_public_url(file_id, namespace, stored_name)

    async def get_signed_url(
        self, file_id: str, namespace: str, stored_name: Optional[str] = None, expires_in: int = 3600
    ) -> Optional[str]:
        return await self._require_uploader().get_signed_url(file_id, namespace, stored_name, expires_in)