import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiIcon } from '../../../shared/ui/ui-icon';
import type { TraceEntry } from '../workspace.store';

/**
 * Ce que DONNA a fait pendant qu'elle réfléchissait — outils invoqués
 * (mémoire, calendrier, email, documents…), dans le fil.
 *
 * Pas des sources citables : un outil comme `set_reminder` ou
 * `save_generated_document` n'est pas un document à relire. Les vraies
 * citations RAG vivent à part, sous la réponse (voir message.sources dans
 * conversation-panel.html).
 *
 * La trace est TOUJOURS rendue déroulée : le pliage est la responsabilité du
 * panneau parent (conversation-panel), jamais d'un clic sur la trace — comme
 * ChatGPT, elle s'affiche d'elle-même et ne demande aucune manip pour être
 * relue. Le parent la borne (hauteur max + défilement interne).
 */
@Component({
  selector: 'research-trace',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiIcon],
  templateUrl: './research-trace.html',
})
export class ResearchTrace {
  readonly entries = input.required<readonly TraceEntry[]>();
  /** Recherche en cours : le libellé passe en « Donna réfléchit… ». */
  readonly live = input(false, { transform: booleanAttribute });

  /** "save_generated_document" → "Save generated document" — lisible sans dictionnaire de libellés par outil. */
  protected label(name: string): string {
    return name.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
  }
}