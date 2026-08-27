import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoDirective } from '@jsverse/transloco';
import { GoogleMark } from '../../../shared/ui/google-mark';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiReveal } from '../../../shared/ui/ui-reveal';

@Component({
  selector: 'hero-section',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslocoDirective, GoogleMark, UiButton, UiReveal],
  templateUrl: './hero-section.html',
})
export class HeroSection {}
