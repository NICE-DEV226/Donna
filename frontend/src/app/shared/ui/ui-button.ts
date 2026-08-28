import { Directive, booleanAttribute, computed, input } from '@angular/core';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'success';
export type ButtonSize = 'sm' | 'md';

// La bordure transparente est structurelle : sans elle, le bouton primaire est
// 2px plus court que le secondaire bordé, et l'alignement casse dès qu'ils voisinent.
// La bordure est déclarée ici SANS couleur : chaque variante pose la sienne.
// Mettre `border-transparent` dans la base plaçait deux utilitaires de
// border-color sur le même élément, et Tailwind tranchait selon SON ordre de
// génération — pas selon l'ordre des classes. Résultat : le bouton secondaire
// perdait son filet et flottait sans contour.
//
// RÈGLE : tout ce que la directive pose ici est INCONTESTABLE depuis un template.
// Deux utilitaires Tailwind sur la même propriété se départagent selon l'ordre de
// génération du CSS, pas selon l'ordre des classes — une classe « correctrice »
// écrite dans le template est ignorée sans le moindre avertissement.
// Toute variation passe donc par une entrée de la directive (`variant`, `size`,
// `wrap`), jamais par une classe concurrente. `npm run lint:classes` l'impose.
const BASE =
  'inline-flex items-center justify-center gap-sm rounded-lg border ' +
  'font-semibold text-center transition-colors duration-200 ' +
  'disabled:opacity-50 disabled:pointer-events-none';

const SIZES: Record<ButtonSize, string> = {
  sm: 'px-md py-sm text-body-sm',
  md: 'px-lg py-md text-body-md',
};

// Le burgundy reste réservé aux actions critiques — cf. design system « Safe ».
const VARIANTS: Record<ButtonVariant, string> = {
  // Une seule couleur de bordure par variante : aucun conflit possible.
  primary: 'border-primary bg-primary text-on-primary hover:border-primary-strong hover:bg-primary-strong',
  // « Transparent background with a 1px #E5E5E5 border and charcoal text » — au mot près.
  secondary: 'border-line bg-transparent text-ink hover:border-primary/40',
  ghost: 'border-transparent bg-transparent text-ink-muted hover:text-primary',
  success: 'border-success-soft bg-success-soft/30 text-success hover:bg-success-soft/60',
};

@Directive({
  // `span[uiButton]` sert aux MAQUETTES : sur la landing, ces éléments montrent
  // le produit sans rien déclencher. Un <button> inerte serait focusable au
  // clavier et annoncé comme actionnable — une promesse que rien ne tient.
  selector: 'button[uiButton], a[uiButton], span[uiButton]',
  host: { '[class]': 'classes()' },
})
export class UiButton {
  readonly variant = input<ButtonVariant, ButtonVariant | ''>('primary', {
    alias: 'uiButton',
    transform: (value) => value || 'primary',
  });
  readonly size = input<ButtonSize>('md');

  /**
   * Autorise le libellé à passer à la ligne. Par défaut un bouton ne se coupe
   * pas : dans une barre de navigation, cela en casserait la hauteur. À activer
   * sur les boutons `w-full` à long libellé.
   */
  readonly wrap = input(false, { transform: booleanAttribute });

  protected readonly classes = computed(
    () =>
      `${BASE} ${this.wrap() ? 'whitespace-normal' : 'whitespace-nowrap'} ` +
      `${SIZES[this.size()]} ${VARIANTS[this.variant()]}`,
  );
}
