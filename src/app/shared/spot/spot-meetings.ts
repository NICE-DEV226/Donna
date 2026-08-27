import { ChangeDetectionStrategy, Component } from '@angular/core';
import { UiInView } from './ui-in-view';

/** Une grille d'agenda où deux créneaux se posent sans se chevaucher. */
@Component({
  selector: 'spot-meetings',
  changeDetection: ChangeDetectionStrategy.OnPush,
  hostDirectives: [UiInView],
  template: `
    <svg viewBox="0 0 200 140" aria-hidden="true">
      <rect class="spot-fill spot-line" x="20" y="18" width="160" height="104" rx="8" />
      <line class="spot-line" x1="20" y1="42" x2="180" y2="42" />

      @for (column of columns; track column) {
        <rect class="spot-bar" [attr.x]="34 + column * 36" y="28" width="16" height="4" rx="2" />
        @for (row of rows; track row) {
          <rect
            class="spot-line"
            [attr.x]="34 + column * 36"
            [attr.y]="52 + row * 24"
            width="28"
            height="18"
            rx="4"
          />
        }
      }

      <!-- Le créneau retenu, puis le suivant : ils apparaissent l'un après l'autre. -->
      <rect class="spot-tint spot-pop" style="--i: 0" x="70" y="52" width="28" height="18" rx="4" />
      <rect class="spot-tint-ok spot-pop" style="--i: 1" x="106" y="76" width="28" height="18" rx="4" />
      <path class="spot-ok spot-pop" style="--i: 2" d="M114 85l4 4 8-9" />
    </svg>
  `,
})
export class SpotMeetings {
  protected readonly columns = [0, 1, 2, 3];
  protected readonly rows = [0, 1, 2];
}
