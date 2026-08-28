import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import { DonnaMark } from '../brand/donna-mark';

interface FooterLink {
  readonly key: string;
  /** Ancre dans la page. */
  readonly fragment?: string;
  /** Route de l'application. */
  readonly route?: string;
  /** Lien externe véritable (mailto…). */
  readonly href?: string;
}

@Component({
  selector: 'site-footer',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslocoDirective, DonnaMark],
  templateUrl: './site-footer.html',
})
export class SiteFooter {
  protected readonly year = new Date().getFullYear();

  /**
   * Chaque entrée mène à quelque chose de réel : une section de la page, une
   * route de l'application, ou une adresse. Les colonnes « Entreprise » et
   * « Légal » ont sauté — elles pointaient vers des pages qui n'existent pas.
   */
  protected readonly columns: readonly { heading: string; links: readonly FooterLink[] }[] = [
    {
      heading: 'footer.product',
      links: [
        { key: 'footer.links.how', fragment: 'how' },
        { key: 'footer.links.features', fragment: 'features' },
        { key: 'footer.links.security', fragment: 'security' },
        { key: 'footer.links.faq', fragment: 'faq' },
      ],
    },
    {
      heading: 'footer.company',
      links: [
        { key: 'footer.signIn', route: '/login' },
        { key: 'footer.getStarted', route: '/signup' },
        { key: 'footer.contact', href: 'mailto:hello@donna.ai' },
      ],
    },
    {
      heading: 'footer.legal',
      links: [
        { key: 'footer.links.terms', route: '/terms' },
        { key: 'footer.links.privacy', route: '/privacy' },
      ],
    },
  ];
}
