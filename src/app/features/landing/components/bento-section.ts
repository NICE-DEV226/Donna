import { NgComponentOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, type Type } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { SpotAudit } from '../../../shared/spot/spot-audit';
import { SpotBrief } from '../../../shared/spot/spot-brief';
import { SpotDraft } from '../../../shared/spot/spot-draft';
import { SpotMeetings } from '../../../shared/spot/spot-meetings';
import { SpotMemory } from '../../../shared/spot/spot-memory';
import { SpotSearch } from '../../../shared/spot/spot-search';
import { UiReveal } from '../../../shared/ui/ui-reveal';

interface Tile {
  /** Illustration maison, rendue par NgComponentOutlet. */
  readonly illustration: Type<unknown>;
  readonly title: string;
  readonly body: string;
  /** Largeur sur la grille de 6 colonnes. */
  readonly span: string;
  /** Teinte — uniquement des valeurs de la palette DONNA. */
  readonly tone: string;
  /** Tuile pleine largeur : illustration à côté du texte plutôt qu'au-dessus. */
  readonly wide?: boolean;
}

@Component({
  selector: 'bento-section',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgComponentOutlet, TranslocoDirective, UiReveal],
  templateUrl: './bento-section.html',
})
export class BentoSection {
  protected readonly tiles: readonly Tile[] = [
    {
      illustration: SpotBrief,
      title: 'bento.tiles.brief.title',
      body: 'bento.tiles.brief.body',
      span: 'md:col-span-3',
      tone: 'bg-primary-soft',
    },
    {
      illustration: SpotSearch,
      title: 'bento.tiles.search.title',
      body: 'bento.tiles.search.body',
      span: 'md:col-span-3',
      tone: 'bg-surface',
    },
    {
      illustration: SpotDraft,
      title: 'bento.tiles.draft.title',
      body: 'bento.tiles.draft.body',
      span: 'md:col-span-2',
      tone: 'bg-success-soft',
    },
    {
      illustration: SpotMeetings,
      title: 'bento.tiles.meetings.title',
      body: 'bento.tiles.meetings.body',
      span: 'md:col-span-2',
      tone: 'bg-surface',
    },
    {
      illustration: SpotMemory,
      title: 'bento.tiles.memory.title',
      body: 'bento.tiles.memory.body',
      span: 'md:col-span-2',
      tone: 'bg-surface-raised',
    },
    {
      illustration: SpotAudit,
      title: 'bento.tiles.audit.title',
      body: 'bento.tiles.audit.body',
      span: 'md:col-span-6',
      tone: 'bg-surface',
      wide: true,
    },
  ];
}
