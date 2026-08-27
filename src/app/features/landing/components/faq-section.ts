import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { UiReveal } from '../../../shared/ui/ui-reveal';

@Component({
  selector: 'faq-section',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiIcon, UiReveal],
  templateUrl: './faq-section.html',
})
export class FaqSection {
  protected readonly items = ['data', 'access', 'act', 'wrong', 'setup'].map((key) => ({
    question: `faq.items.${key}.q`,
    answer: `faq.items.${key}.a`,
  }));
}
