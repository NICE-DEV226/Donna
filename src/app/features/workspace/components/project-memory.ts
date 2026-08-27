import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslocoDirective } from '@jsverse/transloco';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { WorkspaceStore } from '../workspace.store';

/**
 * Ce que DONNA a retenu du dossier ouvert.
 *
 * La distinction que ce panneau rend visible : les DOCUMENTS d'un projet
 * rejoignent la base générale et servent partout, mais la MÉMOIRE d'un client
 * lui reste propre. Ouvrir un autre dossier change ce qui est listé ici.
 */
@Component({
  selector: 'project-memory',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoDirective, UiIcon],
  templateUrl: './project-memory.html',
})
export class ProjectMemory {
  protected readonly store = inject(WorkspaceStore);
}
