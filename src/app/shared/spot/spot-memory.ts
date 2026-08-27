import { ChangeDetectionStrategy, Component } from '@angular/core';
import { UiInView } from './ui-in-view';

/** Une pile de documents dont la clause pertinente se surligne. */
@Component({
  selector: 'spot-memory',
  changeDetection: ChangeDetectionStrategy.OnPush,
  hostDirectives: [UiInView],
  template: `
    <svg viewBox="0 0 200 140" aria-hidden="true">
      <rect
        class="spot-fill spot-line"
        x="44"
        y="16"
        width="98"
        height="98"
        rx="8"
        transform="rotate(-7 93 65)"
      />
      <rect
        class="spot-fill spot-line"
        x="50"
        y="20"
        width="98"
        height="98"
        rx="8"
        transform="rotate(-3 99 69)"
      />
      <rect class="spot-fill spot-line" x="56" y="26" width="98" height="100" rx="8" />

      <rect class="spot-bar-ink" x="70" y="46" width="46" height="5" rx="2.5" />
      <rect class="spot-bar" x="70" y="62" width="70" height="4" rx="2" />
      <rect class="spot-tint spot-grow" style="--i: 0" x="70" y="74" width="62" height="11" rx="3" />
      <rect class="spot-bar" x="70" y="94" width="54" height="4" rx="2" />
      <rect class="spot-bar" x="70" y="106" width="38" height="4" rx="2" />
    </svg>
  `,
})
export class SpotMemory {}
