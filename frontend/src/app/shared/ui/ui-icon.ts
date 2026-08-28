import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { ICON_SET, type IconName } from './icon-set';

/**
 * Icône line-art issue de lucide-static.
 * Le design system impose 20–24px et un stroke de 1.5px — d'où les valeurs par défaut.
 */
@Component({
  selector: 'ui-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'inline-flex shrink-0', '[attr.aria-hidden]': 'true' },
  template: `
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-linecap="round"
      stroke-linejoin="round"
      [attr.width]="size()"
      [attr.height]="size()"
      [attr.stroke-width]="strokeWidth()"
      [innerHTML]="body()"
    ></svg>
  `,
})
export class UiIcon {
  private readonly sanitizer = inject(DomSanitizer);

  readonly name = input.required<IconName>();
  readonly size = input(20);
  readonly strokeWidth = input(1.5);

  // ICON_SET est une constante compilée dans le bundle : aucune entrée utilisateur ici.
  protected readonly body = computed(() =>
    this.sanitizer.bypassSecurityTrustHtml(ICON_SET[this.name()]),
  );
}
