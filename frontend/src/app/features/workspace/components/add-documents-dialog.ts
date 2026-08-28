import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { WorkspaceStore } from '../workspace.store';

/**
 * Popup « Ajouter des documents » — accessible à tout moment depuis le
 * topbar, pas seulement à l'onboarding (voir workspace-setup, qui reste le
 * premier écran mais ne réapparaît plus après coup, voir autoResumeIfReturningUser).
 * Même zone de dépôt, juste dans un tiroir plutôt qu'en plein écran.
 */
@Component({
  selector: 'add-documents-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, TranslocoDirective, UiButton, UiIcon],
  templateUrl: './add-documents-dialog.html',
})
export class AddDocumentsDialog {
  protected readonly store = inject(WorkspaceStore);
  protected readonly dragging = signal(false);
  protected readonly staged = signal<readonly File[]>([]);

  protected onFiles(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.staged.update((list) => [...list, ...(input.files ? Array.from(input.files) : [])]);
    input.value = '';
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    const files = event.dataTransfer?.files ? Array.from(event.dataTransfer.files) : [];
    this.staged.update((list) => [...list, ...files]);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(true);
  }

  protected removeStaged(file: File): void {
    this.staged.update((list) => list.filter((f) => f !== file));
  }

  protected upload(): void {
    this.store.uploadDocuments(this.staged());
    this.staged.set([]);
  }

  protected close(): void {
    this.staged.set([]);
    this.store.closeAddDocuments();
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.close();
  }
}
