import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import { GoogleMark } from '../../../shared/ui/google-mark';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiReveal } from '../../../shared/ui/ui-reveal';

@Component({
  selector: 'cta-band',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslocoDirective, GoogleMark, UiButton, UiReveal],
  template: `
    <section *transloco="let t" class="px-lg py-xxl">
      <!-- Rose soutenu de la palette : le seul aplat coloré de la page. -->
      <div
        uiReveal
        class="mx-auto max-w-page rounded-xl bg-primary-soft px-lg py-xxl text-center"
      >
        <h2 class="text-mobile-headline text-ink sm:text-display">{{ t('cta.title') }}</h2>
        <p class="mx-auto mt-md max-w-measure text-body-lg text-ink-muted">{{ t('cta.body') }}</p>
        <a routerLink="/signup" uiButton class="mt-xl">
          <google-mark />
          {{ t('cta.button') }}
        </a>
      </div>
    </section>
  `,
})
export class CtaBand {}
