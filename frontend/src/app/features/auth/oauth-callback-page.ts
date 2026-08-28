import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import { AuthService } from '../../core/auth/auth.service';
import { UiIcon } from '../../shared/ui/ui-icon';

/**
 * Atterrissage du callback OAuth backend (xauth redirige ici avec des query
 * params — voir routes/oauth.py::callback, le contrat exact des paramètres).
 * Pur relais, aucune UI d'attente longue : le backend a déjà fait le travail,
 * on ne fait que lire le résultat et router vers la bonne suite.
 */
@Component({
  selector: 'oauth-callback-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiIcon],
  template: `
    <div class="flex min-h-screen flex-col items-center justify-center gap-md">
      <ui-icon name="loader-circle" [size]="32" class="animate-spin text-ink-muted" />
      <p *transloco="let t" class="text-body-md text-ink-muted">{{ t('auth.oauth.completing') }}</p>
    </div>
  `,
})
export class OauthCallbackPage implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);

  ngOnInit(): void {
    const params = this.route.snapshot.queryParamMap;
    const accessToken = params.get('access_token');
    const refreshToken = params.get('refresh_token');
    const onboarding = params.get('onboarding') === 'true';
    const tenantsEncoded = params.get('tenants');
    const oauthError = params.get('error');

    if (oauthError || !refreshToken) {
      void this.router.navigate(['/login'], { queryParams: { error: 'auth.errors.generic' } });
      return;
    }

    if (accessToken) {
      void this.auth.completeDirectSession(accessToken, refreshToken);
      return;
    }

    if (onboarding) {
      void this.auth.completeOAuthOnboarding(refreshToken);
      return;
    }

    if (tenantsEncoded) {
      const tenants = this.decodeTenants(tenantsEncoded);
      const first = tenants[0]?.id;
      if (first) {
        void this.auth.completeOAuthTenantSelection(refreshToken, first);
        return;
      }
    }

    void this.auth.completeOAuthOnboarding(refreshToken);
  }

  private decodeTenants(encoded: string): { id: string }[] {
    try {
      return JSON.parse(atob(encoded));
    } catch {
      return [];
    }
  }
}
