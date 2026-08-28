import { ChangeDetectionStrategy, Component, booleanAttribute, computed, input, signal } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiIcon } from '../../../shared/ui/ui-icon';
import type { TraceEntry } from '../workspace.store';

/**
 * Ce que DONNA a fait pendant qu'elle réfléchissait — outils invoqués
 * (mémoire, calendrier, email, documents…), dans le fil, repliable.
 *
 * Pas des sources citables : un outil comme `set_reminder` ou
 * `save_generated_document` n'est pas un document à relire. Les vraies
 * citations RAG vivent à part, sous la réponse (voir message.sources dans
 * conversation-panel.html).
 *
 * Ouvert tant que la recherche est en cours — on voit les outils arriver —
 * puis replié une fois la réponse écrite : la trace reste accessible sans
 * encombrer la lecture.
 */
@Component({
  selector: 'research-trace',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiIcon],
  templateUrl: './research-trace.html',
})
export class ResearchTrace {
  readonly entries = input.required<readonly TraceEntry[]>();
  /** Recherche en cours : le panneau reste ouvert et le libellé change. */
  readonly live = input(false, { transform: booleanAttribute });

  private readonly manual = signal<boolean | null>(null);

  /** Ouvert d'office pendant la recherche, replié ensuite — sauf choix explicite. */
  protected readonly open = computed(() => this.manual() ?? this.live());

  protected toggle(open: boolean): void {
    this.manual.set(open);
  }

  /** "save_generated_document" → "Save generated document" — lisible sans dictionnaire de libellés par outil. */
  protected label(name: string): string {
    return name.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
  }
}
