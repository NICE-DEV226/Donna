import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { AddDocumentsDialog } from './components/add-documents-dialog';
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
    AddDocumentsDialog,
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
            L'indexation flotte au-dessus du contenu — une carte, pas un
            tiroir plein écran : aucun fond propre sur ce conteneur, la carte
            à l'intérieur (indexing-progress) porte déjà son propre fond et
            son ombre. Repliable d'un clic, sans jamais faire bouger le reste
            de la mise en page.
          -->
          @if (store.isIndexing()) {
            @if (store.memoryPanelOpen()) {
              <div class="fixed top-20 right-lg z-20 w-80">
                <indexing-progress />
              </div>
            } @else {
              <button
                type="button"
                class="fixed top-20 right-lg z-20 flex h-10 items-center gap-sm rounded-full border border-line bg-surface px-md text-body-sm text-ink-muted shadow-floating transition-colors hover:text-primary"
                [attr.aria-label]="'Expand panel'"
                [attr.aria-expanded]="false"
                (click)="store.toggleMemoryPanel()"
              >
                <span class="size-2 animate-pulse rounded-full bg-success" aria-hidden="true"></span>
                <ui-icon name="chevron-left" [size]="14" />
              </button>
            }
          }
        </div>
      </div>
    </div>

    <!-- Lecture d'une source, sans quitter la conversation. -->
    <document-preview />

    <!-- Aperçu d'une pièce jointe (générée ou envoyée), même logique. -->
    <attachment-preview />

    <!-- Popup « Ajouter des documents », déclenché depuis le topbar. -->
    <add-documents-dialog />

    <!-- Notifications : elles informent, elles n'interrompent pas. -->
    <toast-stack
      [shifted]="!!store.openSource() || !!store.openAttachment() || store.addDocumentsOpen()"
    />
  `,
})
export class WorkspacePage {
  protected readonly store = inject(WorkspaceStore);
}
