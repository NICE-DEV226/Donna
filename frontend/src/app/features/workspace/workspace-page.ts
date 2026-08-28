import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { AttachmentPreview } from './components/attachment-preview';
import { DocumentPreview } from './components/document-preview';
import { IndexingProgress } from './components/indexing-progress';
import { WorkspaceSidebar } from './components/workspace-sidebar';
import { WorkspaceTopbar } from './components/workspace-topbar';
import { ToastStack } from '../../shared/layout/toast-stack';
import { UiIcon } from '../../shared/ui/ui-icon';
import { WorkspaceStore } from './workspace.store';

@Component({
  selector: 'workspace-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  // Le store vit et meurt avec l'écran : quitter le workspace remet tout à zéro.
  providers: [WorkspaceStore],
  imports: [
    RouterOutlet,
    AttachmentPreview,
    DocumentPreview,
    IndexingProgress,
    WorkspaceSidebar,
    WorkspaceTopbar,
    ToastStack,
    UiIcon,
  ],
  template: `
    <!--
      Aucun filet entre les colonnes : la séparation passe par la couche tonale
      (rails en creux, conversation sur le canvas), comme le prescrit le design
      system — « tonal layers » plutôt que traits.
    -->
    <div class="flex h-screen overflow-hidden bg-canvas">
      <workspace-sidebar class="shrink-0" (newChat)="store.resetConversation()" />

      <div class="flex min-w-0 grow flex-col">
        <workspace-topbar />

        <div class="flex min-h-0 grow">
          <main class="min-w-0 grow">
            <router-outlet />
          </main>

          <!--
            Le rail droit montre l'indexation quand elle tourne — un tiroir
            FLOTTANT (fixed), pas une colonne qui rétrécit la conversation :
            replié d'un clic, sans jamais faire bouger le reste de la mise en
            page.
          -->
          @if (store.isIndexing()) {
            <button
              type="button"
              class="fixed top-1/2 z-30 flex h-16 w-6 -translate-y-1/2 items-center justify-center rounded-l-lg border border-r-0 border-line bg-surface text-ink-muted shadow-floating transition-[right] duration-200 hover:text-primary"
              [style.right]="store.memoryPanelOpen() ? '20rem' : '0'"
              [attr.aria-label]="store.memoryPanelOpen() ? 'Collapse panel' : 'Expand panel'"
              [attr.aria-expanded]="store.memoryPanelOpen()"
              (click)="store.toggleMemoryPanel()"
            >
              <ui-icon [name]="store.memoryPanelOpen() ? 'chevron-right' : 'chevron-left'" [size]="14" />
            </button>

            @if (store.memoryPanelOpen()) {
              <aside
                class="fixed inset-y-0 right-0 z-20 flex w-80 flex-col gap-xl overflow-y-auto border-l border-line bg-surface-sunken p-lg shadow-floating"
              >
                <indexing-progress />
              </aside>
            }
          }
        </div>
      </div>
    </div>

    <!-- Lecture d'une source, sans quitter la conversation. -->
    <document-preview />

    <!-- Aperçu d'une pièce jointe (générée ou envoyée), même logique. -->
    <attachment-preview />

    <!-- Notifications : elles informent, elles n'interrompent pas. -->
    <toast-stack [shifted]="!!store.openSource() || !!store.openAttachment()" />
  `,
})
export class WorkspacePage {
  protected readonly store = inject(WorkspaceStore);
}
