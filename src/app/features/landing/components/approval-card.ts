import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiChip } from '../../../shared/ui/ui-chip';
import { UiIcon } from '../../../shared/ui/ui-icon';

/** Brouillon en attente : matérialise la règle « rien ne part sans validation ». */
@Component({
  selector: 'approval-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiButton, UiChip, UiIcon],
  templateUrl: './approval-card.html',
})
export class ApprovalCard {}
