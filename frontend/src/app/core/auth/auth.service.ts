import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { TokenStorage } from './token-storage';

export interface Credentials {
  readonly email: string;
  readonly password: string;
}

export interface SignUpPayload extends Credentials {
  readonly fullName: string;
}

/** Reflète xauth TokenResponse (backend/app/xauth/src/schemas/auth.py). */
interface TokenResponse {
  readonly access_token: string;
  readonly refresh_token: string;
  readonly token_type: string;
  readonly user_id?: string | null;
  readonly tenant_id?: string | null;
  readonly mfa_required: boolean;
  readonly mfa_token?: string | null;
  readonly needs_tenant_setup: boolean;
  readonly tenants?: unknown[] | null;
}

const AUTH_BASE = `${environment.apiUrl}/app/auth`;

/** Reflète xauth (backend/app/xauth/src/routes/oauth.py::list_linked_accounts). */
export interface LinkedAccount {
  readonly provider: string;
  readonly provider_email: string;
  readonly provider_name: string | null;
  readonly provider_avatar: string | null;
  readonly linked_at: string;
}

/**
 * Point d'entrée unique de l'authentification — appelle le vrai backend xauth.
 *
 * Pas d'écran de sélection/création de tenant côté produit pour l'instant
 * (voir décision "stub plat" sur les Projects) : un utilisateur sans tenant
 * après login/register (`needs_tenant_setup`) se voit auto-créer le sien,
 * silencieusement, via /setup/create — un slug dérivé de son nom + suffixe
 * aléatoire pour éviter les collisions.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly tokens = inject(TokenStorage);

  /** Vrai pendant une requête d'authentification, pour verrouiller les formulaires. */
  readonly pending = signal(false);
  /** Clé de traduction de la dernière erreur, ou null. Le template fait `t(error()!)`. */
  readonly error = signal<string | null>(null);

  async signIn(credentials: Credentials): Promise<boolean> {
    this.pending.set(true);
    this.error.set(null);
    try {
      let session = await firstValueFrom(
        this.http.post<TokenResponse>(`${AUTH_BASE}/login`, credentials),
      );
      if (session.needs_tenant_setup) {
        session = await this.autoCreateTenant(session.refresh_token, credentials.email);
      }
      this.persist(session);
      return await this.router.navigate(['/workspace']);
    } catch (err) {
      this.error.set(this.isUnauthorized(err) ? 'auth.errors.invalidCredentials' : 'auth.errors.generic');
      return false;
    } finally {
      this.pending.set(false);
    }
  }

  async signUp(payload: SignUpPayload): Promise<boolean> {
    this.pending.set(true);
    this.error.set(null);
    try {
      await firstValueFrom(
        this.http.post(`${AUTH_BASE}/register`, {
          email: payload.email,
          password: payload.password,
        }),
      );
      let session = await firstValueFrom(
        this.http.post<TokenResponse>(`${AUTH_BASE}/login`, {
          email: payload.email,
          password: payload.password,
        }),
      );
      if (session.needs_tenant_setup) {
        session = await this.autoCreateTenant(session.refresh_token, payload.fullName);
      }
      this.persist(session);
      return await this.router.navigate(['/workspace']);
    } catch (err) {
      const conflict = err instanceof HttpErrorResponse && (err.status === 409 || err.status === 400);
      this.error.set(conflict ? 'auth.errors.emailTaken' : 'auth.errors.generic');
      return false;
    } finally {
      this.pending.set(false);
    }
  }

  /**
   * Demande un lien de réinitialisation.
   *
   * Le backend répond 202 quoi qu'il arrive (voir routes/password.py) —
   * ne dit jamais si l'adresse correspond à un compte, pour ne pas permettre
   * l'énumération des utilisateurs. On reste silencieux ici aussi, y compris
   * en cas d'erreur réseau : le message affiché à l'écran est le même dans
   * tous les cas (voir reset-page).
   */
  async requestReset(email: string): Promise<void> {
    this.pending.set(true);
    try {
      await firstValueFrom(this.http.post(`${AUTH_BASE}/password/forgot`, { email }));
    } catch {
      // Silencieux, volontairement — voir docstring.
    } finally {
      this.pending.set(false);
    }
  }

  /** Redirige vers le flow OAuth réel — le navigateur quitte l'app, pas d'appel XHR. */
  async signInWithGoogle(): Promise<boolean> {
    window.location.href = `${AUTH_BASE}/oauth/google/authorize?direct=true`;
    return true;
  }

  /**
   * Lie Google au compte actuellement connecté (ex : compte créé par email +
   * mot de passe) — pour un utilisateur déjà authentifié, voir settings-page.
   *
   * Appel authentifié (l'intercepteur pose le Bearer) SANS `direct` : le
   * backend embarque alors le user_id courant dans le state OAuth et lie ce
   * provider à CE compte au retour, plutôt que de chercher/créer par email
   * (voir oauth.py::authorize). `window.location.href` ensuite : la
   * redirection vers Google est une vraie navigation, jamais un fetch.
   */
  async startLinkGoogle(): Promise<void> {
    const redirect = encodeURIComponent(`${window.location.origin}/workspace/settings`);
    const { auth_url } = await firstValueFrom(
      this.http.get<{ auth_url: string }>(
        `${AUTH_BASE}/oauth/google/authorize?redirect=${redirect}`,
      ),
    );
    window.location.href = auth_url;
  }

  listLinkedAccounts(): Promise<LinkedAccount[]> {
    return firstValueFrom(this.http.get<LinkedAccount[]>(`${AUTH_BASE}/oauth/me/accounts`));
  }

  unlinkAccount(provider: string): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`${AUTH_BASE}/oauth/${provider}/unlink`));
  }

  /**
   * Termine un callback OAuth reçu avec un access_token direct (tenant déjà
   * résolu) — voir oauth-callback-page, seul appelant.
   */
  async completeDirectSession(accessToken: string, refreshToken: string): Promise<boolean> {
    this.tokens.set({ accessToken, refreshToken, tenantId: null });
    return this.router.navigate(['/workspace']);
  }

  /**
   * Callback OAuth sans access_token, needs_tenant_setup=true : même repli
   * "stub plat" que l'inscription email/mot de passe — tenant auto-créé,
   * sans écran de choix de nom (voir décision Projects).
   */
  async completeOAuthOnboarding(refreshToken: string): Promise<boolean> {
    try {
      const session = await this.autoCreateTenant(refreshToken, 'My workspace');
      this.persist(session);
      return await this.router.navigate(['/workspace']);
    } catch {
      return this.router.navigate(['/login'], { queryParams: { error: 'auth.errors.generic' } });
    }
  }

  /**
   * Callback OAuth multi-tenant : plutôt qu'un écran de choix (hors scope,
   * voir décision Projects), on prend le premier tenant renvoyé.
   */
  async completeOAuthTenantSelection(refreshToken: string, tenantId: string): Promise<boolean> {
    try {
      const session = await firstValueFrom(
        this.http.post<TokenResponse>(`${AUTH_BASE}/select-tenant`, {
          refresh_token: refreshToken,
          tenant_id: tenantId,
        }),
      );
      this.persist(session);
      return await this.router.navigate(['/workspace']);
    } catch {
      return this.router.navigate(['/login'], { queryParams: { error: 'auth.errors.generic' } });
    }
  }

  /** Quitte l'espace de travail. Le store du workspace meurt avec l'écran. */
  async signOut(): Promise<boolean> {
    this.tokens.clear();
    return this.router.navigate(['/login']);
  }

  private async autoCreateTenant(refreshToken: string, label: string): Promise<TokenResponse> {
    const base = this.slugify(label) || 'workspace';
    const slug = `${base}-${Math.random().toString(36).slice(2, 8)}`;
    return firstValueFrom(
      this.http.post<TokenResponse>(`${AUTH_BASE}/setup/create`, {
        refresh_token: refreshToken,
        name: label.trim() || 'My workspace',
        slug,
      }),
    );
  }

  private slugify(value: string): string {
    return value
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '') // diacritiques (é -> e, etc.)
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '');
  }

  private isUnauthorized(err: unknown): boolean {
    return err instanceof HttpErrorResponse && (err.status === 401 || err.status === 400);
  }

  private persist(session: TokenResponse): void {
    this.tokens.set({
      accessToken: session.access_token,
      refreshToken: session.refresh_token,
      tenantId: session.tenant_id ?? null,
    });
  }
}
