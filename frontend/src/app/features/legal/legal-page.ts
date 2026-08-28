import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { SiteFooter } from '../../shared/layout/site-footer';
import { SiteHeader } from '../../shared/layout/site-header';
import { UiIcon } from '../../shared/ui/ui-icon';

export type LegalDoc = 'terms' | 'privacy';

const SECTIONS: Record<LegalDoc, readonly string[]> = {
  terms: ['scope', 'consent', 'audit', 'accuracy'],
  privacy: ['training', 'storage', 'separation', 'deletion'],
};

/**
 * Conditions d'utilisation et politique de confidentialité.
 *
 * Le texte contractuel n'est pas rédigé, et on ne l'invente pas : la page le
 * dit en toutes lettres. Elle énonce en revanche les engagements que le produit
 * affiche déjà publiquement. Mieux vaut cela qu'un lien mort à l'instant précis
 * où l'on demande à quelqu'un de cocher une case pour s'engager.
 */
@Component({
  selector: 'legal-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, SiteHeader, SiteFooter, UiIcon],
  templateUrl: './legal-page.html',
})
export class LegalPage {
  /** Fourni par `data` sur la route, via withComponentInputBinding(). */
  readonly doc = input.required<LegalDoc>();

  protected readonly base = computed(() => `legal.${this.doc()}`);
  protected readonly sections = computed(() => SECTIONS[this.doc()]);
}
