import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, inject, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import { DonnaMark } from '../../../shared/brand/donna-mark';
import { createFlyout } from '../../../shared/ui/flyout';
import type { IconName } from '../../../shared/ui/icon-set';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { WorkspaceStore, type Conversation, type Project } from '../workspace.store';

@Component({
  selector: 'workspace-sidebar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [OverlayModule, RouterLink, TranslocoDirective, DonnaMark, UiIcon],
  templateUrl: './workspace-sidebar.html',
})
export class WorkspaceSidebar {
  readonly newChat = output<void>();
  readonly newProject = output<void>();

  protected readonly store = inject(WorkspaceStore);

  protected readonly flyout = createFlyout();

  // Le panneau se déploie vers le bas, aligné au bord droit du rail.
  protected readonly positions: ConnectedPosition[] = [
    { originX: 'end', originY: 'top', overlayX: 'start', overlayY: 'top', offsetX: 8 },
    { originX: 'end', originY: 'bottom', overlayX: 'start', overlayY: 'bottom', offsetX: 8 },
  ];

  protected readonly actions: readonly {
    icon: IconName;
    key: string;
    route: string;
    fragment?: string;
  }[] = [
    { icon: 'plug', key: 'workspace.nav.connectors', route: '/workspace/settings' },
    { icon: 'settings', key: 'workspace.nav.settings', route: '/workspace/settings' },
  ];

  protected startNewChat(): void {
    this.newChat.emit();
    this.flyout.hide();
  }

  protected startNewProject(): void {
    this.newProject.emit();
    this.flyout.hide();
  }

  protected openConversation(conversation: Conversation): void {
    this.store.openConversation(conversation.id);
    this.flyout.hide();
  }

  protected pick(project: Project): void {
    this.store.selectProject(project.id);
    this.flyout.hide();
  }
}
