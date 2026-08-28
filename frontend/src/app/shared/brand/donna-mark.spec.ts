import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { DonnaMark } from './donna-mark';

@Component({
  imports: [DonnaMark],
  template: `
    <donna-mark />
    <donna-mark closed />
    <donna-mark boxed label="DONNA" />
  `,
})
class Host {}

describe('DonnaMark', () => {
  function render(): HTMLElement {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('dessine le fût, l’arc et les deux liaisons', () => {
    const [mark] = render().querySelectorAll('donna-mark');
    // 2 tracés pour le D ouvert + 2 liaisons qui ne se tracent qu'une fois validé.
    expect(mark.querySelectorAll('path')).toHaveLength(4);
    expect(mark.querySelectorAll('.donna-mark__link')).toHaveLength(2);
  });

  it('reste ouvert par défaut et se referme à l’état validé', () => {
    const marks = render().querySelectorAll('donna-mark');
    expect(marks[0].classList).not.toContain('donna-mark--closed');
    expect(marks[1].classList).toContain('donna-mark--closed');
  });

  it('est décoratif sans libellé, et nommé avec', () => {
    const marks = render().querySelectorAll('donna-mark');
    const plain = marks[0].querySelector('svg')!;
    expect(plain.getAttribute('aria-hidden')).toBe('true');
    expect(plain.getAttribute('role')).toBeNull();

    const named = marks[2].querySelector('svg')!;
    expect(named.getAttribute('role')).toBe('img');
    expect(named.getAttribute('aria-label')).toBe('DONNA');
    expect(named.getAttribute('aria-hidden')).toBeNull();
  });

  it('ajoute la pastille uniquement en version encadrée', () => {
    const marks = render().querySelectorAll('donna-mark');
    expect(marks[0].querySelector('rect')).toBeNull();
    expect(marks[2].querySelector('rect')).not.toBeNull();
  });
});
