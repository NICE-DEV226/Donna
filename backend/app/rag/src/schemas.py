from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    original_name: str
    status: str
    chunk_count: int
    error: str | None = None
    created_at: str
