import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import { AuthService } from '../../../core/auth/auth.service';
import { LanguageSwitch } from '../../../shared/layout/language-switch';
import { Toasts } from '../../../core/notifications/toasts';
import { createFlyout } from '../../../shared/ui/flyout';
import { UiAvatar } from '../../../shared/ui/ui-avatar';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { ConnectionsPanel } from './connections-panel';
import { WorkspaceStore } from '../workspace.store';

@Component({
  selector: 'workspace-topbar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    OverlayModule,
    RouterLink,
    TranslocoDirective,
    ConnectionsPanel,
    LanguageSwitch,
    UiAvatar,
    UiButton,
    UiIcon,
  ],
  templateUrl: './workspace-topbar.html',
})
export class WorkspaceTopbar {
  protected readonly store = inject(WorkspaceStore);
  protected readonly toasts = inject(Toasts);
  protected readonly flyout = createFlyout();
  protected readonly bell = createFlyout();

  // La cloche ouvre sous elle, alignée à droite.
  protected readonly bellPositions: ConnectedPosition[] = [
    { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 8 },
  ];
  protected readonly account = createFlyout();

  private readonly auth = inject(AuthService);

  // Le panneau tombe sous le bouton, aligné à droite pour ne pas sortir de l'écran.
  protected readonly positions: ConnectedPosition[] = [
    { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 8 },
    { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -8 },
  ];

  protected signOut(): void {
    this.account.hide();
    void this.auth.signOut();
  }
}
