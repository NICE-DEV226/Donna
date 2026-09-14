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
    { name: 'search_knowledge', result: '3 documents trouvés.' },
    { name: 'save_generated_document', result: '' },
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

  it('s’affiche toujours déroulé, sans qu’on ait à le déplier à la main', () => {
    // Terminée : la trace est visible telle quelle, pas réduite à un libellé.
    expect(host.querySelector('.trace-header')).not.toBeNull();
    expect(host.querySelectorAll('li')).toHaveLength(2);

    // En cours : toujours visible.
    component.live.set(true);
    detect();
    expect(host.querySelector('.trace-header')).not.toBeNull();
    expect(host.querySelectorAll('li')).toHaveLength(2);
  });

  it('annonce le nombre d’outils utilisés', () => {
    expect(host.querySelector('.trace-header')?.textContent).toContain('2');
  });

  it('liste les outils invoqués sans jamais les confondre avec des sources : pas de lien', () => {
    // Une source se relit dans le panneau, un outil s'exécute — la trace
    // n'ouvre donc jamais de lien qui ferait quitter la conversation.
    expect(host.querySelectorAll('li a')).toHaveLength(0);
    expect(host.querySelectorAll('li')).toHaveLength(2);
  });

  it('affiche le résultat brut renvoyé par l’outil, et un libellé lisible pour ceux qui n’en ont pas', () => {
    const items = Array.from(host.querySelectorAll('li')).map(
      (li) => li.textContent?.trim() ?? '',
    );

    const first = items[0];
    expect(first).toContain('Search knowledge');
    expect(first).toContain('3 documents trouvés.');

    // Un outil sans résultat n’affiche que son libellé, pas de paragraphe vide.
    expect(items[1]).toContain('Save generated document');
    expect(host.querySelectorAll('li')[1].querySelectorAll('p')).toHaveLength(1);
  });

  it('suit le changement de langue', () => {
    const header = host.querySelector('.trace-header')!;
    expect(header.textContent).toContain(EN.workspace.research.done.replace('{{count}}', ''));

    TestBed.inject(Language).set('fr');
    detect();

    const headerFr = host.querySelector('.trace-header')!;
    expect(headerFr.textContent).toContain(FR.workspace.research.done.replace('{{count}}', ''));
  });
});