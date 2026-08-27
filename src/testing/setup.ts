import { TranslocoTestingModule, type TranslocoTestingOptions } from '@jsverse/transloco';
import en from '../../public/i18n/en.json';
import fr from '../../public/i18n/fr.json';

/**
 * Les traductions réelles sont injectées dans les tests : si une clé disparaît
 * d'un fichier de langue, le test qui l'affiche casse.
 */
export function provideTestTranslations(options: TranslocoTestingOptions = {}) {
  return TranslocoTestingModule.forRoot({
    langs: { en, fr },
    translocoConfig: {
      availableLangs: ['en', 'fr'],
      defaultLang: 'en',
      reRenderOnLangChange: true,
    },
    preloadLangs: true,
    ...options,
  });
}

/** jsdom n'implémente pas IntersectionObserver, dont dépend la directive UiReveal. */
export class IntersectionObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

export function stubIntersectionObserver(): void {
  globalThis.IntersectionObserver = IntersectionObserverStub as never;
}

export const EN = en;
export const FR = fr;
