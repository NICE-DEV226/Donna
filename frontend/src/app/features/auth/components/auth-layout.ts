import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import type { IconName } from '../../../shared/ui/icon-set';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { LanguageSwitch } from '../../../shared/layout/language-switch';
import { ConversationPreview } from '../../landing/components/conversation-preview';

/**
 * Gabarit commun aux écrans d'authentification : formulaire à gauche,
 * panneau éditorial à droite qui rappelle le produit et rassure.
 */
@Component({
  selector: 'auth-layout',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslocoDirective, UiIcon, LanguageSwitch, ConversationPreview],
  templateUrl: './auth-layout.html',
})
export class AuthLayout {
  protected readonly year = new Date().getFullYear();

  protected readonly trustPoints: readonly { icon: IconName; key: string }[] = [
    { icon: 'shield-check', key: 'auth.aside.oauth' },
    { icon: 'lock', key: 'auth.aside.encrypted' },
    { icon: 'circle-check', key: 'auth.aside.audit' },
  ];
}
