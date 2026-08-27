import { DestroyRef, ElementRef, afterNextRender, inject, signal } from '@angular/core';

/**
 * Signale la première entrée de l'élément hôte dans le viewport.
 * Mutualisé entre UiReveal (apparition des blocs) et UiInView (déclenchement
 * des illustrations) : une seule implémentation d'IntersectionObserver.
 */
export function observeFirstEntry(threshold = 0.1) {
  const element = inject(ElementRef<HTMLElement>).nativeElement;
  const destroyRef = inject(DestroyRef);
  const entered = signal(false);

  afterNextRender(() => {
    // Pas d'IntersectionObserver (jsdom, très vieux navigateur) : on montre tout.
    if (typeof IntersectionObserver === 'undefined') {
      entered.set(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          entered.set(true);
          observer.disconnect();
        }
      },
      { threshold },
    );

    observer.observe(element);
    destroyRef.onDestroy(() => observer.disconnect());
  });

  return entered.asReadonly();
}
