import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { FileAccess } from '../../../core/files/file-access';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { WorkspaceStore } from '../workspace.store';

/**
 * Lecture d'une source, à côté de la conversation.
 *
 * Un lien qui ouvre un onglet fait perdre le fil : on revient dans un
 * navigateur, plus dans un raisonnement. Le document s'ouvre donc ici, le
 * passage cité mis en évidence — et le lien vers l'original reste offert,
 * mais comme un choix explicite, pas comme le comportement par défaut.
 *
 * `source.url` est soit une route backend relative (`/app/rag/...`, à ouvrir
 * de façon authentifiée via FileAccess), soit une URL externe complète (démo
 * de l'agenda — voir WorkspaceStore.readAgenda) : un lien direct suffit alors.
 */
@Component({
  selector: 'document-preview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, TranslocoDirective, UiIcon],
  templateUrl: './document-preview.html',
})
export class DocumentPreview {
  protected readonly store = inject(WorkspaceStore);
  private readonly files = inject(FileAccess);

  protected isExternal(url: string): boolean {
    return url.startsWith('http');
  }

  protected openOriginal(url: string): void {
    void this.files.open(url);
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.store.closeSource();
  }
}
