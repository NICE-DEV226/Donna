import { DestroyRef, inject, signal } from '@angular/core';

/** Délai avant fermeture : laisse le temps d'atteindre le panneau. */
const CLOSE_DELAY = 160;

/**
 * Comportement d'un panneau qui s'ouvre au survol d'un déclencheur.
 *
 * Le survol seul ne suffit pas : au clavier et au tactile il n'existe pas.
 * D'où l'épinglage au clic et la fermeture par Échap, systématiquement.
 */
export class FlyoutController {
  readonly open = signal(false);
  readonly pinned = signal(false);

  private timer?: ReturnType<typeof setTimeout>;

  constructor(destroyRef: DestroyRef) {
    destroyRef.onDestroy(() => clearTimeout(this.timer));
  }

  show = (): void => {
    clearTimeout(this.timer);
    this.open.set(true);
  };

  scheduleHide = (): void => {
    if (this.pinned()) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.open.set(false), CLOSE_DELAY);
  };

  togglePinned = (): void => {
    const next = !this.pinned();
    this.pinned.set(next);
    this.open.set(next || this.open());
  };

  hide = (): void => {
    clearTimeout(this.timer);
    this.pinned.set(false);
    this.open.set(false);
  };

  onKeydown = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') this.hide();
  };
}

/** À appeler dans un contexte d'injection (initialiseur de champ d'un composant). */
export function createFlyout(): FlyoutController {
  return new FlyoutController(inject(DestroyRef));
}
