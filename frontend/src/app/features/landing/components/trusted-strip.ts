import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';

@Component({
  selector: 'trusted-strip',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective],
  templateUrl: './trusted-strip.html',
})
export class TrustedStrip {
  // Cabinets fictifs, empruntés à l'univers de Suits — aucun vrai client n'est cité.
  protected readonly firms = [
    'Pearson Hardman',
    'Zane Specter Litt',
    'Rand Kaldor Zane',
    'Meridian Legal',
    'Gordon Schmidt Van Dyke',
    'Wakefield Cady',
  ] as const;
}
