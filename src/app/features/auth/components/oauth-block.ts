import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { GoogleMark } from '../../../shared/ui/google-mark';
import { UiButton } from '../../../shared/ui/ui-button';

/** Entrée principale : Google reste le seul bouton burgundy de l'écran. */
@Component({
  selector: 'oauth-block',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, GoogleMark, UiButton],
  template: `
    <ng-container *transloco="let t">
      <button type="button" uiButton class="w-full" (click)="authenticate.emit()">
        <google-mark />
        {{ t(labelKey()) }}
      </button>

      <div class="my-lg flex items-center gap-md" aria-hidden="true">
        <span class="h-px grow bg-line"></span>
        <span class="text-label-caps uppercase text-ink-subtle">{{ t('auth.or') }}</span>
        <span class="h-px grow bg-line"></span>
      </div>
    </ng-container>
  `,
})
export class OauthBlock {
  readonly labelKey = input('auth.login.google');
  readonly authenticate = output<void>();
}
