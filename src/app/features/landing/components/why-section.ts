import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import type { IconName } from '../../../shared/ui/icon-set';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { UiReveal } from '../../../shared/ui/ui-reveal';

@Component({
  selector: 'why-section',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiIcon, UiReveal],
  templateUrl: './why-section.html',
})
export class WhySection {
  protected readonly items: readonly { icon: IconName; title: string; body: string }[] = [
    { icon: 'brain', title: 'why.items.context.title', body: 'why.items.context.body' },
    { icon: 'zap', title: 'why.items.act.title', body: 'why.items.act.body' },
    { icon: 'shield-check', title: 'why.items.trace.title', body: 'why.items.trace.body' },
  ];
}
