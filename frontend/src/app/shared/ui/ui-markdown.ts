import { Pipe, PipeTransform, inject } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

/**
 * Pipe Markdown → HTML sanitisé.
 * Utilise `marked` pour le parsing et `dompurify` pour la sanitization XSS.
 * Configuration : GFM (GitHub Flavored Markdown) + breaks + highlight.js ready.
 */
@Pipe({
  name: 'markdown',
  standalone: true,
})
export class UiMarkdown implements PipeTransform {
  private readonly sanitizer = inject(DomSanitizer);
  private readonly purify = DOMPurify;

  constructor() {
    marked.setOptions({
      gfm: true,
      breaks: true,
      pedantic: false,
    });
  }

  transform(value: string | null | undefined): SafeHtml {
    if (!value?.trim()) return '';

    // Parse Markdown → HTML
    const rawHtml = marked.parse(value, { async: false });

    // Sanitize against XSS (autorise les balises GFM standards + code blocks + tables)
    const cleanHtml = this.purify.sanitize(rawHtml, {
      ADD_TAGS: ['details', 'summary', 'mark', 'kbd'],
      ADD_ATTR: ['class', 'data-language', 'data-line'],
      FORBID_TAGS: ['script', 'style', 'iframe', 'form', 'input', 'button'],
      FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur'],
    });

    return this.sanitizer.bypassSecurityTrustHtml(cleanHtml);
  }
}