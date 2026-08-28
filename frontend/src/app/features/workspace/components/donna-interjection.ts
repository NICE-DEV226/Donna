import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { DonnaMark } from '../../../shared/brand/donna-mark';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { WorkspaceStore } from '../workspace.store';

/**
 * Ce que DONNA amène d'elle-même, à l'heure qu'elle juge bonne.
 *
 * Ce n'est PAS un rappel. Un rappel vous rend votre propre phrase et vous
 * laisse le travail. Ici, elle arrive en avance, dit ce qui a changé depuis
 * votre demande, et le travail est déjà fait. La seule décision qui reste est
 * la vôtre : envoyer, ouvrir, ou repousser.
 */
@Component({
  selector: 'donna-interjection',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, DonnaMark, UiButton, UiIcon],
  templateUrl: './donna-interjection.html',
})
export class DonnaInterjection {
  readonly messageId = input.required<number>();

  protected readonly store = inject(WorkspaceStore);
  protected readonly changes = ['workspace.reminder.changes.one', 'workspace.reminder.changes.two'];
}
