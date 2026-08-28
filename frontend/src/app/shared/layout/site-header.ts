import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import { DonnaMark } from '../brand/donna-mark';
import { UiButton } from '../ui/ui-button';
import { LanguageSwitch } from './language-switch';

@Component({
  selector: 'site-header',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslocoDirective, DonnaMark, UiButton, LanguageSwitch],
  templateUrl: './site-header.html',
})
export class SiteHeader {
  // Chaque entrée pointe vers une section qui existe réellement dans la page.
  protected readonly navLinks = [
    { key: 'nav.how', fragment: 'how' },
    { key: 'nav.features', fragment: 'features' },
    { key: 'footer.links.security', fragment: 'security' },
    { key: 'nav.voices', fragment: 'voices' },
    { key: 'nav.faq', fragment: 'faq' },
  ] as const;
}
