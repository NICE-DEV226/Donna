import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiAvatar } from '../../shared/ui/ui-avatar';
import { UiButton } from '../../shared/ui/ui-button';
import { UiField } from '../../shared/ui/ui-field';
import { UiInput } from '../../shared/ui/ui-input';
import { WorkspaceStore } from './workspace.store';

@Component({
  selector: 'profile-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block h-full overflow-y-auto' },
  imports: [ReactiveFormsModule, TranslocoDirective, UiAvatar, UiButton, UiField, UiInput],
  templateUrl: './profile-page.html',
})
export class ProfilePage {
  protected readonly store = inject(WorkspaceStore);

  protected readonly form = inject(FormBuilder).nonNullable.group({
    name: [this.store.profile().name, [Validators.required]],
    email: [this.store.profile().email, [Validators.required, Validators.email]],
    role: [this.store.profile().role],
  });

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.store.updateProfile(this.form.getRawValue());
  }
}
