from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class SourceOut(BaseModel):
    doc_id: str
    original_name: str
    excerpt: str
    file_url: str


class AttachmentOut(BaseModel):
    id: str
    kind: str
    original_name: str
    mime_type: str
    file_url: str
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    sources: list[SourceOut] = []
    memory_notes: list[str] = []
    attachments: list[AttachmentOut] = []


class ConversationOut(BaseModel):
    id: str
    title: str


class RenameConversationRequest(BaseModel):
    title: str


class MessageOut(BaseModel):
    role: str
    content: str
    attachments: list[AttachmentOut] = []


class FactOut(BaseModel):
    id: str
    fact: str
    created_at: datetime


class ReminderOut(BaseModel):
    id: str
    content: str
    status: str
    due_at: datetime | None
    created_at: datetime


class PendingActionOut(BaseModel):
    id: str
    kind: str
    summary: str
    status: str
    created_at: datetime


class SetProviderRequest(BaseModel):
    provider: str


class ProviderOut(BaseModel):
    provider: str
