import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import type { IconName } from '../../../shared/ui/icon-set';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { WorkspaceStore } from '../workspace.store';

@Component({
  selector: 'connections-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiIcon],
  templateUrl: './connections-panel.html',
})
export class ConnectionsPanel {
  protected readonly store = inject(WorkspaceStore);

  protected icon(name: string): IconName {
    return name as IconName;
  }
}
