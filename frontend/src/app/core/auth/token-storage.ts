import { Injectable, signal } from '@angular/core';

const ACCESS_KEY = 'donna.access_token';
const REFRESH_KEY = 'donna.refresh_token';
const TENANT_KEY = 'donna.tenant_id';

/**
 * Accès centralisé aux jetons — localStorage, pas de cookie (pas de backend
 * cookie-aware ici, voir xauth : Bearer uniquement). Le signal `hasSession`
 * permet aux guards/composants de réagir sans relire le storage à chaque fois.
 */
@Injectable({ providedIn: 'root' })
export class TokenStorage {
  readonly hasSession = signal(this.readAccessToken() !== null);

  private readAccessToken(): string | null {
    try {
      return localStorage.getItem(ACCESS_KEY);
    } catch {
      return null;
    }
  }

  get accessToken(): string | null {
    return this.readAccessToken();
  }

  get refreshToken(): string | null {
    try {
      return localStorage.getItem(REFRESH_KEY);
    } catch {
      return null;
    }
  }

  get tenantId(): string | null {
    try {
      return localStorage.getItem(TENANT_KEY);
    } catch {
      return null;
    }
  }

  set(tokens: { accessToken: string; refreshToken: string; tenantId: string | null }): void {
    try {
      localStorage.setItem(ACCESS_KEY, tokens.accessToken);
      localStorage.setItem(REFRESH_KEY, tokens.refreshToken);
      if (tokens.tenantId) localStorage.setItem(TENANT_KEY, tokens.tenantId);
    } catch {
      // Stockage indisponible (navigation privée stricte...) : la session ne
      // survivra pas à un refresh, mais l'appli reste utilisable pour l'onglet en cours.
    }
    this.hasSession.set(true);
  }

  clear(): void {
    try {
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
      localStorage.removeItem(TENANT_KEY);
    } catch {
      // ignore
    }
    this.hasSession.set(false);
  }
}
