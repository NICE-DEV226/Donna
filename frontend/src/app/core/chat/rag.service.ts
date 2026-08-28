import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';

const RAG_BASE = `${environment.apiUrl}/app/rag`;

export interface DocumentOut {
  readonly id: string;
  readonly original_name: string;
  readonly status: string;
  readonly chunk_count: number;
}

@Injectable({ providedIn: 'root' })
export class RagService {
  private readonly http = inject(HttpClient);

  /** Un fichier à la fois côté backend — voir rag_routes.py::upload_document. */
  uploadDocument(file: File): Promise<DocumentOut> {
    const form = new FormData();
    form.append('file', file, file.name);
    return firstValueFrom(this.http.post<DocumentOut>(`${RAG_BASE}/documents`, form));
  }
}
