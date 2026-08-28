import { Injectable, OnDestroy, inject } from '@angular/core';
import { Subject } from 'rxjs';
import { environment } from '../../../environments/environment';
import { TokenStorage } from '../auth/token-storage';

const PULSE_BASE = `${environment.apiUrl}/app/xpulse`;
const RECONNECT_DELAY_MS = 3000;

/** Émis par le pont xpulse (xauth/xlicense/xpayproxy) sur le canal "notification" — voir bridge/handlers.py et bridge/billing.py. */
export interface PulseNotification {
  readonly user_id?: string;
  readonly event_type: string;
  /** Déjà formaté et échappé côté serveur (html.escape) — texte à afficher tel quel. */
  readonly text: string;
  readonly [extra: string]: unknown;
}

/** Émis par chat.fire_reminder sur le canal "reminders" — voir chat/src/tasks.py. */
export interface PulseReminder {
  readonly user_id: string;
  readonly tenant_id: string;
  readonly type: 'reminder_due';
  readonly reminder_id: string;
  readonly conversation_id: string | null;
  readonly message_id: string | null;
  readonly content: string;
}

export type PulseEvent =
  | { readonly channel: 'notification'; readonly data: PulseNotification }
  | { readonly channel: 'reminders'; readonly data: PulseReminder };

/**
 * Flux SSE unique vers /app/xpulse/stream (notifications de sécurité/billing
 * + rappels programmés) — fetch + ReadableStream plutôt qu'EventSource, pour
 * pouvoir poser l'en-tête Authorization (voir ChatService.sendStream, même
 * contrainte). Le backend rejoue l'inbox Redis à la connexion : aucun
 * événement manqué pendant une déconnexion n'est perdu.
 */
@Injectable({ providedIn: 'root' })
export class PulseService implements OnDestroy {
  private readonly tokens = inject(TokenStorage);
  private abortController: AbortController | null = null;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private readonly events$ = new Subject<PulseEvent>();

  readonly stream = this.events$.asObservable();

  connect(): void {
    if (this.abortController || !this.tokens.accessToken) return;

    const controller = new AbortController();
    this.abortController = controller;
    void this.run(controller);
  }

  disconnect(): void {
    clearTimeout(this.reconnectTimer);
    this.abortController?.abort();
    this.abortController = null;
  }

  private async run(controller: AbortController): Promise<void> {
    try {
      const response = await fetch(
        `${PULSE_BASE}/stream?channels=notification&channels=reminders`,
        {
          headers: { Authorization: `Bearer ${this.tokens.accessToken}` },
          signal: controller.signal,
        },
      );
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let boundary: number;
        while ((boundary = buffer.indexOf('\n\n')) !== -1) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const parsed = this.parseBlock(block);
          if (parsed) this.events$.next(parsed);
        }
      }
    } catch {
      // Abort volontaire (disconnect) ou coupure réseau — dans les deux cas
      // silencieux : la reconnexion ci-dessous s'en charge si ce n'était
      // pas un abort volontaire.
    } finally {
      if (this.abortController === controller) {
        this.abortController = null;
        if (this.tokens.hasSession()) {
          this.reconnectTimer = setTimeout(() => this.connect(), RECONNECT_DELAY_MS);
        }
      }
    }
  }

  private parseBlock(block: string): PulseEvent | null {
    let channel = 'notification';
    let dataRaw = '';
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) channel = line.slice(6).trim();
      else if (line.startsWith('data:')) dataRaw += line.slice(5).trim();
    }
    if (!dataRaw) return null;

    try {
      const data = JSON.parse(dataRaw);
      if (channel === 'reminders') return { channel: 'reminders', data };
      return { channel: 'notification', data };
    } catch {
      return null;
    }
  }

  ngOnDestroy(): void {
    this.disconnect();
  }
}
