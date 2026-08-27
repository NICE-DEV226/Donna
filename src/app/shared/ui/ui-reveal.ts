import { Directive, input } from '@angular/core';
import { observeFirstEntry } from './in-view';

/**
 * Révèle l'élément quand il entre dans le viewport.
 * L'animation elle-même est en CSS (styles.scss) et se désactive
 * automatiquement si l'utilisateur a demandé moins de mouvement.
 */
@Directive({
  selector: '[uiReveal]',
  host: {
    class: 'ui-reveal',
    '[class.ui-reveal--visible]': 'visible()',
    '[style.transition-delay.ms]': 'delay()',
  },
})
export class UiReveal {
  /** Décalage en ms, pour échelonner une grille de cartes. */
  readonly delay = input<number, number | ''>(0, {
    alias: 'uiReveal',
    // L'attribut nu `uiReveal` transmet une chaîne vide : on la ramène à zéro.
    transform: (value) => (value === '' ? 0 : value),
  });

  protected readonly visible = observeFirstEntry();
}
