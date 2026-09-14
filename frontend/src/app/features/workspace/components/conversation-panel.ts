import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  effect,
  inject,
  viewChild,
} from '@angular/core';
import { TranslocoDirective, TranslocoService } from '@jsverse/transloco';
import type { AttachmentOut } from '../../../core/chat/chat.service';
import { DonnaMark } from '../../../shared/brand/donna-mark';
import type { IconName } from '../../../shared/ui/icon-set';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiChip } from '../../../shared/ui/ui-chip';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { UiInput } from '../../../shared/ui/ui-input';
import { UiMarkdown } from '../../../shared/ui/ui-markdown';
import { WorkspaceStore } from '../workspace.store';
import { DonnaInterjection } from './donna-interjection';
import { ResearchTrace } from './research-trace';
import type { ComposerSubmission } from './workspace-composer';
import { WorkspaceComposer } from './workspace-composer';

@Component({
  selector: 'conversation-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  // Sans display explicite, l'élément hôte reste inline : le `h-full` interne
  // n'a alors aucune hauteur de référence et le composer sort de l'écran.
  host: { class: 'block h-full min-h-0' },
  imports: [
    TranslocoDirective,
    DonnaMark,
    DonnaInterjection,
    ResearchTrace,
    UiButton,
    UiChip,
    UiIcon,
    UiInput,
    UiMarkdown,
    WorkspaceComposer,
  ],
  templateUrl: './conversation-panel.html',
})
export class ConversationPanel {
  protected readonly store = inject(WorkspaceStore);
  private readonly transloco = inject(TranslocoService);

  /** Index des points de l'indicateur de réflexion, pour décaler leur pulsation. */
  protected readonly dots = [0, 1, 2];

  /** Le fil se colle en bas : à chaque NOUVEAU message envoyé (entrée utilisateur
   *  incluse, pas seulement pendant le streaming), et pendant qu'un flux écrit —
   *  mais seulement si on est déjà près du bas, pour ne pas arracher la lecture
   *  à quelqu'un qui aurait remonté l'historique. */
  private readonly scrollHost = viewChild.required<ElementRef<HTMLElement>>('scrollHost');
  private previousUserMessages = 0;

  constructor() {
    effect(() => {
      const list = this.store.messages();
      const host = this.scrollHost();
      if (!host) return;

      let userCount = 0;
      for (const message of list) {
        if (message.author === 'user') userCount++;
      }
      const posted = userCount > this.previousUserMessages;
      this.previousUserMessages = userCount;

      const el = host.nativeElement;
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
      if (!posted && !(this.store.streaming() && nearBottom)) return;

      // Laisser le DOM se stabiliser avec le dernier delta avant de mesurer.
      queueMicrotask(() => {
        const latest = this.scrollHost();
        if (!latest) return;
        latest.nativeElement.scrollTop = latest.nativeElement.scrollHeight;
      });
    });
  }

  protected readonly suggestions: readonly { icon: IconName; key: string }[] = [
    { icon: 'search', key: 'workspace.suggestions.search' },
    { icon: 'file-text', key: 'workspace.suggestions.analyze' },
    { icon: 'file-pen-line', key: 'workspace.suggestions.draft' },
  ];

  protected send(submission: ComposerSubmission): void {
    this.store.send(submission.text, submission.files);
  }

  /** Une suggestion vaut question : on envoie son libellé traduit. */
  protected sendSuggestion(key: string): void {
    this.store.send(this.transloco.translate(key));
  }

  /** Ouvre le panneau d'aperçu (PDF/image/Word/Excel rendus inline, voir attachment-preview). */
  protected openAttachment(attachment: AttachmentOut): void {
    this.store.viewAttachment(attachment);
  }

  protected attachmentIcon(attachment: AttachmentOut): IconName {
    if (attachment.kind === 'image') return 'image';
    if (attachment.mime_type.includes('spreadsheet') || attachment.mime_type.includes('excel')) {
      return 'file-spreadsheet';
    }
    return 'file-text';
  }
}
