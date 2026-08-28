"""
Storage backends for the xstorage xcore extension.

Uniform interface: put / get / delete / delete_prefix / exists / close
                    get_public_url / get_signed_url (URL generation)
Storage key convention (owned by callers, not the backend): "{namespace}/{name}".

Backends:
  - LocalBackend    : local disk (default, dev/single-instance)
  - S3Backend       : AWS S3, Cloudflare R2, MinIO (production)
  - SupabaseBackend : Supabase Storage
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("xcore.services.storage")


class StorageBackend(ABC):
    """Common interface implemented by every storage backend."""

    @abstractmethod
    async def put(self, key: str, content: bytes) -> None:
        """Store `content` under `key`."""

    @abstractmethod
    async def get(self, key: str) -> Optional[bytes]:
        """Return the content, or None if absent."""

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete the key. Returns True if it existed."""

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> int:
        """Delete every key starting with `prefix`. Returns the number deleted."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return True if the key exists."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources (connections, sessions)."""

    # Not abstract: backends that can't enumerate keys (or choose not to)
    # simply keep the default (returns []). Callers never need hasattr().
    async def list_prefix(self, prefix: str) -> list:
        """Return the stored_name (last path segment) of every key under `prefix`."""
        return []

    # ── URL generation ────────────────────────────────────────
    # Not abstract: backends that don't support URLs simply keep the
    # default (returns None). Callers never need hasattr() checks.

    async def get_public_url(self, key: str) -> Optional[str]:
        """Return a permanent public URL, or None if unsupported/private."""
        return None

    async def get_signed_url(self, key: str, expires_in: int = 3600) -> Optional[str]:
        """Return a temporary signed URL valid for `expires_in` seconds, or None if unsupported."""
        return None


def _safe_join(root: Path, relative: str) -> Path:
    """
    Resolve `relative` under `root` and raise ValueError on any path traversal
    attempt. Uses Path.relative_to (not string prefix matching, which is
    bypassable e.g. root='/data/x' vs resolved='/data/x_evil/y').
    """
    if not relative or relative.startswith(("/", "\\")):
        raise ValueError(f"invalid key: {relative!r}")
    root_resolved = root.resolve()
    resolved = (root_resolved / relative).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise ValueError(f"invalid key (path traversal): {relative!r}") from None
    return resolved


# ─────────────────────────────────────────────────────────────
# Local backend
# ─────────────────────────────────────────────────────────────

class LocalBackend(StorageBackend):
    """
    Local disk storage. root_dir/{key} → physical file.

    Optional URL support:
      - public_base_url: if set, get_public_url() returns f"{public_base_url}/{key}".
      - url_secret: if set, get_signed_url() returns an HMAC-signed, time-limited
        URL. Your app must expose a route that serves files after calling
        verify_signed_url() to validate the signature/expiry — this backend
        only signs/verifies, it doesn't serve HTTP itself.
    """

    def __init__(
        self,
        root_dir: Path,
        public_base_url: Optional[str] = None,
        url_secret: Optional[str] = None,
    ) -> None:
        self._root = Path(root_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._public_base_url = public_base_url.rstrip("/") if public_base_url else None
        self._url_secret = url_secret
        logger.info("LocalBackend ready — root=%s", self._root)

    def _path(self, key: str) -> Path:
        return _safe_join(self._root, key)

    async def put(self, key: str, content: bytes) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + f".{id(content)}.tmp")
        try:
            tmp.write_bytes(content)
            tmp.rename(dest)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    async def get(self, key: str) -> Optional[bytes]:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None

    async def delete(self, key: str) -> bool:
        path = self._path(key)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    async def delete_prefix(self, prefix: str) -> int:
        # _safe_join guarantees target_dir can never escape self._root.
        target_dir = _safe_join(self._root, prefix.rstrip("/") or ".")
        if not target_dir.exists() or not target_dir.is_dir():
            return 0
        count = 0
        for f in target_dir.iterdir():
            if f.is_file():
                f.unlink()
                count += 1
        try:
            target_dir.rmdir()
        except OSError:
            pass
        return count

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def close(self) -> None:
        pass

    async def list_prefix(self, prefix: str) -> list:
        # _safe_join guarantees target_dir can never escape self._root.
        target_dir = _safe_join(self._root, prefix.rstrip("/") or ".")
        if not target_dir.exists() or not target_dir.is_dir():
            return []
        return sorted(f.name for f in target_dir.iterdir() if f.is_file())

    # ── URLs ──────────────────────────────────────────────────

    def _sign(self, key: str, expires_at: int) -> str:
        msg = f"{key}:{expires_at}".encode()
        return hmac.new(self._url_secret.encode(), msg, hashlib.sha256).hexdigest()

    async def get_public_url(self, key: str) -> Optional[str]:
        if not self._public_base_url:
            return None
        return f"{self._public_base_url}/{key}"

    async def get_signed_url(self, key: str, expires_in: int = 3600) -> Optional[str]:
        if not self._url_secret:
            logger.warning("LocalBackend.get_signed_url: no url_secret configured (storage.local.url_secret)")
            return None
        expires_at = int(time.time()) + expires_in
        signature = self._sign(key, expires_at)
        base = self._public_base_url or ""
        return f"{base}/{key}?expires={expires_at}&signature={signature}"

    def verify_signed_url(self, key: str, expires_at: int, signature: str) -> bool:
        """
        For use by your app's file-serving route: verify a signature produced
        by get_signed_url(). Returns False if expired or invalid/tampered.
        """
        if not self._url_secret:
            return False
        try:
            expires_at = int(expires_at)
        except (TypeError, ValueError):
            return False
        if int(time.time()) > expires_at:
            return False
        expected = self._sign(key, expires_at)
        return hmac.compare_digest(expected, signature or "")


# ─────────────────────────────────────────────────────────────
# S3 backend (AWS S3 / Cloudflare R2 / MinIO)
# ─────────────────────────────────────────────────────────────

class S3Backend(StorageBackend):
    """
    S3-compatible storage (AWS S3, Cloudflare R2, MinIO).
    Uses aioboto3 for async operations. S3 key = {prefix}{key}.
    """

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        access_key_id: str = "",
        secret_access_key: str = "",
        prefix: str = "xstorage/",
        endpoint_url: Optional[str] = None,
        public: bool = False,
        public_base_url: Optional[str] = None,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._session_kwargs: Dict[str, Any] = {"region_name": region}
        if access_key_id and secret_access_key:
            self._session_kwargs["aws_access_key_id"] = access_key_id
            self._session_kwargs["aws_secret_access_key"] = secret_access_key
        self._client_kwargs: Dict[str, Any] = {}
        if endpoint_url:
            self._client_kwargs["endpoint_url"] = endpoint_url
        self._endpoint_url = endpoint_url
        self._public = public
        # e.g. a CDN / custom domain in front of the bucket
        self._public_base_url = public_base_url.rstrip("/") if public_base_url else None

        self._session = None
        self._client = None
        self._client_lock = asyncio.Lock()
        logger.info(
            "S3Backend ready — bucket=%s prefix=%s endpoint=%s public=%s",
            bucket, self._prefix, endpoint_url or "AWS", public,
        )

    async def _get_client(self):
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:  # re-check: another task may have won the race
                return self._client
            try:
                import aioboto3
            except ImportError:
                raise RuntimeError(
                    "aioboto3 is required for the S3 backend. Install it: pip install aioboto3"
                )
            self._session = aioboto3.Session(**self._session_kwargs)
            self._client = await self._session.client("s3", **self._client_kwargs).__aenter__()
            return self._client

    def _s3_key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def put(self, key: str, content: bytes) -> None:
        client = await self._get_client()
        await client.put_object(Bucket=self._bucket, Key=self._s3_key(key), Body=content)

    async def get(self, key: str) -> Optional[bytes]:
        client = await self._get_client()
        try:
            resp = await client.get_object(Bucket=self._bucket, Key=self._s3_key(key))
            return await resp["Body"].read()
        except client.exceptions.NoSuchKey:
            return None
        except Exception as exc:
            # Some SDK paths raise a generic ClientError for missing keys.
            if "NoSuchKey" in str(exc) or "404" in str(exc):
                return None
            raise

    async def delete(self, key: str) -> bool:
        # head_object immediately before delete_object (rather than the old
        # public exists()-then-delete() two-call pattern) narrows, but does
        # not eliminate, the TOCTOU window; delete_object on S3 is idempotent
        # either way so this only affects the accuracy of the return value.
        client = await self._get_client()
        s3_key = self._s3_key(key)
        try:
            await client.head_object(Bucket=self._bucket, Key=s3_key)
        except Exception:
            return False
        await client.delete_object(Bucket=self._bucket, Key=s3_key)
        return True

    async def delete_prefix(self, prefix: str) -> int:
        client = await self._get_client()
        s3_prefix = self._s3_key(prefix)
        paginator = client.get_paginator("list_objects_v2")
        count = 0
        async for page in paginator.paginate(Bucket=self._bucket, Prefix=s3_prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue
            await client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
            )
            count += len(objects)
        return count

    async def exists(self, key: str) -> bool:
        client = await self._get_client()
        try:
            await client.head_object(Bucket=self._bucket, Key=self._s3_key(key))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._client = None

    # ── URLs ──────────────────────────────────────────────────

    async def get_public_url(self, key: str) -> Optional[str]:
        if not self._public:
            return None
        s3_key = self._s3_key(key)
        if self._public_base_url:
            return f"{self._public_base_url}/{s3_key}"
        if self._endpoint_url:
            # R2 / MinIO / custom S3-compatible endpoint
            return f"{self._endpoint_url.rstrip('/')}/{self._bucket}/{s3_key}"
        # Standard AWS S3 virtual-hosted URL
        region = self._session_kwargs.get("region_name", "us-east-1")
        if region == "us-east-1":
            return f"https://{self._bucket}.s3.amazonaws.com/{s3_key}"
        return f"https://{self._bucket}.s3.{region}.amazonaws.com/{s3_key}"

    async def get_signed_url(self, key: str, expires_in: int = 3600) -> Optional[str]:
        client = await self._get_client()
        try:
            return await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": self._s3_key(key)},
                ExpiresIn=expires_in,
            )
        except Exception as exc:
            logger.warning("S3Backend: could not create presigned URL: %s", exc)
            return None


# ─────────────────────────────────────────────────────────────
# Supabase Storage backend
# ─────────────────────────────────────────────────────────────

class SupabaseBackend(StorageBackend):
    """
    Supabase Storage via the official supabase-py v2 SDK.
    Requires: pip install supabase. Storage key = {prefix}{key}.
    """

    # Supabase's storage `list()` endpoint paginates; this is its page size.
    _LIST_PAGE_SIZE = 100

    def __init__(
        self,
        url: str,
        key: str,
        bucket: str,
        prefix: str = "uploads/",
        public: bool = False,
    ) -> None:
        if not url or not key:
            raise ValueError("storage.supabase.url and storage.supabase.key are required.")
        if not bucket:
            raise ValueError("storage.supabase.bucket is required.")

        self._url = url
        self._key = key
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._public = public
        self._client = None
        self._client_lock = asyncio.Lock()
        logger.info("SupabaseBackend ready — url=%s bucket=%s prefix=%s", url, bucket, self._prefix)

    async def _get_storage(self):
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    try:
                        from supabase import acreate_client
                    except ImportError:
                        raise RuntimeError(
                            "supabase is required for the Supabase backend. Install it: pip install supabase"
                        )
                    self._client = await acreate_client(self._url, self._key)
        return self._client.storage.from_(self._bucket)

    def _full_path(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def _list_all(self, storage, folder: str) -> list:
        """Page through storage.list() until exhausted (SDK paginates internally)."""
        all_objects: list = []
        offset = 0
        while True:
            page = await storage.list(
                folder, {"limit": self._LIST_PAGE_SIZE, "offset": offset}
            )
            if not page:
                break
            all_objects.extend(page)
            if len(page) < self._LIST_PAGE_SIZE:
                break
            offset += self._LIST_PAGE_SIZE
        return all_objects

    async def put(self, key: str, content: bytes) -> None:
        storage = await self._get_storage()
        await storage.upload(
            path=self._full_path(key),
            file=content,
            file_options={"upsert": "true"},
        )

    async def get(self, key: str) -> Optional[bytes]:
        storage = await self._get_storage()
        try:
            return await storage.download(self._full_path(key))
        except Exception as exc:
            if "not found" in str(exc).lower() or "404" in str(exc):
                return None
            raise

    async def delete(self, key: str) -> bool:
        if not await self.exists(key):
            return False
        storage = await self._get_storage()
        await storage.remove([self._full_path(key)])
        return True

    async def delete_prefix(self, prefix: str) -> int:
        storage = await self._get_storage()
        full_prefix = self._full_path(prefix)
        try:
            objects = await self._list_all(storage, full_prefix.rstrip("/"))
        except Exception:
            return 0
        if not objects:
            return 0
        paths = [f"{full_prefix}{obj['name']}" for obj in objects if obj.get("name")]
        if not paths:
            return 0
        # Supabase's remove() also has a batch-size limit; chunk defensively.
        removed = 0
        for i in range(0, len(paths), self._LIST_PAGE_SIZE):
            chunk = paths[i : i + self._LIST_PAGE_SIZE]
            await storage.remove(chunk)
            removed += len(chunk)
        return removed

    async def exists(self, key: str) -> bool:
        storage = await self._get_storage()
        path = self._full_path(key)
        parent = "/".join(path.split("/")[:-1])
        name = path.split("/")[-1]
        try:
            objects = await self._list_all(storage, parent)
            return any(obj.get("name") == name for obj in objects)
        except Exception:
            return False

    async def get_public_url(self, key: str) -> Optional[str]:
        """Return the public URL (only if the bucket is public)."""
        if not self._public:
            return None
        storage = await self._get_storage()
        return storage.get_public_url(self._full_path(key))

    async def get_signed_url(self, key: str, expires_in: int = 3600) -> Optional[str]:
        """Return a signed URL valid for `expires_in` seconds."""
        storage = await self._get_storage()
        try:
            result = await storage.create_signed_url(self._full_path(key), expires_in)
            return result.get("signedURL") or result.get("signedUrl")
        except Exception as exc:
            logger.warning("Could not create signed URL: %s", exc)
            return None

    async def close(self) -> None:
        self._client = None


# ─────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────

def build_backend(config: Dict[str, Any], data_dir: Path) -> StorageBackend:
    """
    Build the storage backend from the extension config (int.yaml
    services.extensions.storage.config — ${VAR} placeholders are already
    resolved by the kernel before this function runs).

    data_dir: base directory used to resolve a relative `local.path` — pass
    the kernel's shared data/state directory, not a plugin-specific one,
    since this backend is shared across every plugin.
    """
    backend_name = (config.get("backend") or "local").lower()

    if backend_name == "local":
        local_cfg = config.get("local") or {}
        path_str = local_cfg.get("path") or "data/storage"
        root = Path(path_str) if Path(path_str).is_absolute() else data_dir / path_str
        return LocalBackend(
            root_dir=root,
            public_base_url=local_cfg.get("public_base_url") or None,
            url_secret=local_cfg.get("url_secret") or None,
        )

    if backend_name in ("s3", "r2"):
        cfg_key = "r2" if backend_name == "r2" else "s3"
        s3_cfg = config.get(cfg_key) or {}

        bucket = s3_cfg.get("bucket") or ""
        if not bucket:
            raise ValueError(f"storage.{cfg_key}.bucket is required for backend {backend_name}.")

        endpoint_url = s3_cfg.get("endpoint_url") or None
        if backend_name == "r2":
            account_id = s3_cfg.get("account_id") or ""
            if account_id and not endpoint_url:
                endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

        return S3Backend(
            bucket=bucket,
            region=s3_cfg.get("region") or "auto",
            access_key_id=s3_cfg.get("access_key_id") or "",
            secret_access_key=s3_cfg.get("secret_access_key") or "",
            prefix=s3_cfg.get("prefix") or "xstorage/",
            endpoint_url=endpoint_url,
            public=bool(s3_cfg.get("public", False)),
            public_base_url=s3_cfg.get("public_base_url") or None,
        )

    if backend_name == "supabase":
        sb_cfg = config.get("supabase") or {}
        return SupabaseBackend(
            url=sb_cfg.get("url") or "",
            key=sb_cfg.get("key") or "",
            bucket=sb_cfg.get("bucket") or "",
            prefix=sb_cfg.get("prefix") or "uploads/",
            public=bool(sb_cfg.get("public", False)),
        )

    raise ValueError(
        f"unknown storage backend: '{backend_name}'. Accepted values: local, s3, r2, supabase"
    )