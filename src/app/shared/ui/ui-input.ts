import { Directive, OnInit, computed, inject, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { AbstractControl, NgControl } from '@angular/forms';
import { EMPTY, switchMap } from 'rxjs';

const BASE =
  'w-full rounded-lg border bg-surface px-md py-sm text-body-md text-ink ' +
  'placeholder:text-ink-subtle transition-colors duration-200 ' +
  'disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-subtle';

// Le design system proscrit les contrastes violents au focus : on glisse vers le gris-brun.
const VALID = 'border-line focus:border-ink-subtle';
const INVALID = 'border-danger focus:border-danger';

@Directive({
  selector: 'input[uiInput], textarea[uiInput]',
  host: {
    '[class]': 'classes()',
    '[attr.aria-invalid]': 'invalid() ? "true" : null',
  },
})
export class UiInput implements OnInit {
  private readonly ngControl = inject(NgControl, { optional: true });
  private readonly control = signal<AbstractControl | null>(null);

  /** `events` couvre valeur, statut ET touched — indispensable en zoneless. */
  private readonly events = toSignal(
    toObservable(this.control).pipe(switchMap((control) => control?.events ?? EMPTY)),
    { initialValue: null },
  );

  protected readonly invalid = computed(() => {
    this.events();
    const control = this.control();
    return !!control && control.invalid && (control.touched || control.dirty);
  });

  protected readonly classes = computed(() => `${BASE} ${this.invalid() ? INVALID : VALID}`);

  ngOnInit(): void {
    // NgControl.control n'est câblé qu'après l'init de la directive de formulaire.
    this.control.set(this.ngControl?.control ?? null);
  }
}
