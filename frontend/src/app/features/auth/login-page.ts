import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
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
  protected readonly error = this.auth.error;

  protected readonly form = inject(FormBuilder).nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  constructor() {
    // Retour d'un callback OAuth en échec (voir oauth-callback-page) : le
    // message générique arrive ici en query param plutôt que par le store
    // normal, puisqu'aucune session AuthService n'existe encore à ce stade.
    const failure = inject(ActivatedRoute).snapshot.queryParamMap.get('error');
    if (failure) this.auth.error.set(failure);
  }

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
