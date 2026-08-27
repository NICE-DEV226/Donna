import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { SpotAudit } from '../../../shared/spot/spot-audit';
import type { IconName } from '../../../shared/ui/icon-set';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { UiReveal } from '../../../shared/ui/ui-reveal';

@Component({
  selector: 'security-section',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, SpotAudit, UiIcon, UiReveal],
  templateUrl: './security-section.html',
})
export class SecuritySection {
  protected readonly items: readonly { icon: IconName; title: string; body: string }[] = [
    {
      icon: 'lock',
      title: 'security.items.scoped.title',
      body: 'security.items.scoped.body',
    },
    {
      icon: 'shield-check',
      title: 'security.items.encrypted.title',
      body: 'security.items.encrypted.body',
    },
    {
      icon: 'circle-check',
      title: 'security.items.audited.title',
      body: 'security.items.audited.body',
    },
  ];
}
