from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class UsageOut(BaseModel):
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_rounds: int = 0
    rag_used: bool = False
    rag_skipped_by_gate: bool = False
    budget_hit: bool = False
    provider_fallbacks: int = 0


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
    # Comptabilité tokens de la requête (estimation — voir usage.py) : rend
    # le coût VISIBLE côté client pour piloter les budgets. Additif : les
    # clients qui l'ignorent ne cassent pas.
    usage: UsageOut | None = None


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
