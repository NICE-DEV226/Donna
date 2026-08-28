import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ConversationPanel } from './components/conversation-panel';
import { WorkspaceSetup } from './components/workspace-setup';
import { WorkspaceStore } from './workspace.store';

/** Vue par défaut du workspace : la mise en place tant qu'il n'y a pas de mémoire. */
@Component({
  selector: 'workspace-home',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block h-full min-h-0' },
  imports: [ConversationPanel, WorkspaceSetup],
  template: `
    @if (store.initialised()) {
      <conversation-panel />
    } @else {
      <workspace-setup />
    }
  `,
})
export class WorkspaceHome {
  protected readonly store = inject(WorkspaceStore);
}
