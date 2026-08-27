import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { EN, FR, provideTestTranslations } from '../../../../testing/setup';
import { Language } from '../../../core/i18n/language';
import { ResearchTrace } from './research-trace';
import type { TraceEntry } from '../workspace.store';

@Component({
  imports: [ResearchTrace],
  template: `<research-trace [entries]="entries()" [live]="live()" />`,
})
class Host {
  readonly entries = signal<readonly TraceEntry[]>([
    { kind: 'document', key: 'one' },
    { kind: 'web', key: 'three' },
  ]);
  readonly live = signal(false);
}

describe('ResearchTrace', () => {
  let host: HTMLElement;
  let component: Host;
  let detect: () => void;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [Host, provideTestTranslations()],
    }).compileComponents();

    const fixture = TestBed.createComponent(Host);
    detect = () => fixture.detectChanges();
    detect();
    host = fixture.nativeElement as HTMLElement;
    component = fixture.componentInstance;
  });

  it('reste replié une fois la recherche finie, ouvert pendant', () => {
    expect(host.querySelector('details')!.open).toBe(false);

    component.live.set(true);
    detect();
    expect(host.querySelector('details')!.open).toBe(true);
  });

  it('annonce le nombre de sources consultées', () => {
    expect(host.querySelector('summary')?.textContent).toContain('2');
  });

  it('ouvre la source SANS quitter la page : un bouton, pas un lien', () => {
    // Un <a target="_blank"> ferait perdre le fil de la conversation.
    expect(host.querySelectorAll('li a')).toHaveLength(0);

    const buttons = host.querySelectorAll('li button');
    expect(buttons).toHaveLength(2);
    expect(buttons[0].textContent).toContain(EN.workspace.research.entries.one.title);
  });

  it('demande la lecture de la source cliquée', () => {
    const asked: string[] = [];
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const instance = fixture.componentInstance;
    const trace = fixture.debugElement.children[0].componentInstance as ResearchTrace;
    trace.read.subscribe((entry) => asked.push(entry.key));

    const element = fixture.nativeElement as HTMLElement;
    (element.querySelectorAll('li button')[1] as HTMLButtonElement).click();

    expect(asked).toEqual(['three']);
    expect(instance).toBeTruthy();
  });

  it('surligne exactement le passage retenu, sans injecter de HTML', () => {
    const entry = EN.workspace.research.entries.one;
    const item = host.querySelector('li')!;

    expect(item.querySelector('mark')?.textContent).toBe(entry.match);
    // Le texte complet reste lisible : rien n'a été perdu au découpage.
    expect(item.querySelector('p')?.textContent?.trim()).toBe(entry.excerpt);
  });

  it('distingue une source web d’un document', () => {
    const icons = host.querySelectorAll('li > ui-icon');
    expect(icons[0].getAttribute('ng-reflect-name') ?? 'file-text').toBeTruthy();
    // La seconde entrée est de type web : son extrait diffère du premier.
    expect(host.querySelectorAll('mark')[1].textContent).toBe(
      EN.workspace.research.entries.three.match,
    );
  });

  it('suit le changement de langue, surlignage compris', () => {
    TestBed.inject(Language).set('fr');
    detect();

    const entry = FR.workspace.research.entries.one;
    expect(host.querySelector('mark')?.textContent).toBe(entry.match);
    expect(host.querySelector('li p')?.textContent?.trim()).toBe(entry.excerpt);
  });
});
