import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { TokenStorage } from '../auth/token-storage';

const CHAT_BASE = `${environment.apiUrl}/app/chat`;

export interface SourceOut {
  readonly doc_id: string;
  readonly original_name: string;
  readonly excerpt: string;
  readonly file_url: string;
}

export interface AttachmentOut {
  readonly id: string;
  readonly kind: string;
  readonly original_name: string;
  readonly mime_type: string;
  readonly file_url: string;
  readonly created_at: string;
}

export interface ChatResponse {
  readonly conversation_id: string;
  readonly reply: string;
  readonly sources: readonly SourceOut[];
  readonly memory_notes: readonly string[];
  readonly attachments: readonly AttachmentOut[];
}

export interface ConversationOut {
  readonly id: string;
  readonly title: string;
}

export interface MessageOut {
  readonly role: 'user' | 'assistant';
  readonly content: string;
  readonly attachments?: readonly AttachmentOut[];
}

/** Un événement du flux SSE /app/chat/stream — voir chat_routes.py::event_stream. */
export type ChatStreamEvent =
  | { readonly type: 'start'; readonly conversationId: string }
  | { readonly type: 'delta'; readonly text: string }
  | {
      readonly type: 'tool_call';
      readonly name: string;
      readonly result: string;
      readonly arguments: Readonly<Record<string, unknown>>;
    }
  | {
      readonly type: 'done';
      readonly sources: readonly SourceOut[];
      readonly memoryNotes: readonly string[];
      readonly attachments: readonly AttachmentOut[];
    }
  | { readonly type: 'error'; readonly message: string }
  | {
      readonly type: 'provider_fallback';
      readonly from: string;
      readonly to: string;
      readonly reason: string;
    };

@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly http = inject(HttpClient);
  private readonly tokens = inject(TokenStorage);

  listConversations(): Promise<ConversationOut[]> {
    return firstValueFrom(this.http.get<ConversationOut[]>(`${CHAT_BASE}/`));
  }

  getMessages(conversationId: string): Promise<MessageOut[]> {
    return firstValueFrom(
      this.http.get<MessageOut[]>(`${CHAT_BASE}/${conversationId}/messages`),
    );
  }

  renameConversation(conversationId: string, title: string): Promise<ConversationOut> {
    return firstValueFrom(
      this.http.patch<ConversationOut>(`${CHAT_BASE}/${conversationId}`, { title }),
    );
  }

  deleteConversation(conversationId: string): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`${CHAT_BASE}/${conversationId}`));
  }

  send(message: string, conversationId: string | null): Promise<ChatResponse> {
    return firstValueFrom(
      this.http.post<ChatResponse>(`${CHAT_BASE}/`, {
        message,
        conversation_id: conversationId,
      }),
    );
  }

  /**
   * Message avec fichier(s) joint(s) — endpoint dédié, non-streaming (voir
   * chat_routes.py::upload) : extraction/transcription avant tout appel LLM,
   * pas adapté à un flux SSE incrémental comme /stream.
   */
  upload(
    message: string,
    files: readonly File[],
    conversationId: string | null,
  ): Promise<ChatResponse> {
    const form = new FormData();
    if (message) form.append('message', message);
    if (conversationId) form.append('conversation_id', conversationId);
    for (const file of files) form.append('files', file, file.name);
    return firstValueFrom(this.http.post<ChatResponse>(`${CHAT_BASE}/upload`, form));
  }

  /**
   * Envoi en streaming (SSE) — fetch + ReadableStream plutôt qu'EventSource,
   * pour pouvoir poser l'en-tête Authorization (EventSource ne le permet pas).
   * L'appelant DOIT consommer le générateur jusqu'au bout ou l'annuler via
   * AbortController pour libérer la connexion.
   */
  async *sendStream(
    message: string,
    conversationId: string | null,
    signal?: AbortSignal,
  ): AsyncGenerator<ChatStreamEvent> {
    const response = await fetch(`${CHAT_BASE}/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(this.tokens.accessToken ? { Authorization: `Bearer ${this.tokens.accessToken}` } : {}),
      },
      body: JSON.stringify({ message, conversation_id: conversationId }),
      signal,
    });

    if (!response.ok || !response.body) {
      yield { type: 'error', message: `HTTP ${response.status}` };
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Un événement SSE = un bloc "event: X\ndata: Y" séparé par une ligne vide.
      let boundary: number;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = this.parseBlock(block);
        if (parsed) yield parsed;
      }
    }
  }

  private parseBlock(block: string): ChatStreamEvent | null {
    let eventName = 'message';
    let dataRaw = '';
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim();
      else if (line.startsWith('data:')) dataRaw += line.slice(5).trim();
    }
    if (!dataRaw) return null;

    let data: Record<string, unknown>;
    try {
      data = JSON.parse(dataRaw);
    } catch {
      return null;
    }

    switch (eventName) {
      case 'start':
        return { type: 'start', conversationId: String(data['conversation_id'] ?? '') };
      case 'tool_call':
        return {
          type: 'tool_call',
          name: String(data['name'] ?? ''),
          result: String(data['result'] ?? ''),
          arguments: (data['arguments'] as Record<string, unknown> | undefined) ?? {},
        };
      case 'error':
        return { type: 'error', message: String(data['error'] ?? '') };
      case 'provider_fallback':
        return {
          type: 'provider_fallback',
          from: String(data['from'] ?? ''),
          to: String(data['to'] ?? ''),
          reason: String(data['reason'] ?? ''),
        };
      case 'done':
        return {
          type: 'done',
          sources: (data['sources'] as SourceOut[] | undefined) ?? [],
          memoryNotes: (data['memory_notes'] as string[] | undefined) ?? [],
          attachments: (data['attachments'] as AttachmentOut[] | undefined) ?? [],
        };
      default:
        if (typeof data['delta'] === 'string') return { type: 'delta', text: data['delta'] };
        return null;
    }
  }
}
