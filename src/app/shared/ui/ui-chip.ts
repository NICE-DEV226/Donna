import { Directive, computed, input } from '@angular/core';

export type ChipTone = 'neutral' | 'primary' | 'success';

const BASE =
  'inline-flex items-center gap-xs rounded-full px-sm py-xs text-label-caps uppercase';

// Fonds très légèrement teintés (5–10%) — le design system interdit les aplats saturés.
const TONES: Record<ChipTone, string> = {
  neutral: 'bg-surface-raised text-ink-muted',
  primary: 'bg-primary/5 text-primary',
  success: 'bg-success/5 text-success',
};

@Directive({
  selector: '[uiChip]',
  host: { '[class]': 'classes()' },
})
export class UiChip {
  readonly tone = input<ChipTone, ChipTone | ''>('neutral', {
    alias: 'uiChip',
    transform: (value) => value || 'neutral',
  });

  protected readonly classes = computed(() => `${BASE} ${TONES[this.tone()]}`);
}
