import { ChangeDetectionStrategy, Component } from '@angular/core';
import { UiInView } from './ui-in-view';

/** Quatre sources qui convergent vers une réponse unique, balayées par la recherche. */
@Component({
  selector: 'spot-search',
  changeDetection: ChangeDetectionStrategy.OnPush,
  hostDirectives: [UiInView],
  template: `
    <svg viewBox="0 0 200 140" aria-hidden="true">
      @for (source of sources; track source; let i = $index) {
        <g>
          <rect class="spot-fill spot-line" x="12" [attr.y]="18 + i * 28" width="44" height="20" rx="6" />
          <rect class="spot-bar" x="20" [attr.y]="25 + i * 28" width="28" height="5" rx="2.5" />
        </g>
        <path
          class="spot-line spot-draw"
          [style.--i]="i"
          [attr.d]="'M56 ' + (28 + i * 28) + 'H80c8 0 8 ' + (70 - (28 + i * 28)) + ' 16 ' + (70 - (28 + i * 28)) + 'h12'"
        />
      }

      <rect class="spot-fill spot-accent" x="112" y="46" width="76" height="48" rx="8" />
      <rect class="spot-bar-accent" x="126" y="60" width="36" height="5" rx="2.5" />
      <rect class="spot-bar" x="126" y="72" width="48" height="4" rx="2" />

      <rect class="spot-tint spot-sweep" x="86" y="12" width="10" height="116" rx="5" />
    </svg>
  `,
})
export class SpotSearch {
  protected readonly sources = [0, 1, 2, 3];
}
