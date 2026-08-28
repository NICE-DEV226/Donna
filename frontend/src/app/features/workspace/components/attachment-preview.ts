import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, signal } from '@angular/core';
import { DomSanitizer, type SafeHtml, type SafeResourceUrl, type SafeUrl } from '@angular/platform-browser';
import { TranslocoDirective } from '@jsverse/transloco';
import type { AttachmentOut } from '../../../core/chat/chat.service';
import { FileAccess } from '../../../core/files/file-access';
import { UiIcon } from '../../../shared/ui/ui-icon';
import { WorkspaceStore } from '../workspace.store';

const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const MARKDOWN_MIME = 'text/markdown';
const JSON_MIME = 'application/json';

type PreviewState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'error' }
  | { readonly kind: 'unsupported' }
  | { readonly kind: 'image'; readonly url: SafeUrl }
  | { readonly kind: 'pdf'; readonly url: SafeResourceUrl }
  | { readonly kind: 'text'; readonly content: string }
  | { readonly kind: 'html'; readonly html: SafeHtml }
  | { readonly kind: 'table'; readonly rows: readonly (readonly string[])[] };

/**
 * Aperçu inline d'une pièce jointe (générée par un outil, ou envoyée par
 * l'utilisateur) — même panneau latéral que document-preview (les deux ne
 * s'ouvrent jamais ensemble, voir WorkspaceStore.viewAttachment), pour ne
 * jamais faire quitter la conversation pour un simple coup d'œil.
 *
 * PDF/image : rendu natif du navigateur. Markdown/Word : rendus en HTML
 * (marked+DOMPurify / mammoth). JSON : reformaté avec indentation (structure
 * lisible plutôt qu'un blob sur une ligne si le fichier est minifié). Excel :
 * tableau via exceljs. Tout est chargé à la demande. Le reste (audio, types
 * inconnus) retombe sur "ouvrir" — pas de quoi construire un lecteur dédié.
 */
@Component({
  selector: 'attachment-preview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [A11yModule, TranslocoDirective, UiIcon],
  templateUrl: './attachment-preview.html',
})
export class AttachmentPreview {
  protected readonly store = inject(WorkspaceStore);
  private readonly files = inject(FileAccess);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly state = signal<PreviewState>({ kind: 'loading' });
  private objectUrl: string | null = null;

  constructor() {
    effect(() => {
      const attachment = this.store.openAttachment();
      if (attachment) void this.load(attachment);
    });
    this.destroyRef.onDestroy(() => this.revokeObjectUrl());
  }

  protected openOriginal(url: string): void {
    void this.files.open(url);
  }

  // Le template ne peut pas affiner l'union à partir de `@switch (state().kind)` —
  // ces accesseurs portent l'affirmation de type au même endroit que le rendu,
  // plutôt que de parsemer le template de `$any(...)`.
  protected asUrl(state: PreviewState): SafeUrl {
    return (state as { url: SafeUrl }).url;
  }

  protected asResourceUrl(state: PreviewState): SafeResourceUrl {
    return (state as { url: SafeResourceUrl }).url;
  }

  protected asText(state: PreviewState): string {
    return (state as { content: string }).content;
  }

  protected asHtml(state: PreviewState): SafeHtml {
    return (state as { html: SafeHtml }).html;
  }

  protected asRows(state: PreviewState): readonly (readonly string[])[] {
    return (state as { rows: readonly (readonly string[])[] }).rows;
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.store.closeAttachment();
  }

  private async load(attachment: AttachmentOut): Promise<void> {
    this.revokeObjectUrl();
    this.state.set({ kind: 'loading' });

    let blob: Blob;
    try {
      blob = await this.files.fetch(attachment.file_url);
    } catch {
      this.state.set({ kind: 'error' });
      return;
    }
    // Une navigation a pu ouvrir une autre pièce jointe pendant le fetch —
    // ce résultat, périmé, ne doit pas écraser le nouvel état.
    if (this.store.openAttachment()?.id !== attachment.id) return;

    try {
      this.state.set(await this.render(blob, attachment.mime_type));
    } catch {
      this.state.set({ kind: 'unsupported' });
    }
  }

  private async render(blob: Blob, mimeType: string): Promise<PreviewState> {
    if (mimeType.startsWith('image/')) {
      this.objectUrl = URL.createObjectURL(blob);
      return { kind: 'image', url: this.sanitizer.bypassSecurityTrustUrl(this.objectUrl) };
    }

    if (mimeType === 'application/pdf') {
      this.objectUrl = URL.createObjectURL(blob);
      return { kind: 'pdf', url: this.sanitizer.bypassSecurityTrustResourceUrl(this.objectUrl) };
    }

    if (mimeType === MARKDOWN_MIME) {
      const [{ marked }, DOMPurify] = await Promise.all([import('marked'), import('dompurify')]);
      const html = DOMPurify.default.sanitize(await marked.parse(await blob.text()));
      return { kind: 'html', html: this.sanitizer.bypassSecurityTrustHtml(html) };
    }

    if (mimeType === JSON_MIME) {
      const raw = await blob.text();
      try {
        return { kind: 'text', content: JSON.stringify(JSON.parse(raw), null, 2) };
      } catch {
        // JSON invalide malgré le mime type déclaré : montrer le brut plutôt qu'échouer.
        return { kind: 'text', content: raw };
      }
    }

    if (mimeType.startsWith('text/')) {
      return { kind: 'text', content: await blob.text() };
    }

    if (mimeType === DOCX_MIME) {
      const mammoth = await import('mammoth');
      const arrayBuffer = await blob.arrayBuffer();
      const { value } = await mammoth.convertToHtml({ arrayBuffer });
      // Sortie de mammoth : balises structurelles (p/strong/table/...) issues
      // du docx, jamais de <script> — mammoth ne préserve aucun contenu
      // exécutable du document source.
      return { kind: 'html', html: this.sanitizer.bypassSecurityTrustHtml(value) };
    }

    if (mimeType === XLSX_MIME) {
      const { Workbook } = await import('exceljs');
      const workbook = new Workbook();
      await workbook.xlsx.load(await blob.arrayBuffer());
      const sheet = workbook.worksheets[0];
      if (!sheet) return { kind: 'unsupported' };

      const rows: string[][] = [];
      sheet.eachRow((row) => {
        // `row.values` est indexé à partir de 1 (l'index 0 est toujours vide) —
        // artefact ExcelJS, pas une colonne réelle.
        const cells = (row.values as unknown[]).slice(1);
        rows.push(cells.map((cell) => (cell == null ? '' : String(cell))));
      });
      return rows.length ? { kind: 'table', rows } : { kind: 'unsupported' };
    }

    return { kind: 'unsupported' };
  }

  private revokeObjectUrl(): void {
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
  }
}
