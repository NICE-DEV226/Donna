import { Injectable, OnDestroy, inject } from '@angular/core';
import { Subject } from 'rxjs';
import { environment } from '../../../environments/environment';
import { TokenStorage } from '../auth/token-storage';

/** Reflète les payloads broadcastés par ext.websocket côté backend (canal "user"). */
export interface MemoryFactSavedEvent {
  readonly conversation_id: string;
  readonly fact: string;
}

export interface DonnaQuestionEvent {
  readonly conversation_id: string;
  readonly question: string;
}

interface RagDocSlot {
  readonly document_id: string;
  readonly original_name: string;
  readonly status: string;
}

export interface RagIngestionStatusEvent {
  readonly tenant_id: string;
  readonly previous: RagDocSlot | null;
  readonly current: RagDocSlot | null;
  readonly next: RagDocSlot | null;
}

export type RealtimeEvent =
  | { readonly action: 'memory_fact_saved'; readonly payload: MemoryFactSavedEvent }
  | { readonly action: 'donna_question'; readonly payload: DonnaQuestionEvent }
  | { readonly action: 'rag_ingestion_status'; readonly payload: RagIngestionStatusEvent };

const RECONNECT_DELAY_MS = 3000;

/**
 * Connexion websocket unique vers /ws/user — reçoit tout ce que le backend
 * pousse en temps réel (mémoire, questions de clarification, indexation
 * RAG). PAS les rappels (reminder_due) ni les notifications xauth/billing :
 * ceux-ci passent par ext.pubsub/SSE (xpulse), un transport distinct — voir
 * PulseService.
 */
@Injectable({ providedIn: 'root' })
export class RealtimeService implements OnDestroy {
  private readonly tokens = inject(TokenStorage);
  private socket: WebSocket | null = null;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private readonly events$ = new Subject<RealtimeEvent>();

  readonly stream = this.events$.asObservable();

  connect(): void {
    if (this.socket || !this.tokens.accessToken) return;

    const url = `${environment.wsUrl}/ws/user?access_token=${encodeURIComponent(this.tokens.accessToken)}`;
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.onmessage = (raw) => this.handleMessage(raw.data);
    socket.onclose = () => {
      this.socket = null;
      if (this.tokens.hasSession()) {
        this.reconnectTimer = setTimeout(() => this.connect(), RECONNECT_DELAY_MS);
      }
    };
    socket.onerror = () => socket.close();
  }

  disconnect(): void {
    clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = null;
  }

  private handleMessage(raw: string): void {
    let envelope: { action?: string; payload?: unknown };
    try {
      envelope = JSON.parse(raw);
    } catch {
      return;
    }

    // WsManager._encode met `action` en MAJUSCULES sur le fil (voir
    // extensions/xwebsocket/ws.py) — on redescend en snake_case ici pour
    // matcher les noms d'événements tels qu'émis côté chat/rag.
    const action = envelope.action?.toLowerCase();
    if (action === 'memory_fact_saved' || action === 'donna_question' || action === 'rag_ingestion_status') {
      this.events$.next({ action, payload: envelope.payload } as RealtimeEvent);
    }
  }

  ngOnDestroy(): void {
    this.disconnect();
  }
}
