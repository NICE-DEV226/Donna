import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { UiReveal } from '../../../shared/ui/ui-reveal';
import { ConversationPreview } from './conversation-preview';

@Component({
  selector: 'loop-section',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiIcon, UiReveal, ConversationPreview],
  templateUrl: './loop-section.html',
})
export class LoopSection {
  protected readonly points = ['loop.points.ask', 'loop.points.read', 'loop.points.cite'] as const;
}
