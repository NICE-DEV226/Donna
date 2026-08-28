import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import { AuthService } from '../../core/auth/auth.service';
import { UiButton } from '../../shared/ui/ui-button';
import { UiField } from '../../shared/ui/ui-field';
import { UiIcon } from '../../shared/ui/ui-icon';
import { UiInput } from '../../shared/ui/ui-input';
import { AuthLayout } from './components/auth-layout';

@Component({
  selector: 'reset-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    TranslocoDirective,
    AuthLayout,
    UiButton,
    UiField,
    UiIcon,
    UiInput,
  ],
  templateUrl: './reset-page.html',
})
export class ResetPage {
  private readonly auth = inject(AuthService);

  protected readonly pending = this.auth.pending;
  /** Adresse soumise : sert au message de confirmation, jamais à confirmer l'existence du compte. */
  protected readonly sentTo = signal<string | null>(null);

  protected readonly form = inject(FormBuilder).nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
  });

  protected async submit(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { email } = this.form.getRawValue();
    await this.auth.requestReset(email);
    this.sentTo.set(email);
  }

  protected resend(): void {
    this.sentTo.set(null);
  }
}
