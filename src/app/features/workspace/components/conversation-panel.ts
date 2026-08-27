import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslocoDirective, TranslocoService } from '@jsverse/transloco';
import { DonnaMark } from '../../../shared/brand/donna-mark';
import type { IconName } from '../../../shared/ui/icon-set';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiChip } from '../../../shared/ui/ui-chip';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { UiInput } from '../../../shared/ui/ui-input';
import { WorkspaceStore } from '../workspace.store';
import { DonnaInterjection } from './donna-interjection';
import { ResearchTrace } from './research-trace';
import { WorkspaceComposer } from './workspace-composer';

@Component({
  selector: 'conversation-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  // Sans display explicite, l'élément hôte reste inline : le `h-full` interne
  // n'a alors aucune hauteur de référence et le composer sort de l'écran.
  host: { class: 'block h-full min-h-0' },
  imports: [
    TranslocoDirective,
    DonnaMark,
    DonnaInterjection,
    ResearchTrace,
    UiButton,
    UiChip,
    UiIcon,
    UiInput,
    WorkspaceComposer,
  ],
  templateUrl: './conversation-panel.html',
})
export class ConversationPanel {
  protected readonly store = inject(WorkspaceStore);
  private readonly transloco = inject(TranslocoService);

  /** Index des points de l'indicateur de réflexion, pour décaler leur pulsation. */
  protected readonly dots = [0, 1, 2];

  protected readonly suggestions: readonly { icon: IconName; key: string }[] = [
    { icon: 'search', key: 'workspace.suggestions.search' },
    { icon: 'file-text', key: 'workspace.suggestions.analyze' },
    { icon: 'file-pen-line', key: 'workspace.suggestions.draft' },
  ];

  protected send(text: string): void {
    this.store.send(text);
  }

  /** Une suggestion vaut question : on envoie son libellé traduit. */
  protected sendSuggestion(key: string): void {
    this.store.send(this.transloco.translate(key));
  }
}
