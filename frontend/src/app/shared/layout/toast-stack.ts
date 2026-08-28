import { ChangeDetectionStrategy, Component, booleanAttribute, inject, input } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { Toasts } from '../../core/notifications/toasts';
import { DonnaMark } from '../brand/donna-mark';
import { UiIcon } from '../ui/ui-icon';

/**
 * Notifications empilées en bas à droite.
 *
 * En haut à droite, sous la barre : en bas, la pile recouvrait le champ de
 * saisie — une notification qui gêne l'écriture est une notification ratée.
 *
 * `pointer-events-none` sur la pile, réactivé sur chaque carte : la zone vide
 * ne capture pas les clics, donc rien de ce qui est dessous n'est bloqué.
 */
@Component({
  selector: 'toast-stack',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, DonnaMark, UiIcon],
  template: `
    <div
      *transloco="let t"
      class="toast-stack pointer-events-none fixed top-20 z-50 flex flex-col items-end gap-sm"
      [class.toast-stack--shifted]="shifted()"
      aria-live="off"
    >
      @for (toast of toasts.items(); track toast.id) {
        <article
          class="toast-in pointer-events-auto flex max-w-toast items-center gap-md rounded-xl border border-line bg-surface py-sm pr-sm pl-md shadow-floating"
        >
          <!-- La marque refermée : DONNA a tranché et retenu. -->
          <span
            class="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary"
            aria-hidden="true"
          >
            <donna-mark [size]="15" closed />
          </span>

          <div class="min-w-0">
            <p class="text-body-sm font-semibold text-ink">{{ t(toast.titleKey, toast.titleParams) }}</p>
            @if (toast.bodyText) {
              <p class="truncate text-body-sm text-ink-muted">{{ toast.bodyText }}</p>
            } @else if (toast.bodyKey) {
              <p class="truncate text-body-sm text-ink-muted">{{ t(toast.bodyKey) }}</p>
            }
          </div>

          @if (toast.url && toast.linkLabelKey) {
            <a
              [href]="toast.url"
              target="_blank"
              rel="noopener noreferrer"
              class="shrink-0 text-body-sm font-semibold text-primary hover:underline"
            >
              {{ t(toast.linkLabelKey) }}
            </a>
          }

          <button
            type="button"
            class="flex size-7 shrink-0 items-center justify-center rounded-lg text-ink-subtle transition-colors hover:bg-surface-sunken hover:text-ink"
            [attr.aria-label]="t('workspace.memory.dismiss')"
            (click)="toasts.dismiss(toast.id)"
          >
            <ui-icon name="x" [size]="16" />
          </button>
        </article>
      }
    </div>
  `,
})
export class ToastStack {
  /**
   * Décale la pile quand un panneau occupe le bord droit : deux éléments
   * empilés au même endroit, c'est l'un des deux qu'on ne lit plus.
   */
  readonly shifted = input(false, { transform: booleanAttribute });

  protected readonly toasts = inject(Toasts);
}
