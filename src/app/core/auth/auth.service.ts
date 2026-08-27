import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

export interface Credentials {
  readonly email: string;
  readonly password: string;
}

export interface SignUpPayload extends Credentials {
  readonly fullName: string;
}

/**
 * Point d'entrée unique de l'authentification.
 *
 * ⚠️ Le backend DONNAT n'est pas encore branché : les trois méthodes simulent
 * un aller-retour réseau puis entrent dans le workspace. C'est ici — et nulle
 * part ailleurs — qu'il faudra brancher les vrais appels HTTP / OAuth.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly router = inject(Router);

  /** Vrai pendant une requête d'authentification, pour verrouiller les formulaires. */
  readonly pending = signal(false);

  signIn(credentials: Credentials): Promise<boolean> {
    return this.complete(credentials.email);
  }

  signUp(payload: SignUpPayload): Promise<boolean> {
    return this.complete(payload.email);
  }

  signInWithGoogle(): Promise<boolean> {
    return this.complete('google');
  }

  /** Quitte l'espace de travail. Le store du workspace meurt avec l'écran. */
  signOut(): Promise<boolean> {
    return this.router.navigate(['/login']);
  }

  private async complete(_identifier: string): Promise<boolean> {
    this.pending.set(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, 600));
      return await this.router.navigate(['/workspace']);
    } finally {
      this.pending.set(false);
    }
  }
}
