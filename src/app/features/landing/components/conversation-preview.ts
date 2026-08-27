import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiChip } from '../../../shared/ui/ui-chip';
import { UiIcon } from '../../../shared/ui/ui-icon';

@Component({
  selector: 'conversation-preview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiButton, UiChip, UiIcon],
  templateUrl: './conversation-preview.html',
})
export class ConversationPreview {}
