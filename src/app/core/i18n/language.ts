import { Injectable, effect, inject, signal } from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { TranslocoService } from '@jsverse/transloco';

export const LANGUAGES = [
  { code: 'en', label: 'EN', name: 'English' },
  { code: 'fr', label: 'FR', name: 'Français' },
] as const;

export type LanguageCode = (typeof LANGUAGES)[number]['code'];

export const DEFAULT_LANGUAGE: LanguageCode = 'en';

const STORAGE_KEY = 'donnat.lang';

const isSupported = (value: unknown): value is LanguageCode =>
  LANGUAGES.some((l) => l.code === value);

/** Langue active, persistée entre les visites et reflétée sur <html lang>. */
@Injectable({ providedIn: 'root' })
export class Language {
  private readonly transloco = inject(TranslocoService);
  private readonly document = inject(DOCUMENT);

  readonly current = signal<LanguageCode>(this.restore());
  readonly available = LANGUAGES;

  constructor() {
    effect(() => {
      const lang = this.current();
      this.transloco.setActiveLang(lang);
      this.document.documentElement.lang = lang;
      // localStorage peut lever (navigation privée, cookies bloqués).
      try {
        localStorage.setItem(STORAGE_KEY, lang);
      } catch {
        /* préférence non persistée, sans conséquence */
      }
    });
  }

  set(lang: LanguageCode): void {
    this.current.set(lang);
  }

  private restore(): LanguageCode {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (isSupported(stored)) return stored;
    } catch {
      /* pas d'accès au stockage */
    }
    // On ne devine PAS depuis navigator.language : l'anglais est la langue par défaut du produit.
    return DEFAULT_LANGUAGE;
  }
}
