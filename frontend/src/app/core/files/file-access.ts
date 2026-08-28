import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Toasts } from '../notifications/toasts';

/**
 * Ouvre un fichier servi par une route backend protégée (RAG, pièces
 * jointes de chat) — un `<a href>` classique ne peut pas porter l'en-tête
 * Authorization, donc on récupère le blob via HttpClient (intercepteur JWT
 * déjà branché) puis on l'ouvre dans un nouvel onglet via une URL objet
 * temporaire.
 */
@Injectable({ providedIn: 'root' })
export class FileAccess {
  private readonly http = inject(HttpClient);
  private readonly toasts = inject(Toasts);

  async open(fileUrl: string): Promise<void> {
    // Déjà une URL objet locale (aperçu d'un fichier tout juste joint, avant
    // tout aller-retour serveur — voir WorkspaceStore.localAttachment) :
    // rien à récupérer, on l'ouvre telle quelle.
    if (fileUrl.startsWith('blob:')) {
      window.open(fileUrl, '_blank', 'noopener');
      return;
    }

    try {
      const blob = await this.fetch(fileUrl);
      const objectUrl = URL.createObjectURL(blob);
      window.open(objectUrl, '_blank', 'noopener');
      // Le navigateur a eu le temps d'ouvrir/charger l'onglet ; libère la mémoire ensuite.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch {
      this.toasts.push({ titleKey: 'workspace.errors.fileOpenFailed' }, 'File open failed');
    }
  }

  /**
   * Récupère le fichier sans l'ouvrir — pour un rendu inline (aperçu PDF/image/
   * Office, voir attachment-preview) plutôt qu'un nouvel onglet. Laisse
   * l'appelant gérer ses propres erreurs : contrairement à `open`, pas de
   * toast ici (le panneau d'aperçu affiche son propre état d'échec).
   */
  fetch(fileUrl: string): Promise<Blob> {
    const url = fileUrl.startsWith('http') ? fileUrl : `${environment.apiUrl}${fileUrl}`;
    return firstValueFrom(this.http.get(url, { responseType: 'blob' }));
  }
}
