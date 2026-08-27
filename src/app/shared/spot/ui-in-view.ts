import { Directive } from '@angular/core';
import { observeFirstEntry } from '../ui/in-view';

/**
 * Pose la classe `in-view` à la première apparition à l'écran, sans rien
 * animer elle-même : ce sont les illustrations qui décident quoi jouer.
 * Appliquée en `hostDirectives` par chaque composant d'illustration.
 */
@Directive({
  selector: '[uiInView]',
  host: { class: 'spot', '[class.in-view]': 'entered()' },
})
export class UiInView {
  protected readonly entered = observeFirstEntry(0.35);
}
