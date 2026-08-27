import { ChangeDetectionStrategy, Component } from '@angular/core';
import { SiteFooter } from '../../shared/layout/site-footer';
import { SiteHeader } from '../../shared/layout/site-header';
import { ApproveSection } from './components/approve-section';
import { BentoSection } from './components/bento-section';
import { CtaBand } from './components/cta-band';
import { FaqSection } from './components/faq-section';
import { HeroSection } from './components/hero-section';
import { LoopSection } from './components/loop-section';
import { SecuritySection } from './components/security-section';
import { TrustedStrip } from './components/trusted-strip';
import { VoicesSection } from './components/voices-section';
import { WhySection } from './components/why-section';

@Component({
  selector: 'landing-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SiteHeader,
    SiteFooter,
    HeroSection,
    LoopSection,
    ApproveSection,
    WhySection,
    BentoSection,
    SecuritySection,
    TrustedStrip,
    VoicesSection,
    FaqSection,
    CtaBand,
  ],
  template: `
    <div class="flex min-h-screen flex-col">
      <site-header />

      <main class="grow">
        <hero-section />
        <loop-section />
        <approve-section />
        <why-section />
        <bento-section />
        <security-section />
        <trusted-strip />
        <voices-section />
        <faq-section />
        <cta-band />
      </main>

      <site-footer />
    </div>
  `,
})
export class LandingPage {}
