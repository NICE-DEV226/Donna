import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { LanguageSwitch } from '../../shared/layout/language-switch';
import type { IconName } from '../../shared/ui/icon-set';
import { UiButton } from '../../shared/ui/ui-button';
import { UiIcon } from '../../shared/ui/ui-icon';
import { WorkspaceStore } from './workspace.store';

@Component({
  selector: 'settings-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block h-full overflow-y-auto' },
  imports: [TranslocoDirective, LanguageSwitch, UiButton, UiIcon],
  templateUrl: './settings-page.html',
})
export class SettingsPage {
  protected readonly store = inject(WorkspaceStore);

  protected icon(name: string): IconName {
    return name as IconName;
  }
}
