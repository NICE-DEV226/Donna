import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiAvatar } from '../../../shared/ui/ui-avatar';
import { UiReveal } from '../../../shared/ui/ui-reveal';

@Component({
  selector: 'voices-section',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiAvatar, UiReveal],
  templateUrl: './voices-section.html',
})
export class VoicesSection {
  // Personnages de Suits : le propos est illustratif, pas un vrai témoignage client.
  protected readonly quotes = ['one', 'two', 'three', 'four'].map((key) => ({
    body: `voices.quotes.${key}.body`,
    name: `voices.quotes.${key}.name`,
    role: `voices.quotes.${key}.role`,
  }));
}
