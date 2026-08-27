import { LiveAnnouncer } from '@angular/cdk/a11y';
import { Injectable, inject, signal } from '@angular/core';

export interface Toast {
  readonly id: number;
  readonly titleKey: string;
  /** Paramètres d'interpolation du titre (nom du client, par exemple). */
  readonly titleParams?: Record<string, string>;
  readonly bodyKey?: string;
  readonly linkLabelKey?: string;
  readonly url?: string;
}

/** Durée d'affichage avant retrait automatique. */
const LIFETIME = 6000;

/**
 * File de notifications non bloquantes.
 *
 * Elles signalent ce que DONNA décide en arrière-plan — typiquement un ajout à
 * la mémoire de l'entreprise. Jamais de modal : l'utilisateur n'a rien à
 * confirmer, il doit seulement pouvoir le savoir, et le lire s'il le souhaite.
 */
@Injectable({ providedIn: 'root' })
export class Toasts {
  private readonly announcer = inject(LiveAnnouncer);
  private readonly timers = new Map<number, ReturnType<typeof setTimeout>>();
  private nextId = 1;

  readonly items = signal<readonly Toast[]>([]);
  /** Ce qui a été notifié, même après disparition : la cloche doit pouvoir le redonner. */
  readonly history = signal<readonly Toast[]>([]);

  push(toast: Omit<Toast, 'id'>, announcement?: string): number {
    const id = this.nextId++;
    const entry: Toast = { ...toast, id };
    this.items.update((list) => [...list, entry]);
    this.history.update((list) => [entry, ...list]);

    // Une notification visuelle qui ne s'annonce pas n'existe pas pour tout le monde.
    if (announcement) this.announcer.announce(announcement, 'polite');

    this.timers.set(
      id,
      setTimeout(() => this.dismiss(id), LIFETIME),
    );
    return id;
  }

  dismiss(id: number): void {
    clearTimeout(this.timers.get(id));
    this.timers.delete(id);
    this.items.update((list) => list.filter((toast) => toast.id !== id));
  }

  clear(): void {
    for (const timer of this.timers.values()) clearTimeout(timer);
    this.timers.clear();
    this.items.set([]);
  }

  clearHistory(): void {
    this.history.set([]);
  }
}
