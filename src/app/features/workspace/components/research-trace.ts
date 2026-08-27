import {
  ChangeDetectionStrategy,
  Component,
  booleanAttribute,
  computed,
  input,
  output,
  signal,
} from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiIcon } from '../../../shared/ui/ui-icon';
import type { TraceEntry } from '../workspace.store';

interface ExcerptParts {
  readonly before: string;
  readonly match: string;
  readonly after: string;
}

/**
 * Ce que DONNA a consulté, dans le fil, repliable.
 *
 * Ouvert tant que la recherche est en cours — on voit les sources arriver —
 * puis replié une fois la réponse écrite : la preuve reste accessible sans
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

  /** Demande d'ouverture d'une source dans le panneau de lecture. */
  readonly read = output<TraceEntry>();

  private readonly manual = signal<boolean | null>(null);

  /** Ouvert d'office pendant la recherche, replié ensuite — sauf choix explicite. */
  protected readonly open = computed(() => this.manual() ?? this.live());

  protected toggle(open: boolean): void {
    this.manual.set(open);
  }

  protected keyOf(entry: TraceEntry): string {
    return `workspace.research.entries.${entry.key}`;
  }

  /**
   * Découpe l'extrait autour du passage retenu. Aucun HTML n'est injecté :
   * les trois morceaux sont rendus comme du texte, le surlignage est du CSS.
   */
  protected parts(excerpt: string, match: string): ExcerptParts {
    const index = excerpt.indexOf(match);
    if (index < 0) return { before: excerpt, match: '', after: '' };
    return {
      before: excerpt.slice(0, index),
      match,
      after: excerpt.slice(index + match.length),
    };
  }
}
