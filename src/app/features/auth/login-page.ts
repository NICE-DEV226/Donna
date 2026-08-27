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

@Component({
  selector: 'login-page',
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
  templateUrl: './login-page.html',
})
export class LoginPage {
  private readonly auth = inject(AuthService);

  protected readonly pending = this.auth.pending;

  protected readonly form = inject(FormBuilder).nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  protected signInWithGoogle(): void {
    void this.auth.signInWithGoogle();
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    void this.auth.signIn(this.form.getRawValue());
  }
}
