import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';

/**
 * La marque DONNA.
 *
 * Deux tracés : un fût, et un arc qui s'en approche sans le toucher.
 *
 * L'écart n'est pas décoratif, il dit le produit. Donna anticipe — l'arc est
 * déjà en place — mais elle ne referme rien sans vous : c'est exactement la
 * règle « elle rédige, vous validez ». Quand l'action est approuvée, deux
 * traits de liaison se tracent et le D se ferme.
 *
 * `closed` force l'état fermé ; sinon un ancêtre portant `.donna-lockup`
 * referme la marque au survol.
 */
@Component({
  selector: 'donna-mark',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'donna-mark inline-flex shrink-0',
    '[class.donna-mark--closed]': 'closed()',
  },
  template: `
    <svg
      viewBox="0 0 32 32"
      [attr.width]="size()"
      [attr.height]="size()"
      [attr.role]="label() ? 'img' : null"
      [attr.aria-label]="label() || null"
      [attr.aria-hidden]="label() ? null : true"
    >
      @if (boxed()) {
        <rect width="32" height="32" rx="7.5" fill="currentColor" />
      }

      <g
        [attr.stroke]="boxed() ? 'var(--color-surface)' : 'currentColor'"
        stroke-width="3.4"
        stroke-linecap="round"
        fill="none"
        [attr.transform]="boxed() ? 'translate(2.4 1.4) scale(0.86)' : null"
      >
        <!-- Le fût : le seuil, son bureau devant la porte. -->
        <path d="M10 5.5V26.5" />
        <!-- L'arc : déjà là, en attente. -->
        <path d="M15.8 5.5C24 5.5 27.5 10 27.5 16C27.5 22 24 26.5 15.8 26.5" />
        <!-- Les liaisons : elles ne se tracent qu'une fois validé. -->
        <path class="donna-mark__link" d="M10 5.5H15.8" />
        <path class="donna-mark__link" d="M10 26.5H15.8" />
      </g>
    </svg>
  `,
})
export class DonnaMark {
  readonly size = input(28);
  /** Version en réserve dans une pastille pleine : pour l'onglet et l'icône d'app. */
  readonly boxed = input(false, { transform: booleanAttribute });
  /** État validé : le D est refermé. */
  readonly closed = input(false, { transform: booleanAttribute });
  /** Renseigné, le SVG devient une image nommée ; sinon il est décoratif. */
  readonly label = input('');
}
