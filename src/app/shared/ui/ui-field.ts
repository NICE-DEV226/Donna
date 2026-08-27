import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { AbstractControl } from '@angular/forms';
import { switchMap } from 'rxjs';

const DEFAULT_MESSAGES: Record<string, string> = {
  required: 'This field is required.',
  email: 'Enter a valid email address.',
  minlength: 'This value is too short.',
  requiredTrue: 'You need to accept this to continue.',
};

/** Habillage d'un champ : libellé, aide, message d'erreur relié par aria-describedby. */
@Component({
  selector: 'ui-field',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block' },
  template: `
    <label [for]="controlId()" class="mb-xs block text-body-sm font-medium text-ink">
      {{ label() }}
    </label>

    <ng-content />

    @if (errorMessage(); as message) {
      <p [id]="describedBy()" role="alert" class="mt-xs text-body-sm text-danger">{{ message }}</p>
    } @else if (hint()) {
      <p [id]="describedBy()" class="mt-xs text-body-sm text-ink-muted">{{ hint() }}</p>
    }
  `,
})
export class UiField {
  readonly label = input.required<string>();
  readonly controlId = input.required<string>();
  readonly control = input.required<AbstractControl>();
  readonly hint = input('');
  /** Surcharge des libellés d'erreur, par clé de validateur. */
  readonly messages = input<Record<string, string>>({});

  private readonly events = toSignal(
    toObservable(this.control).pipe(switchMap((control) => control.events)),
    { initialValue: null },
  );

  protected readonly describedBy = computed(() => `${this.controlId()}-description`);

  protected readonly errorMessage = computed(() => {
    this.events();
    const control = this.control();

    // On n'accuse pas l'utilisateur d'une erreur sur un champ qu'il n'a pas encore touché.
    if (!control.invalid || !(control.touched || control.dirty)) return null;

    const [key] = Object.keys(control.errors ?? {});
    if (!key) return null;

    return this.messages()[key] ?? DEFAULT_MESSAGES[key] ?? 'Invalid value.';
  });
}
