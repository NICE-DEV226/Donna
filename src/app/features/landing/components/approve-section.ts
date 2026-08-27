import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiReveal } from '../../../shared/ui/ui-reveal';
import { ApprovalCard } from './approval-card';

@Component({
  selector: 'approve-section',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiReveal, ApprovalCard],
  templateUrl: './approve-section.html',
})
export class ApproveSection {}
