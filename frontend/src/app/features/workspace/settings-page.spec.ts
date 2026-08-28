import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { EN, mockFiles, provideTestTranslations } from '../../../testing/setup';
import { Toasts } from '../../core/notifications/toasts';
import { ProfilePage } from './profile-page';
import { SettingsPage } from './settings-page';
import { WorkspaceStore } from './workspace.store';

describe('Paramètres et profil', () => {
  let store: WorkspaceStore;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [provideTestTranslations()],
      providers: [provideRouter([]), WorkspaceStore],
    });
    store = TestBed.inject(WorkspaceStore);
  });

  function render<T>(component: new (...args: never[]) => T): {
    host: HTMLElement;
    fixture: ComponentFixture<T>;
  } {
    const fixture = TestBed.createComponent(component as never) as ComponentFixture<T>;
    fixture.detectChanges();
    return { host: fixture.nativeElement as HTMLElement, fixture };
  }

  describe('connecteurs', () => {
    it('liste chaque outil avec ce qu’il donne à lire', () => {
      const { host } = render(SettingsPage);
      const rows = host.querySelectorAll('li');

      expect(rows).toHaveLength(store.connections().length);
      expect(rows[0].textContent).toContain(EN.workspace.connections.drive);
      // L'utilisateur doit savoir ce qu'il accorde, pas seulement à qui.
      expect(rows[0].textContent).toContain(EN.workspace.connectorsList.drive.detail);
    });

    it('coupe réellement l’accès, pas seulement l’affichage', () => {
      const { host, fixture } = render(SettingsPage);
      const connectedBefore = store.connections().filter((c) => c.connected).length;

      const disconnect = [...host.querySelectorAll('button')].find(
        (b) => b.textContent?.trim() === EN.workspace.settings.connectors.disconnect,
      ) as HTMLButtonElement;
      disconnect.click();
      fixture.detectChanges();

      expect(store.connections().filter((c) => c.connected)).toHaveLength(connectedBefore - 1);
      // L'état vit dans le store : le rail et l'aperçu le reflètent aussi.
      expect(store.connections()[0].connected).toBe(false);
    });
  });

  describe('mémoire', () => {
    it('n’offre l’effacement que s’il y a quelque chose à effacer', () => {
      const { host, fixture } = render(SettingsPage);
      const purge = () =>
        [...host.querySelectorAll('button')].find(
          (b) => b.textContent?.trim() === EN.workspace.settings.memory.purge,
        ) as HTMLButtonElement;

      expect(purge().disabled).toBe(true);

      store.addDocuments(mockFiles(12));
      fixture.detectChanges();
      expect(purge().disabled).toBe(false);

      purge().click();
      fixture.detectChanges();
      expect(store.documentCount()).toBe(0);
    });
  });

  describe('profil', () => {
    it('refuse un e-mail invalide', () => {
      const { host, fixture } = render(ProfilePage);
      const email = host.querySelector<HTMLInputElement>('#profile-email')!;
      const before = store.profile().email;

      email.value = 'pas-un-email';
      email.dispatchEvent(new Event('input'));
      host.querySelector('form')!.dispatchEvent(new Event('submit'));
      fixture.detectChanges();

      expect(store.profile().email).toBe(before);
      expect(host.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
        EN.auth.fields.emailInvalid,
      );
    });

    it('enregistre et le fait savoir', () => {
      const toasts = TestBed.inject(Toasts);
      const { host, fixture } = render(ProfilePage);

      const name = host.querySelector<HTMLInputElement>('#profile-name')!;
      name.value = 'Donna Paulsen';
      name.dispatchEvent(new Event('input'));
      host.querySelector('form')!.dispatchEvent(new Event('submit'));
      fixture.detectChanges();

      expect(store.profile().name).toBe('Donna Paulsen');
      expect(toasts.items()).toHaveLength(1);
      // Le monogramme suit le nom, sans photo inventée.
      expect(host.querySelector('ui-avatar')?.textContent?.trim()).toBe('DP');
    });
  });
});
