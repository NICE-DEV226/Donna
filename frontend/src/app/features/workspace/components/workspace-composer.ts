import { TextFieldModule } from '@angular/cdk/text-field';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoDirective } from '@jsverse/transloco';
import { Language } from '../../../core/i18n/language';
import { UiIcon } from '../../../shared/ui/ui-icon';

/** L'API de reconnaissance vocale, non typée par TypeScript et encore préfixée. */
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

function speechRecognition(): SpeechRecognitionLike | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as Record<string, new () => SpeechRecognitionLike>;
  const Ctor = w['SpeechRecognition'] ?? w['webkitSpeechRecognition'];
  return Ctor ? new Ctor() : null;
}

export interface ComposerSubmission {
  readonly text: string;
  readonly files: readonly File[];
}

@Component({
  selector: 'workspace-composer',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TextFieldModule, TranslocoDirective, UiIcon],
  templateUrl: './workspace-composer.html',
})
export class WorkspaceComposer {
  readonly disabled = input(false);
  readonly send = output<ComposerSubmission>();

  /** La dictée doit écouter dans la langue de l'interface. */
  protected readonly language = inject(Language);

  protected readonly draft = signal('');
  protected readonly attachments = signal<readonly File[]>([]);
  protected readonly listening = signal(false);

  /**
   * La dictée n'est pas offerte partout. Plutôt qu'un bouton qui ne fait rien
   * sur Firefox, on ne l'affiche que là où elle fonctionne réellement.
   */
  protected readonly voiceSupported = speechRecognition() !== null;

  private recognition: SpeechRecognitionLike | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.recognition?.stop());
  }

  protected readonly canSend = () =>
    (this.draft().trim().length > 0 || this.attachments().length > 0) && !this.disabled();

  protected submit(): void {
    if (!this.canSend()) return;
    this.send.emit({ text: this.draft().trim(), files: this.attachments() });
    this.draft.set('');
    this.attachments.set([]);
  }

  protected onEnter(event: Event): void {
    const keyboard = event as KeyboardEvent;
    if (keyboard.shiftKey) return;
    keyboard.preventDefault();
    this.submit();
  }

  protected onFiles(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = [...(input.files ?? [])];
    this.attachments.update((list) => [...list, ...files]);
    // On vide la sélection pour pouvoir rejoindre le même fichier.
    input.value = '';
  }

  protected removeAttachment(file: File): void {
    this.attachments.update((list) => list.filter((item) => item !== file));
  }

  protected toggleVoice(lang: string): void {
    if (this.listening()) {
      this.recognition?.stop();
      return;
    }

    const recognition = speechRecognition();
    if (!recognition) return;

    this.recognition = recognition;
    recognition.lang = lang === 'fr' ? 'fr-FR' : 'en-US';
    recognition.interimResults = false;
    recognition.continuous = false;

    recognition.onresult = (event) => {
      const transcript = [...(event.results as unknown as Iterable<ArrayLike<{ transcript: string }>>)]
        .map((result) => result[0].transcript)
        .join(' ');
      this.draft.update((current) => (current ? `${current} ${transcript}` : transcript));
    };
    // `onend` couvre aussi bien l'arrêt manuel que l'expiration du silence.
    recognition.onend = () => this.listening.set(false);
    recognition.onerror = () => this.listening.set(false);

    this.listening.set(true);
    recognition.start();
  }
}
