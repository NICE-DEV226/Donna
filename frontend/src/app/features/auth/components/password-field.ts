import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiField } from '../../../shared/ui/ui-field';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { UiInput } from '../../../shared/ui/ui-input';

@Component({
  selector: 'password-field',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, TranslocoDirective, UiField, UiIcon, UiInput],
  template: `
    <ui-field *transloco="let t"
      [label]="t('auth.fields.password')"
      [controlId]="controlId()"
      [control]="control()"
      [hint]="hint()"
      [messages]="messages()"
    >
      <div class="relative">
        <input
          uiInput
          [id]="controlId()"
          [type]="revealed() ? 'text' : 'password'"
          [formControl]="control()"
          [autocomplete]="autocomplete()"
          [attr.aria-describedby]="controlId() + '-description'"
          class="pr-xxl"
        />
        <button
          type="button"
          class="absolute inset-y-0 right-0 flex items-center rounded-r-lg px-md text-ink-muted transition-colors hover:text-ink"
          [attr.aria-label]="revealed() ? t('auth.fields.hidePassword') : t('auth.fields.showPassword')"
          [attr.aria-pressed]="revealed()"
          (click)="toggle()"
        >
          <ui-icon [name]="revealed() ? 'eye-off' : 'eye'" [size]="18" />
        </button>
      </div>
    </ui-field>
  `,
})
export class PasswordField {
  readonly control = input.required<FormControl<string>>();
  readonly controlId = input('password');
  readonly autocomplete = input<'current-password' | 'new-password'>('current-password');
  readonly hint = input('');
  readonly messages = input<Record<string, string>>({});

  protected readonly revealed = signal(false);

  protected toggle(): void {
    this.revealed.update((value) => !value);
  }
}
