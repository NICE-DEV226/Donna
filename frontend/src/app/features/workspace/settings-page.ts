import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import type { LinkedAccount } from '../../core/auth/auth.service';
import { AuthService } from '../../core/auth/auth.service';
import { Toasts } from '../../core/notifications/toasts';
import { LanguageSwitch } from '../../shared/layout/language-switch';
import type { IconName } from '../../shared/ui/icon-set';
import { UiButton } from '../../shared/ui/ui-button';
import { UiIcon } from '../../shared/ui/ui-icon';
import { WorkspaceStore } from './workspace.store';

@Component({
  selector: 'settings-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block h-full overflow-y-auto' },
  imports: [TranslocoDirective, LanguageSwitch, UiButton, UiIcon],
  templateUrl: './settings-page.html',
})
export class SettingsPage implements OnInit {
  protected readonly store = inject(WorkspaceStore);
  private readonly auth = inject(AuthService);
  private readonly toasts = inject(Toasts);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  /** null pendant le chargement initial — distingue « pas encore su » de « aucun compte lié ». */
  protected readonly linkedAccounts = signal<readonly LinkedAccount[] | null>(null);
  protected readonly linkingGoogle = signal(false);

  ngOnInit(): void {
    void this.loadLinkedAccounts();
    this.handleOAuthRedirect();
  }

  protected icon(name: string): IconName {
    return name as IconName;
  }

  protected isGoogleLinked(): boolean {
    return (this.linkedAccounts() ?? []).some((a) => a.provider === 'google');
  }

  protected googleAccount(): LinkedAccount | undefined {
    return (this.linkedAccounts() ?? []).find((a) => a.provider === 'google');
  }

  protected async linkGoogle(): Promise<void> {
    this.linkingGoogle.set(true);
    try {
      // Quitte la page — le retour se fait via handleOAuthRedirect ci-dessus,
      // après le round-trip complet vers Google (voir auth.service.ts).
      await this.auth.startLinkGoogle();
    } catch {
      this.linkingGoogle.set(false);
      this.toasts.push({ titleKey: 'workspace.settings.account.linkFailed' }, 'Link failed');
    }
  }

  protected async unlinkGoogle(): Promise<void> {
    try {
      await this.auth.unlinkAccount('google');
      this.toasts.push({ titleKey: 'workspace.settings.account.unlinked' }, 'Account unlinked');
      await this.loadLinkedAccounts();
    } catch {
      this.toasts.push({ titleKey: 'workspace.settings.account.linkFailed' }, 'Unlink failed');
    }
  }

  private async loadLinkedAccounts(): Promise<void> {
    try {
      this.linkedAccounts.set(await this.auth.listLinkedAccounts());
    } catch {
      // Liste vide plutôt qu'un écran cassé — la section reste utilisable
      // (l'utilisateur peut réessayer de lier, ça échouera proprement sinon).
      this.linkedAccounts.set([]);
    }
  }

  /**
   * Atterrissage après le round-trip OAuth de liaison (voir
   * oauth.py::callback, branche `linked`/`link_error` — la connexion,
   * elle, atterrit sur OauthCallbackPage, jamais ici).
   */
  private handleOAuthRedirect(): void {
    const params = this.route.snapshot.queryParamMap;
    const linked = params.get('linked');
    const linkError = params.get('link_error');
    if (!linked && !linkError) return;

    if (linked) {
      this.toasts.push({ titleKey: 'workspace.settings.account.linked' }, 'Account linked');
      void this.loadLinkedAccounts();
    } else {
      this.toasts.push({ titleKey: 'workspace.settings.account.linkFailed' }, 'Link failed');
    }
    // Nettoie l'URL — un F5 ne doit pas rejouer le toast indéfiniment.
    void this.router.navigate([], { relativeTo: this.route, queryParams: {} });
  }
}
