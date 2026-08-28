import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiButton } from '../../../shared/ui/ui-button';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { WorkspaceStore } from '../workspace.store';
import { ConnectionsPanel } from './connections-panel';

/** Premier écran de l'espace : constituer la mémoire avant de pouvoir demander. */
@Component({
  selector: 'workspace-setup',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block h-full overflow-y-auto' },
  imports: [TranslocoDirective, ConnectionsPanel, UiButton, UiIcon],
  templateUrl: './workspace-setup.html',
})
export class WorkspaceSetup {
  protected readonly store = inject(WorkspaceStore);
  protected readonly dragging = signal(false);

  protected onFiles(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.store.addDocuments(input.files ? Array.from(input.files) : []);
    // On vide la sélection pour que le même fichier puisse être redéposé.
    input.value = '';
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    this.store.addDocuments(event.dataTransfer?.files ? Array.from(event.dataTransfer.files) : []);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(true);
  }
}
