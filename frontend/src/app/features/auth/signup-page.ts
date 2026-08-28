import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import { AuthService } from '../../core/auth/auth.service';
import { UiButton } from '../../shared/ui/ui-button';
import { UiField } from '../../shared/ui/ui-field';
import { UiIcon } from '../../shared/ui/ui-icon';
import { UiInput } from '../../shared/ui/ui-input';
import { AuthLayout } from './components/auth-layout';
import { OauthBlock } from './components/oauth-block';
import { PasswordField } from './components/password-field';

const MIN_PASSWORD_LENGTH = 8;

@Component({
  selector: 'signup-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    TranslocoDirective,
    AuthLayout,
    OauthBlock,
    PasswordField,
    UiButton,
    UiField,
    UiIcon,
    UiInput,
  ],
  templateUrl: './signup-page.html',
})
export class SignupPage {
  private readonly auth = inject(AuthService);

  protected readonly minPasswordLength = MIN_PASSWORD_LENGTH;
  protected readonly pending = this.auth.pending;
  protected readonly error = this.auth.error;

  protected readonly form = inject(FormBuilder).nonNullable.group({
    fullName: ['', [Validators.required]],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(MIN_PASSWORD_LENGTH)]],
    terms: [false, [Validators.requiredTrue]],
  });

  protected signUpWithGoogle(): void {
    void this.auth.signInWithGoogle();
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { fullName, email, password } = this.form.getRawValue();
    void this.auth.signUp({ fullName, email, password });
  }
}
