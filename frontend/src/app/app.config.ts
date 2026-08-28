import { ApplicationConfig, isDevMode, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import {
  provideRouter,
  withComponentInputBinding,
  withInMemoryScrolling,
} from '@angular/router';
import { provideTransloco } from '@jsverse/transloco';
import { authInterceptor } from './core/auth/auth.interceptor';
import { DEFAULT_LANGUAGE, LANGUAGES } from './core/i18n/language';
import { TranslocoHttpLoader } from './core/i18n/transloco-loader';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideHttpClient(withFetch(), withInterceptors([authInterceptor])),
    provideRouter(
      routes,
      // Les liens de la nav sont des ancres : il faut que le routeur les honore.
      withInMemoryScrolling({ anchorScrolling: 'enabled', scrollPositionRestoration: 'enabled' }),
      // `data` de la route alimente directement les entrées du composant.
      withComponentInputBinding(),
    ),
    provideTransloco({
      config: {
        availableLangs: LANGUAGES.map((l) => l.code),
        defaultLang: DEFAULT_LANGUAGE,
        fallbackLang: DEFAULT_LANGUAGE,
        reRenderOnLangChange: true,
        prodMode: !isDevMode(),
        missingHandler: { logMissingKey: isDevMode() },
      },
      loader: TranslocoHttpLoader,
    }),
  ],
};
