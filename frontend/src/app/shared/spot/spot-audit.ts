import { ChangeDetectionStrategy, Component } from '@angular/core';
import { UiInView } from './ui-in-view';

/** Un journal d'actions dont chaque ligne se valide à son tour. */
@Component({
  selector: 'spot-audit',
  changeDetection: ChangeDetectionStrategy.OnPush,
  hostDirectives: [UiInView],
  template: `
    <svg viewBox="0 0 200 140" aria-hidden="true">
      <rect class="spot-fill spot-line" x="18" y="16" width="164" height="108" rx="8" />
      <line class="spot-line" x1="60" y1="16" x2="60" y2="124" />

      @for (row of rows; track row.y; let i = $index) {
        <rect class="spot-bar" x="28" [attr.y]="row.y - 2" width="24" height="4" rx="2" />
        <rect class="spot-bar-ink" x="72" [attr.y]="row.y - 3" [attr.width]="row.width" height="5" rx="2.5" />
        <path class="spot-ok spot-pop" [style.--i]="i" [attr.d]="'M152 ' + row.y + 'l4 4 8-9'" />
      }
    </svg>
  `,
})
export class SpotAudit {
  protected readonly rows = [
    { y: 38, width: 58 },
    { y: 62, width: 44 },
    { y: 86, width: 66 },
    { y: 110, width: 38 },
  ];
}
