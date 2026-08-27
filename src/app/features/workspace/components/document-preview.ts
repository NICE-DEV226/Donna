import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { WorkspaceStore } from '../workspace.store';

/**
 * Lecture d'une source, à côté de la conversation.
 *
 * Un lien qui ouvre un onglet fait perdre le fil : on revient dans un
 * navigateur, plus dans un raisonnement. Le document s'ouvre donc ici, le
 * passage cité mis en évidence — et le lien vers l'original reste offert,
 * mais comme un choix explicite, pas comme le comportement par défaut.
 */
@Component({
  selector: 'document-preview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, TranslocoDirective, UiIcon],
  templateUrl: './document-preview.html',
})
export class DocumentPreview {
  protected readonly store = inject(WorkspaceStore);

  protected readonly base = computed(() => {
    const entry = this.store.openSource();
    return entry ? `workspace.research.entries.${entry.key}` : null;
  });

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.store.closeSource();
  }
}
