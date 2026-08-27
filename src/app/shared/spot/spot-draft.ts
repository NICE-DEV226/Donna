import { ChangeDetectionStrategy, Component } from '@angular/core';
import { UiInView } from './ui-in-view';

/** Un document dont les deux dernières lignes s'écrivent sous la plume. */
@Component({
  selector: 'spot-draft',
  changeDetection: ChangeDetectionStrategy.OnPush,
  hostDirectives: [UiInView],
  template: `
    <svg viewBox="0 0 200 140" aria-hidden="true">
      <rect class="spot-fill spot-line" x="34" y="14" width="106" height="112" rx="8" />
      <rect class="spot-bar-ink" x="50" y="34" width="58" height="5" rx="2.5" />
      <rect class="spot-bar" x="50" y="50" width="74" height="4" rx="2" />
      <rect class="spot-bar" x="50" y="62" width="62" height="4" rx="2" />

      <path class="spot-accent spot-draw" style="--i: 0" d="M50 80h56" />
      <path class="spot-accent spot-draw" style="--i: 1" d="M50 96h34" />

      <path class="spot-accent" d="M150 78l16-16 8 8-16 16-11 3z" />
      <path class="spot-accent" d="M158 70l8 8" />
    </svg>
  `,
})
export class SpotDraft {}
