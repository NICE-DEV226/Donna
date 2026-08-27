import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * Avatar par monogramme. Pas de photo : afficher un visage d'inconnu à côté
 * d'un témoignage inventé serait trompeur. La teinte est dérivée du nom, donc
 * stable d'un rendu à l'autre, et puisée dans la palette DONNA.
 */
const TONES = [
  'bg-primary-soft text-primary',
  'bg-success-soft text-success',
  'bg-surface-raised text-ink-muted',
] as const;

@Component({
  selector: 'ui-avatar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'inline-flex shrink-0' },
  template: `
    <span
      class="inline-flex items-center justify-center rounded-full border border-line text-label-caps uppercase"
      [class]="tone()"
      [style.width.px]="size()"
      [style.height.px]="size()"
      [attr.aria-hidden]="true"
    >
      {{ initials() }}
    </span>
  `,
})
export class UiAvatar {
  readonly name = input.required<string>();
  readonly size = input(36);

  protected readonly initials = computed(() =>
    this.name()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join(''),
  );

  protected readonly tone = computed(() => {
    const name = this.name();
    // Hachage polynomial : une simple somme des points de code donne des
    // résultats trop proches pour des noms de longueur voisine — les quatre
    // témoignages tombaient tous sur la même teinte.
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) % 997;
    return TONES[hash % TONES.length];
  });
}
