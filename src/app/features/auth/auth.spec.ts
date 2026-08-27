import type { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthService } from '../../core/auth/auth.service';
import { Language } from '../../core/i18n/language';
import { EN, FR, provideTestTranslations, stubIntersectionObserver } from '../../../testing/setup';
import { LoginPage } from './login-page';
import { SignupPage } from './signup-page';

const authStub = {
  pending: () => false,
  signIn: vi.fn().mockResolvedValue(true),
  signUp: vi.fn().mockResolvedValue(true),
  signInWithGoogle: vi.fn().mockResolvedValue(true),
};

async function mount<T>(component: Type<T>): Promise<ComponentFixture<T>> {
  await TestBed.configureTestingModule({
    imports: [component, provideTestTranslations()],
    providers: [provideRouter([]), { provide: AuthService, useValue: authStub }],
  }).compileComponents();

  const fixture = TestBed.createComponent(component);
  fixture.detectChanges();
  return fixture;
}

beforeAll(stubIntersectionObserver);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  TestBed.resetTestingModule();
});

describe('LoginPage', () => {
  it('ne soumet rien tant que le formulaire est invalide, et révèle les erreurs', async () => {
    const fixture = await mount(LoginPage);
    const host = fixture.nativeElement as HTMLElement;

    host.querySelector('form')!.dispatchEvent(new Event('submit'));
    fixture.detectChanges();

    expect(authStub.signIn).not.toHaveBeenCalled();
    const errors = host.querySelectorAll('[role="alert"]');
    expect(errors.length).toBeGreaterThanOrEqual(2);
    expect(errors[0].textContent?.trim()).toBe(EN.auth.fields.required);
  });

  it("marque le champ en erreur pour les lecteurs d'écran", async () => {
    const fixture = await mount(LoginPage);
    const host = fixture.nativeElement as HTMLElement;
    const email = host.querySelector<HTMLInputElement>('#email')!;

    expect(email.getAttribute('aria-invalid')).toBeNull();
    expect(email.getAttribute('aria-describedby')).toBe('email-description');

    email.value = 'pas-un-email';
    email.dispatchEvent(new Event('input'));
    email.dispatchEvent(new Event('blur'));
    fixture.detectChanges();

    expect(email.getAttribute('aria-invalid')).toBe('true');
    expect(host.querySelector('#email-description')?.textContent?.trim()).toBe(
      EN.auth.fields.emailInvalid,
    );
  });

  it('soumet les identifiants quand le formulaire est valide', async () => {
    const fixture = await mount(LoginPage);
    const host = fixture.nativeElement as HTMLElement;

    const email = host.querySelector<HTMLInputElement>('#email')!;
    email.value = 'harvey@pearsonhardman.com';
    email.dispatchEvent(new Event('input'));

    const password = host.querySelector<HTMLInputElement>('#password')!;
    password.value = 'closer-2026';
    password.dispatchEvent(new Event('input'));

    fixture.detectChanges();
    host.querySelector('form')!.dispatchEvent(new Event('submit'));

    expect(authStub.signIn).toHaveBeenCalledWith({
      email: 'harvey@pearsonhardman.com',
      password: 'closer-2026',
    });
  });

  it('bascule la visibilité du mot de passe', async () => {
    const fixture = await mount(LoginPage);
    const host = fixture.nativeElement as HTMLElement;
    const selector = `[aria-label="${EN.auth.fields.showPassword}"]`;

    expect(host.querySelector<HTMLInputElement>('#password')!.type).toBe('password');
    host.querySelector<HTMLButtonElement>(selector)!.click();
    fixture.detectChanges();

    expect(host.querySelector<HTMLInputElement>('#password')!.type).toBe('text');
    expect(host.querySelector(`[aria-label="${EN.auth.fields.hidePassword}"]`)).not.toBeNull();
  });

  it('traduit aussi les messages de validation', async () => {
    const fixture = await mount(LoginPage);
    const host = fixture.nativeElement as HTMLElement;

    TestBed.inject(Language).set('fr');
    fixture.detectChanges();

    const email = host.querySelector<HTMLInputElement>('#email')!;
    email.value = 'pas-un-email';
    email.dispatchEvent(new Event('input'));
    email.dispatchEvent(new Event('blur'));
    fixture.detectChanges();

    expect(host.querySelector('#email-description')?.textContent?.trim()).toBe(
      FR.auth.fields.emailInvalid,
    );
  });
});

describe('SignupPage', () => {
  it('exige le consentement avant de créer le compte', async () => {
    const fixture = await mount(SignupPage);
    const host = fixture.nativeElement as HTMLElement;

    const fill = (selector: string, value: string) => {
      const input = host.querySelector<HTMLInputElement>(selector)!;
      input.value = value;
      input.dispatchEvent(new Event('input'));
    };

    fill('#fullName', 'Donna Paulsen');
    fill('#email', 'donna@pearsonhardman.com');
    fill('#password', 'sheknows2026');
    fixture.detectChanges();

    host.querySelector('form')!.dispatchEvent(new Event('submit'));
    expect(authStub.signUp).not.toHaveBeenCalled();

    host.querySelector<HTMLInputElement>('[formcontrolname="terms"]')!.click();
    fixture.detectChanges();

    host.querySelector('form')!.dispatchEvent(new Event('submit'));
    expect(authStub.signUp).toHaveBeenCalledWith({
      fullName: 'Donna Paulsen',
      email: 'donna@pearsonhardman.com',
      password: 'sheknows2026',
    });
  });

  it('refuse un mot de passe trop court, avec le seuil interpolé dans le message', async () => {
    const fixture = await mount(SignupPage);
    const host = fixture.nativeElement as HTMLElement;
    const password = host.querySelector<HTMLInputElement>('#password')!;

    password.value = 'court';
    password.dispatchEvent(new Event('input'));
    password.dispatchEvent(new Event('blur'));
    fixture.detectChanges();

    const message = host.querySelector('#password-description')?.textContent?.trim();
    expect(message).toBe(EN.auth.fields.passwordMin.replace('{{count}}', '8'));
    // Le paramètre doit être remplacé, pas affiché tel quel.
    expect(message).not.toContain('{{');
  });
});
