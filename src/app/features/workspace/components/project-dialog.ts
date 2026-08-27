import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, inject, output, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiField } from '../../../shared/ui/ui-field';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { UiInput } from '../../../shared/ui/ui-input';
import { WorkspaceStore } from '../workspace.store';

/**
 * Création d'un dossier client.
 *
 * Modal assumé : le formulaire est court et demande une décision. C'est
 * l'inverse de l'indexation, qui dure et ne doit rien bloquer.
 */
@Component({
  selector: 'project-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, ReactiveFormsModule, TranslocoDirective, UiButton, UiField, UiIcon, UiInput],
  templateUrl: './project-dialog.html',
})
export class ProjectDialog {
  readonly closed = output<void>();

  private readonly store = inject(WorkspaceStore);

  protected readonly documents = signal(0);
  protected readonly dragging = signal(false);

  protected readonly form = inject(FormBuilder).nonNullable.group({
    name: ['', [Validators.required]],
    client: [''],
  });

  protected onFiles(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.documents.update((count) => count + (input.files?.length ?? 0));
    input.value = '';
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    this.documents.update((count) => count + (event.dataTransfer?.files.length ?? 0));
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(true);
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.closed.emit();
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { name, client } = this.form.getRawValue();
    this.store.createProject(name, client, this.documents());
    this.closed.emit();
  }
}
