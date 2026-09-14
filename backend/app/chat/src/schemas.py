from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ContextStatusOut(BaseModel):
    """État de la compaction du contexte — visible à chaque réponse ET sur
    un endpoint dédié, pour que le frontend affiche la « santé » du contexte
    (barre de progression, badge compacté, etc.)."""
    total_messages: int
    covered_messages: int
    recent_messages: int
    summary_chars: int
    context_budget_used_pct: int
    compacted: bool


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
    usage: UsageOut | None = None
    context: ContextStatusOut | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    context: ContextStatusOut | None = None


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
