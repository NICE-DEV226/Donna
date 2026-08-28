import { ChangeDetectionStrategy, Component } from '@angular/core';
import { UiInView } from './ui-in-view';

/** Un panneau de briefing dont les lignes se posent une à une. */
@Component({
  selector: 'spot-brief',
  changeDetection: ChangeDetectionStrategy.OnPush,
  hostDirectives: [UiInView],
  template: `
    <svg viewBox="0 0 200 140" aria-hidden="true">
      <rect class="spot-fill spot-line" x="20" y="18" width="160" height="104" rx="10" />
      <line class="spot-line" x1="20" y1="46" x2="180" y2="46" />
      <rect class="spot-bar-ink" x="34" y="29" width="52" height="5" rx="2.5" />

      <circle class="spot-accent" cx="162" cy="32" r="7" />
      <path class="spot-accent" d="M162 28v4.5l3 2" />

      <g class="spot-rise" style="--i: 0">
        <circle class="spot-bar-accent" cx="36" cy="60" r="3.5" />
        <rect class="spot-bar-ink" x="48" y="56" width="88" height="5" rx="2.5" />
        <rect class="spot-bar" x="48" y="66" width="52" height="4" rx="2" />
      </g>
      <g class="spot-rise" style="--i: 1">
        <circle class="spot-bar" cx="36" cy="84" r="3.5" />
        <rect class="spot-bar-ink" x="48" y="80" width="70" height="5" rx="2.5" />
        <rect class="spot-bar" x="48" y="90" width="40" height="4" rx="2" />
      </g>
      <g class="spot-rise" style="--i: 2">
        <circle class="spot-bar" cx="36" cy="106" r="3.5" />
        <rect class="spot-bar-ink" x="48" y="102" width="58" height="5" rx="2.5" />
      </g>
    </svg>
  `,
})
export class SpotBrief {}
