import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Language, type LanguageCode } from '../../core/i18n/language';

/** Contrôle segmenté EN / FR. Deux langues : un menu déroulant serait de trop. */
@Component({
  selector: 'language-switch',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="inline-flex items-center rounded-full border border-line p-[2px]"
      role="group"
      aria-label="Language"
    >
      @for (lang of language.available; track lang.code) {
        <button
          type="button"
          class="rounded-full px-sm py-xs text-label-caps transition-colors duration-200"
          [class.bg-primary]="language.current() === lang.code"
          [class.text-on-primary]="language.current() === lang.code"
          [class.text-ink-muted]="language.current() !== lang.code"
          [class.hover:text-ink]="language.current() !== lang.code"
          [attr.aria-pressed]="language.current() === lang.code"
          [attr.aria-label]="lang.name"
          (click)="select(lang.code)"
        >
          {{ lang.label }}
        </button>
      }
    </div>
  `,
})
export class LanguageSwitch {
  protected readonly language = inject(Language);

  protected select(code: LanguageCode): void {
    this.language.set(code);
  }
}
