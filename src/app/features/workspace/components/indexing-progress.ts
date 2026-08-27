import { ChangeDetectionStrategy, Component, effect, inject, untracked } from '@angular/core';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { TranslocoDirective, TranslocoService } from '@jsverse/transloco';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { INGEST_STEPS, WorkspaceStore } from '../workspace.store';

/**
 * Progression de l'indexation initiale, dans le rail droit.
 *
 * Volontairement NON bloquante : une entreprise qui verse des milliers de
 * documents attendrait plusieurs minutes derrière un voile. L'indexation se
 * poursuit pendant que l'utilisateur discute — DONNA répond déjà sur ce
 * qu'elle a lu.
 *
 * Ce panneau n'apparaît QUE pendant la construction de la mémoire. Les
 * questions posées ensuite ne l'affichent jamais.
 */
@Component({
  selector: 'indexing-progress',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiIcon],
  templateUrl: './indexing-progress.html',
})
export class IndexingProgress {
  protected readonly store = inject(WorkspaceStore);
  protected readonly steps = INGEST_STEPS;

  private readonly announcer = inject(LiveAnnouncer);
  private readonly transloco = inject(TranslocoService);

  constructor() {
    // L'indexation est une attente : sans annonce, un utilisateur non-voyant
    // ne saurait pas que quelque chose progresse.
    effect(() => {
      const step = this.store.ingestStep();
      if (!step) return;
      untracked(() => {
        const label = this.transloco.translate(`workspace.setup.indexing.${step}`);
        this.announcer.announce(
          this.transloco.translate('workspace.setup.indexing.announce', { step: label }),
          'polite',
        );
      });
    });
  }
}
