import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { DocumentPreview } from './components/document-preview';
import { IndexingProgress } from './components/indexing-progress';
import { ProjectMemory } from './components/project-memory';
import { ProjectDialog } from './components/project-dialog';
import { WorkspaceSidebar } from './components/workspace-sidebar';
import { WorkspaceTopbar } from './components/workspace-topbar';
import { ToastStack } from '../../shared/layout/toast-stack';
import { WorkspaceStore } from './workspace.store';

@Component({
  selector: 'workspace-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  // Le store vit et meurt avec l'écran : quitter le workspace remet tout à zéro.
  providers: [WorkspaceStore],
  imports: [
    RouterOutlet,
    DocumentPreview,
    IndexingProgress,
    ProjectMemory,
    ProjectDialog,
    WorkspaceSidebar,
    WorkspaceTopbar,
    ToastStack,
  ],
  template: `
    <!--
      Aucun filet entre les colonnes : la séparation passe par la couche tonale
      (rails en creux, conversation sur le canvas), comme le prescrit le design
      system — « tonal layers » plutôt que traits.
    -->
    <div class="flex h-screen overflow-hidden bg-canvas">
      <workspace-sidebar
        class="shrink-0"
        (newChat)="store.resetConversation()"
        (newProject)="projectDialog.set(true)"
      />

      <div class="flex min-w-0 grow flex-col">
        <workspace-topbar />

        <div class="flex min-h-0 grow">
          <main class="min-w-0 grow">
            <router-outlet />
          </main>

          <!--
            Le rail droit n'existe que tant qu'il a quelque chose à dire.
            Un panneau vide de 320px serait de l'espace volé à la conversation.
          -->
          <!--
            Le rail droit porte le contexte du moment : l'indexation quand elle
            tourne, sinon la mémoire du dossier ouvert.
          -->
          @if (store.isIndexing() || store.activeProject()) {
            <aside
              class="hidden w-80 shrink-0 flex-col gap-xl overflow-y-auto bg-surface-sunken p-lg xl:flex"
            >
              @if (store.isIndexing()) {
                <indexing-progress />
              }
              @if (store.activeProject()) {
                <project-memory />
              }
            </aside>
          }
        </div>
      </div>
    </div>

    @if (projectDialog()) {
      <project-dialog (closed)="projectDialog.set(false)" />
    }

    <!-- Lecture d'une source, sans quitter la conversation. -->
    <document-preview />

    <!-- Notifications : elles informent, elles n'interrompent pas. -->
    <toast-stack [shifted]="!!store.openSource()" />
  `,
})
export class WorkspacePage {
  protected readonly store = inject(WorkspaceStore);
  protected readonly projectDialog = signal(false);
}
