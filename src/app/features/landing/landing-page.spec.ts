import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { Language } from '../../core/i18n/language';
import { EN, FR, provideTestTranslations, stubIntersectionObserver } from '../../../testing/setup';
import { LandingPage } from './landing-page';

describe('LandingPage', () => {
  let fixture: ComponentFixture<LandingPage>;
  let host: HTMLElement;

  beforeAll(stubIntersectionObserver);

  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      imports: [LandingPage, provideTestTranslations()],
      providers: [provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(LandingPage);
    fixture.detectChanges();
    host = fixture.nativeElement as HTMLElement;
  });

  it("s'affiche en anglais par défaut", () => {
    expect(host.querySelector('h1')?.textContent?.trim()).toBe(EN.hero.title);
    expect(host.textContent).toContain(EN.bento.title);
  });

  it('bascule tout le contenu en français via le sélecteur', () => {
    TestBed.inject(Language).set('fr');
    fixture.detectChanges();

    expect(host.querySelector('h1')?.textContent?.trim()).toBe(FR.hero.title);
    expect(host.textContent).toContain(FR.bento.title);
    expect(document.documentElement.lang).toBe('fr');
  });

  it("n'a aucun lien mort : chaque ancre vise une section réelle, en-tête ET pied de page", () => {
    const fragments = [...host.querySelectorAll('a[href^="/#"], a[href^="#"]')]
      .map((a) => a.getAttribute('href')!.replace(/^\/?#/, ''))
      .filter(Boolean);

    expect(fragments.length).toBeGreaterThan(0);
    for (const fragment of fragments) {
      expect(host.querySelector(`#${fragment}`), `section #${fragment} introuvable`).not.toBeNull();
    }

    // Aucun href="#" nulle part : ni dans la nav, ni dans le pied de page.
    expect(host.querySelectorAll('a[href="#"]')).toHaveLength(0);

    // Le pied de page mène quelque part : ancres, routes ou adresse.
    const footerLinks = [...host.querySelectorAll('site-footer a')];
    expect(footerLinks.length).toBeGreaterThan(0);
    for (const link of footerLinks) {
      const href = link.getAttribute('href') ?? '';
      expect(href, `lien « ${link.textContent?.trim()} » sans cible`).not.toBe('#');
      expect(href.length, `lien « ${link.textContent?.trim()} » vide`).toBeGreaterThan(0);
    }
  });

  it('expose une section sécurité, indispensable à un produit qui lit des contrats', () => {
    const section = host.querySelector('#security');
    expect(section).not.toBeNull();
    expect(section!.textContent).toContain(EN.security.title);
    // Le journal d'audit est montré, pas seulement promis.
    expect(section!.querySelector('spot-audit svg')).not.toBeNull();
  });

  it("l'ancre du CTA secondaire du hero pointe vers une section existante", () => {
    const cta = [...host.querySelectorAll('a[href^="#"]')].find(
      (a) => a.textContent?.trim() === EN.hero.ctaSecondary,
    );
    expect(cta).toBeDefined();
    expect(host.querySelector(cta!.getAttribute('href')!)).not.toBeNull();
  });

  it('rend la FAQ avec des <details> natifs, accessibles sans JavaScript', () => {
    const items = host.querySelectorAll('#faq details');
    expect(items.length).toBe(Object.keys(EN.faq.items).length);
    expect(items[0].querySelector('summary')?.textContent).toContain(EN.faq.items.data.q);
  });

  it('rend les six tuiles de la grille, chacune avec son illustration maison', () => {
    const tiles = host.querySelectorAll('#features li');
    expect(tiles).toHaveLength(Object.keys(EN.bento.tiles).length);
    // Chaque tuile porte un SVG dessiné à la main, pas un asset externe.
    for (const tile of tiles) {
      expect(tile.querySelector('svg')).not.toBeNull();
    }
    expect(host.querySelectorAll('#features svg[aria-hidden="true"]')).toHaveLength(tiles.length);
  });

  it('donne un avatar monogramme à chaque témoignage, sans photo inventée', () => {
    const avatars = host.querySelectorAll('#voices ui-avatar');
    expect(avatars).toHaveLength(Object.keys(EN.voices.quotes).length);
    expect(host.querySelectorAll('#voices img')).toHaveLength(0);
    // Harvey Specter → « HS »
    expect(avatars[0].textContent?.trim()).toBe('HS');
  });
});
