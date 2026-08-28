import { HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { TranslocoService } from '@jsverse/transloco';
import type { AttachmentOut, SourceOut } from '../../core/chat/chat.service';
import { ChatService } from '../../core/chat/chat.service';
import { RagService } from '../../core/chat/rag.service';
import { RealtimeService } from '../../core/chat/realtime.service';
import { Toasts } from '../../core/notifications/toasts';
import { PulseService } from '../../core/notifications/pulse.service';

/** Étapes de l'indexation initiale. L'ordre du tableau EST le déroulé. */
export const INGEST_STEPS = ['reading', 'extracting', 'indexing'] as const;
export type IngestStep = (typeof INGEST_STEPS)[number];

/** Un outil invoqué pendant la recherche en cours — voir événements tool_call du flux SSE. */
export interface TraceEntry {
  readonly name: string;
  readonly result: string;
}

/** Une source citable, prête à être lue dans le panneau document-preview — réelle (RAG) ou de démo (agenda). */
export interface SourceRef {
  readonly kind: 'document' | 'web';
  readonly id: string;
  readonly title: string;
  readonly excerpt: string;
  /** URL relative backend (à ouvrir via FileAccess, authentifiée) ou externe (lien direct). */
  readonly url?: string;
  readonly meta?: string;
}

function sourceRefFromOut(source: SourceOut): SourceRef {
  return {
    kind: 'document',
    id: source.doc_id,
    title: source.original_name,
    excerpt: source.excerpt,
    url: source.file_url,
  };
}

/** Extrait le `detail` FastAPI (`{"detail": "..."}`) d'une 4xx — jamais pour une 5xx (message technique, pas pour l'utilisateur). */
function uploadErrorDetail(err: unknown): string | null {
  if (!(err instanceof HttpErrorResponse)) return null;
  if (err.status < 400 || err.status >= 500) return null;
  const detail = (err.error as { detail?: unknown } | null)?.detail;
  return typeof detail === 'string' ? detail : null;
}

/** Un fait que DONNA a retenu. Sa portée dit qui peut s'en servir. */
export interface MemoryNote {
  readonly id: number;
  readonly text?: string;
}

/** Un outil branché. Le couper doit couper l'accès, pas seulement l'affichage. */
export interface Connection {
  readonly key: string;
  readonly icon: string;
  readonly connected: boolean;
}

/** Un fil. Ouvrir une conversation ancienne doit rendre son contenu, pas un écran vide. */
export interface Conversation {
  readonly id: string;
  /** Clé de traduction pour les fils d'exemple. */
  readonly titleKey?: string;
  /** Titre déduit de la première question, ou renvoyé par le backend. */
  readonly title?: string;
  readonly messages: readonly Message[];
}

export interface Message {
  readonly id: number;
  readonly author: 'user' | 'donna';
  /** Texte réel — utilisateur ou réponse de DONNA. */
  readonly text?: string;
  /** Clé de traduction, uniquement pour les fils d'exemple restants (aucun ne devrait en avoir). */
  readonly textKey?: string;
  /** Citations réelles (RAG) sur lesquelles s'appuie la réponse — cliquables, voir document-preview. */
  readonly sources?: readonly SourceRef[];
  /** Fichiers que DONNA a créés en répondant (Word/Excel/PDF via le bridge MCP). */
  readonly attachments?: readonly AttachmentOut[];
  /** Action proposée, en attente de validation. */
  readonly actionKey?: string;
  /**
   * Message que DONNA amène d'elle-même, sans qu'on l'ait sollicitée.
   * Ce n'est pas un rappel : c'est une arrivée, avec le travail déjà fait.
   *
   * ⚠️ Aucun message réel ne porte ce kind pour l'instant : donna-interjection
   * est entièrement scénarisé (voir son fichier).
   *
   * 'question' : la réponse en cours contient une question de clarification
   * (outil ask_user invoqué pendant ce même flux — voir streamAnswer).
   * 'reminder' : rappel programmé, injecté en direct dans le fil concerné
   * (voir l'abonnement à pulse.stream côté constructeur).
   */
  readonly kind?: 'interjection' | 'clarification' | 'question' | 'reminder';
  /** Réponses proposées, quand DONNA demande une précision (démo uniquement — clés de traduction). */
  readonly optionKeys?: readonly string[];
  /** Choix réels proposés par ask_user (texte brut, pas des clés — voir tools.py::ask_user). */
  readonly options?: readonly string[];
}

const SEED_CONNECTIONS: readonly Connection[] = [
  { key: 'drive', icon: 'folder', connected: true },
  { key: 'calendar', icon: 'calendar-days', connected: true },
  { key: 'gmail', icon: 'mail', connected: true },
  { key: 'slack', icon: 'message-square', connected: false },
];

/**
 * État de l'espace de travail.
 *
 * Deux temps distincts, à ne pas confondre :
 *  - l'INDEXATION initiale, une seule fois, quand l'utilisateur dépose les
 *    documents de l'entreprise. Elle tourne EN ARRIÈRE-PLAN et n'empêche
 *    jamais de discuter ; le rail droit en montre l'avancement.
 *  - les QUESTIONS ensuite, où DONNA puise dans cette mémoire. Là, le seul
 *    retour visuel est l'indicateur de réflexion, dans le fil.
 *
 * Branché sur le vrai backend pour : conversations, messages (streaming SSE),
 * indexation RAG, mémoire (faits retenus). Restent scénarisés : Connections
 * (pas d'endpoint de statut/toggle Google encore exposé), donna-interjection.
 */
@Injectable()
export class WorkspaceStore {
  private nextId = 1;
  /** Fichiers déposés avant le lancement de l'espace — voir addDocuments/initialise. */
  private stagedFiles: File[] = [];
  /** Documents dont on attend encore la fin d'indexation (voir rag_ingestion_status). */
  private readonly pendingIngestDocIds = new Set<string>();

  private readonly toasts = inject(Toasts);
  private readonly transloco = inject(TranslocoService);
  private readonly chat = inject(ChatService);
  private readonly rag = inject(RagService);
  private readonly realtime = inject(RealtimeService);
  private readonly pulse = inject(PulseService);

  // — Indexation initiale —
  readonly initialised = signal(false);
  readonly ingestStep = signal<IngestStep | null>(null);
  readonly documentCount = signal(0);
  readonly processedCount = signal(0);
  readonly isIndexing = computed(() => this.ingestStep() !== null);

  // — Conversations —
  readonly conversations = signal<readonly Conversation[]>([]);
  readonly activeConversationId = signal<string | null>(null);
  readonly activeConversation = computed(
    () => this.conversations().find((c) => c.id === this.activeConversationId()) ?? null,
  );
  /** Le fil affiché découle de la conversation ouverte : aucune copie à resynchroniser. */
  readonly messages = computed<readonly Message[]>(() => this.activeConversation()?.messages ?? []);
  readonly isThinking = signal(false);
  /** Outils invoqués pendant la question en cours, dans l'ordre d'arrivée (voir événements tool_call du flux). */
  readonly liveTrace = signal<readonly TraceEntry[]>([]);
  readonly approved = signal<readonly number[]>([]);
  /** Actions reformulées par l'utilisateur avant validation, par message. */
  readonly editedActions = signal<Record<number, string>>({});
  readonly editingAction = signal<number | null>(null);
  /** Interjections que l'utilisateur a repoussées. */
  readonly deferred = signal<readonly number[]>([]);
  /**
   * Source ouverte dans le panneau de lecture, ou null.
   * Consulter une source ne doit jamais faire quitter la conversation.
   */
  readonly openSource = signal<SourceRef | null>(null);
  /** Pièce jointe (générée ou envoyée) ouverte dans le panneau d'aperçu, ou null — voir attachment-preview. */
  readonly openAttachment = signal<AttachmentOut | null>(null);

  // — Connecteurs — ⚠️ scénarisé, voir docstring de classe.
  readonly connections = signal<readonly Connection[]>(SEED_CONNECTIONS);

  // — Profil —
  readonly profile = signal({
    name: 'Harvey Specter',
    email: 'harvey@pearsonhardman.com',
    role: 'Managing Partner',
  });

  /** Ce que DONNA retient sur l'entreprise — alimenté par les vrais memory_notes du backend. */
  readonly companyMemory = signal<readonly MemoryNote[]>([]);
  readonly isEmpty = computed(() => this.messages().length === 0);

  /** Tiroir flottant (indexation en cours) — ouvert par défaut dès qu'il a quelque chose à montrer, repliable à la main. */
  readonly memoryPanelOpen = signal(true);

  toggleMemoryPanel(): void {
    this.memoryPanelOpen.update((open) => !open);
  }

  /** Popup « Ajouter des documents », accessible depuis le topbar à tout moment (pas seulement à l'onboarding). */
  readonly addDocumentsOpen = signal(false);

  openAddDocuments(): void {
    this.addDocumentsOpen.set(true);
  }

  closeAddDocuments(): void {
    this.addDocumentsOpen.set(false);
  }

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      this.realtime.disconnect();
      this.pulse.disconnect();
    });

    this.realtime.stream.subscribe((event) => {
      switch (event.action) {
        case 'memory_fact_saved':
          this.remember({ text: event.payload.fact });
          this.toasts.push(
            { titleKey: 'workspace.memory.saved', bodyText: event.payload.fact },
            'Saved to memory',
          );
          break;
        case 'donna_question':
          // La question apparaît déjà dans le fil via le flux SSE de la même
          // requête (l'outil ask_user marque le message en cours kind:
          // 'question', voir streamAnswer) — cet événement websocket ne sert
          // qu'à prévenir si un autre onglet/conversation est ouvert.
          this.toasts.push(
            { titleKey: 'workspace.notifications.donnaAsks', bodyText: event.payload.question },
            event.payload.question,
          );
          break;
        case 'rag_ingestion_status':
          this.handleIngestionStatus(event.payload.current);
          break;
      }
    });

    this.pulse.stream.subscribe((event) => {
      if (event.channel === 'reminders') {
        // Toujours notifié (cloche) — en plus, injecté en direct dans le fil
        // si c'est celui actuellement ouvert : le backend l'y a déjà persisté
        // (voir chat/src/tasks.py::_insert_reminder_message), mais sans
        // rechargement l'utilisateur ne le verrait qu'à la réouverture.
        this.toasts.push(
          { titleKey: 'workspace.notifications.pulse.reminder', bodyText: event.data.content },
          event.data.content,
        );
        if (event.data.conversation_id && event.data.conversation_id === this.activeConversationId()) {
          this.pushIntoConversation(event.data.conversation_id, {
            author: 'donna',
            text: `Petit rappel : ${event.data.content}.`,
            kind: 'reminder',
          });
        }
        return;
      }
      this.toasts.push(
        { titleKey: this.pulseTitleKey(event.data.event_type), bodyText: event.data.text },
        event.data.text,
      );
    });

    void this.autoResumeIfReturningUser();
  }

  /**
   * Un utilisateur qui a déjà des conversations n'est pas un nouvel
   * utilisateur : lui remontrer l'onboarding « Let's build your company
   * memory » à chaque rechargement de page cache sa liste de fils derrière
   * un écran qu'il doit fermer à la main à chaque fois. On vérifie donc tôt
   * s'il a un historique réel, et on saute directement dedans si oui.
   */
  private async autoResumeIfReturningUser(): Promise<void> {
    if (this.initialised()) return;
    let list: readonly { id: string; title: string }[];
    try {
      list = await this.chat.listConversations();
    } catch {
      return; // Au pire l'onboarding s'affiche — jamais un écran cassé.
    }
    // L'utilisateur a peut-être déjà cliqué « Initialiser »/« Plus tard »
    // pendant l'attente réseau — ne pas écraser son choix.
    if (this.initialised() || list.length === 0) return;

    this.conversations.set(list.map((c) => ({ id: c.id, title: c.title, messages: [] })));
    this.initialised.set(true);
    this.realtime.connect();
    this.pulse.connect();
  }

  /** Catégorise l'event_type xpulse (voir bridge/handlers.py, bridge/billing.py) en clé de titre de toast. */
  private pulseTitleKey(eventType: string): string {
    if (eventType.startsWith('security.')) return 'workspace.notifications.pulse.security';
    if (
      eventType.startsWith('license.') ||
      eventType.startsWith('payment.') ||
      eventType.startsWith('subscription.') ||
      eventType.startsWith('invoice.')
    ) {
      return 'workspace.notifications.pulse.billing';
    }
    if (eventType.startsWith('tenant.')) return 'workspace.notifications.pulse.tenant';
    return 'workspace.notifications.pulse.generic';
  }

  /** Position d'une étape d'indexation : passée, en cours, ou à venir. */
  stepState(step: IngestStep): 'done' | 'active' | 'pending' {
    const current = this.ingestStep();
    if (current === null) return 'pending';
    const index = INGEST_STEPS.indexOf(step);
    const currentIndex = INGEST_STEPS.indexOf(current);
    if (index < currentIndex) return 'done';
    return index === currentIndex ? 'active' : 'pending';
  }

  /** Dépose des fichiers à indexer, avant le lancement (voir initialise). */
  addDocuments(files: File[]): void {
    if (files.length === 0 || this.isIndexing()) return;
    this.stagedFiles.push(...files);
    this.documentCount.update((total) => total + files.length);
  }

  /**
   * Ajout de documents une fois l'espace déjà en route (popup « Ajouter des
   * documents », voir add-documents-dialog) — même ingestion réelle que
   * l'onboarding (runRealIngest), juste sans passer par `initialise()`.
   */
  uploadDocuments(files: readonly File[]): void {
    if (files.length === 0) return;
    this.closeAddDocuments();
    this.documentCount.update((total) => total + files.length);
    void this.runRealIngest([...files]);
  }

  /**
   * Ouvre l'espace ET lance l'indexation des fichiers déposés, sans attendre
   * la fin : sur un fonds documentaire d'entreprise, ce serait plusieurs
   * minutes d'écran bloqué. L'utilisateur discute pendant que la mémoire se
   * construit ; le rail droit montre l'avancement (voir rag_ingestion_status).
   */
  initialise(): void {
    if (this.initialised()) return;
    this.initialised.set(true);
    this.realtime.connect();
    this.pulse.connect();
    void this.loadConversations();

    if (this.stagedFiles.length > 0) {
      const files = this.stagedFiles.splice(0);
      void this.runRealIngest(files);
    }
  }

  private async loadConversations(): Promise<void> {
    try {
      const list = await this.chat.listConversations();
      this.conversations.set(list.map((c) => ({ id: c.id, title: c.title, messages: [] })));
    } catch {
      // Liste vide plutôt qu'un écran cassé — l'utilisateur peut toujours écrire.
    }
  }

  private async runRealIngest(files: File[]): Promise<void> {
    this.ingestStep.set('reading');
    this.processedCount.set(0);
    let uploaded = 0;

    for (const file of files) {
      try {
        const doc = await this.rag.uploadDocument(file);
        this.pendingIngestDocIds.add(doc.id);
      } catch {
        this.toasts.push(
          { titleKey: 'workspace.setup.uploadFailed', bodyText: file.name },
          'Upload failed',
        );
      }
      uploaded++;
      this.processedCount.set(uploaded);
    }

    // "extracting" n'a pas de granularité propre côté backend (extraction +
    // découpage + embedding sont une seule étape opaque) — on la traverse
    // immédiatement, "indexing" reste actif jusqu'à confirmation par websocket.
    this.ingestStep.set(this.pendingIngestDocIds.size > 0 ? 'indexing' : null);
  }

  private handleIngestionStatus(current: { document_id: string; status: string } | null): void {
    if (!current || !this.pendingIngestDocIds.has(current.document_id)) return;
    if (current.status !== 'done' && current.status !== 'failed') return;

    this.pendingIngestDocIds.delete(current.document_id);
    if (this.pendingIngestDocIds.size === 0) this.ingestStep.set(null);
  }

  /** Entre dans l'espace sans indexer — la mémoire se construira plus tard. */
  skipSetup(): void {
    this.ingestStep.set(null);
    this.initialised.set(true);
    this.realtime.connect();
    this.pulse.connect();
    void this.loadConversations();
  }

  send(text: string, files: readonly File[] = []): void {
    const question = text.trim();
    if ((!question && files.length === 0) || this.isThinking() || !this.initialised()) return;

    const localAttachments = files.map((file) => this.localAttachment(file));
    this.pushMessage({
      author: 'user',
      text: question,
      attachments: localAttachments.length ? localAttachments : undefined,
    });
    this.isThinking.set(true);
    this.liveTrace.set([]);

    if (files.length > 0) {
      void this.sendWithUpload(question, files);
    } else {
      void this.streamAnswer(question);
    }
  }

  /**
   * Aperçu immédiat du fichier qu'on vient de joindre, via une URL objet
   * locale — le serveur ne renvoie pas les pièces jointes UPLOADÉES par
   * l'utilisateur dans ChatResponse (seulement celles que DONNA génère, voir
   * chat_routes.py::upload), donc pas d'id/URL backend avant rechargement.
   */
  private localAttachment(file: File): AttachmentOut {
    return {
      id: `local-${this.nextId++}`,
      kind: file.type.startsWith('image/') ? 'image' : 'document',
      original_name: file.name,
      mime_type: file.type || 'application/octet-stream',
      file_url: URL.createObjectURL(file),
      created_at: new Date().toISOString(),
    };
  }

  /** Message avec fichier(s) joint(s) — endpoint non-streaming dédié, voir ChatService.upload. */
  private async sendWithUpload(question: string, files: readonly File[]): Promise<void> {
    const conversationIdAtStart = this.activeConversationId();
    const isRealId = conversationIdAtStart !== null && !conversationIdAtStart.startsWith('local-');

    try {
      const response = await this.chat.upload(
        question,
        files,
        isRealId ? conversationIdAtStart : null,
      );
      this.reconcileConversationId(response.conversation_id);
      this.pushMessage({
        author: 'donna',
        text: response.reply,
        sources: response.sources.length ? response.sources.map(sourceRefFromOut) : undefined,
        attachments: response.attachments.length ? response.attachments : undefined,
      });
      for (const fact of response.memory_notes) {
        this.remember({ text: fact });
        this.toasts.push(
          { titleKey: 'workspace.memory.saved', bodyText: fact },
          'Saved to memory',
        );
      }
    } catch (err) {
      // Contrairement au flux SSE (toujours un message générique — l'erreur y
      // est déjà une contrainte connue, ex. limite de débit), /upload peut
      // rejeter pour une raison propre au fichier lui-même (ex. « aucun
      // contenu exploitable dans l'archive zip ») — un détail utile que
      // l'utilisateur doit voir, pas juste « réessayez ».
      const detail = uploadErrorDetail(err);
      if (detail) {
        this.toasts.push({ titleKey: 'workspace.errors.uploadFailed', bodyText: detail }, detail);
      } else {
        this.toasts.push({ titleKey: 'workspace.errors.chatFailed' }, 'Chat failed');
      }
    } finally {
      this.isThinking.set(false);
    }
  }

  /** Répond à une option de clarification comme à une question normale. */
  chooseOption(labelKey: string): void {
    if (this.isThinking()) return;
    this.send(this.transloco.translate(labelKey));
  }

  private async streamAnswer(question: string): Promise<void> {
    const conversationIdAtStart = this.activeConversationId();
    const isRealId = conversationIdAtStart !== null && !conversationIdAtStart.startsWith('local-');
    let started = false;
    // ask_user est signalé EN PLUS du texte normal (voir tools.py::_ask_user) —
    // jamais à la place : on ne l'ajoute donc pas à liveTrace comme un outil
    // de recherche, on s'en sert juste pour distinguer visuellement le
    // message qui va suivre.
    let pendingQuestion = false;
    let pendingOptions: readonly string[] = [];

    try {
      for await (const event of this.chat.sendStream(
        question,
        isRealId ? conversationIdAtStart : null,
      )) {
        switch (event.type) {
          case 'start':
            this.reconcileConversationId(event.conversationId);
            break;
          case 'delta':
            if (!started) {
              started = true;
              this.isThinking.set(false);
              this.pushMessage({
                author: 'donna',
                text: '',
                kind: pendingQuestion ? 'question' : undefined,
                options: pendingOptions.length ? pendingOptions : undefined,
              });
            }
            this.appendToLastMessage(event.text);
            break;
          case 'tool_call':
            if (event.name === 'ask_user') {
              pendingQuestion = true;
              const raw = event.arguments['options'];
              pendingOptions = Array.isArray(raw)
                ? raw.filter((o): o is string => typeof o === 'string')
                : [];
            } else {
              this.liveTrace.update((list) => [...list, { name: event.name, result: event.result }]);
            }
            break;
          case 'provider_fallback':
            // Le cloud (Groq/Anthropic/...) est indisponible (rate limit,
            // clé, réseau) — Donna a basculé sur le modèle local sans
            // interrompre la réponse. Visible dans la trace, pas un toast :
            // ça ne casse rien pour l'utilisateur, juste plus lent/moins fin.
            this.liveTrace.update((list) => [
              ...list,
              { name: 'provider_fallback', result: event.reason },
            ]);
            break;
          case 'done': {
            if (event.sources.length > 0) {
              this.setLastMessageSources(event.sources.map(sourceRefFromOut));
            }
            if (event.attachments.length > 0) {
              this.setLastMessageAttachments(event.attachments);
            }
            for (const fact of event.memoryNotes) {
              this.remember({ text: fact });
              this.toasts.push(
                { titleKey: 'workspace.memory.saved', bodyText: fact },
                'Saved to memory',
              );
            }
            break;
          }
          case 'error':
            this.toasts.push({ titleKey: 'workspace.errors.chatFailed' }, 'Chat failed');
            break;
        }
      }
    } catch {
      this.toasts.push({ titleKey: 'workspace.errors.chatFailed' }, 'Chat failed');
    } finally {
      this.isThinking.set(false);
      this.liveTrace.set([]);
    }
  }

  /** Bascule un connecteur. ⚠️ Affichage seul — voir docstring de classe. */
  toggleConnection(key: string): void {
    this.connections.update((list) =>
      list.map((c) => (c.key === key ? { ...c, connected: !c.connected } : c)),
    );
  }

  updateProfile(profile: { name: string; email: string; role: string }): void {
    this.profile.set(profile);
    this.toasts.push({ titleKey: 'workspace.profile.saved' }, 'Profile updated');
  }

  /** Efface la mémoire indexée. Irréversible, donc annoncé comme tel. */
  purgeMemory(): void {
    this.ingestStep.set(null);
    this.documentCount.set(0);
    this.processedCount.set(0);
    this.toasts.push({ titleKey: 'workspace.settings.memory.purged' }, 'Memory erased');
  }

  readSource(source: SourceRef): void {
    // Un seul panneau latéral à la fois — voir viewAttachment.
    this.openAttachment.set(null);
    this.openSource.set(source);
  }

  closeSource(): void {
    this.openSource.set(null);
  }

  viewAttachment(attachment: AttachmentOut): void {
    // Idem dans l'autre sens : ouvrir une pièce jointe ferme la source en cours.
    this.openSource.set(null);
    this.openAttachment.set(attachment);
  }

  closeAttachment(): void {
    this.openAttachment.set(null);
  }

  defer(id: number): void {
    this.deferred.update((list) => (list.includes(id) ? list : [...list, id]));
  }

  isDeferred(id: number): boolean {
    return this.deferred().includes(id);
  }

  /** Ouvre un fil existant — récupère son vrai contenu si pas déjà en mémoire. */
  openConversation(id: string): void {
    this.isThinking.set(false);
    this.liveTrace.set([]);
    this.activeConversationId.set(id);

    const existing = this.conversations().find((c) => c.id === id);
    if (existing && existing.messages.length > 0) return;

    void this.chat.getMessages(id).then((history) => {
      const messages: Message[] = history.map((m) => ({
        id: this.nextId++,
        author: m.role === 'user' ? 'user' : 'donna',
        text: m.content,
        attachments: m.attachments,
      }));
      this.conversations.update((list) =>
        list.map((c) => (c.id === id ? { ...c, messages } : c)),
      );
    });
  }

  /** Insère un message dans UN fil précis, actif ou non — voir l'injection des rappels ci-dessus. */
  private pushIntoConversation(conversationId: string, message: Omit<Message, 'id'>): void {
    const entry: Message = { ...message, id: this.nextId++ };
    this.conversations.update((list) =>
      list.map((c) => (c.id === conversationId ? { ...c, messages: [...c.messages, entry] } : c)),
    );
  }

  private pushMessage(message: Omit<Message, 'id'>): Message {
    const entry: Message = { ...message, id: this.nextId++ };
    const target = this.activeConversationId();

    // Aucun fil ouvert : la première question en crée un local, réconcilié
    // avec l'id réel dès l'événement "start" du flux (voir streamAnswer).
    if (target === null) {
      const conversation: Conversation = {
        id: `local-${this.nextId++}`,
        title: message.text?.slice(0, 60),
        messages: [entry],
      };
      this.conversations.update((list) => [conversation, ...list]);
      this.activeConversationId.set(conversation.id);
      return entry;
    }

    this.conversations.update((list) =>
      list.map((c) => (c.id === target ? { ...c, messages: [...c.messages, entry] } : c)),
    );
    return entry;
  }

  /** Remplace l'id local provisoire d'une conversation par le vrai id backend. */
  private reconcileConversationId(realId: string): void {
    const current = this.activeConversationId();
    if (current === realId) return;
    if (current === null || !current.startsWith('local-')) {
      this.activeConversationId.set(realId);
      return;
    }
    this.conversations.update((list) =>
      list.map((c) => (c.id === current ? { ...c, id: realId } : c)),
    );
    this.activeConversationId.set(realId);
  }

  private appendToLastMessage(delta: string): void {
    this.updateLastMessage((m) => ({ text: (m.text ?? '') + delta }));
  }

  private setLastMessageSources(sources: readonly SourceRef[]): void {
    this.updateLastMessage(() => ({ sources }));
  }

  private setLastMessageAttachments(attachments: readonly AttachmentOut[]): void {
    this.updateLastMessage(() => ({ attachments }));
  }

  private updateLastMessage(patch: (message: Message) => Partial<Message>): void {
    const target = this.activeConversationId();
    if (target === null) return;
    this.conversations.update((list) =>
      list.map((c) => {
        if (c.id !== target || c.messages.length === 0) return c;
        const messages = [...c.messages];
        const last = messages[messages.length - 1];
        messages[messages.length - 1] = { ...last, ...patch(last) };
        return { ...c, messages };
      }),
    );
  }

  startEditingAction(id: number): void {
    this.editingAction.set(id);
  }

  cancelEditingAction(): void {
    this.editingAction.set(null);
  }

  /** Valide l'action après reformulation : c'est le texte corrigé qui fait foi. */
  saveAction(id: number, text: string): void {
    const amended = text.trim();
    if (amended) this.editedActions.update((map) => ({ ...map, [id]: amended }));
    this.editingAction.set(null);
    this.approve(id);
  }

  editedAction(id: number): string | null {
    return this.editedActions()[id] ?? null;
  }

  /** Ouvre le brouillon d'ordre du jour préparé par DONNA. ⚠️ Démo (donna-interjection) — traduit à la volée en SourceRef pour rester compatible avec le panneau de lecture réel. */
  readAgenda(): void {
    const base = 'workspace.research.entries.agenda';
    this.openSource.set({
      kind: 'document',
      id: 'agenda-demo',
      title: this.transloco.translate(`${base}.title`),
      excerpt: this.transloco.translate(`${base}.excerpt`),
      url: this.transloco.translate(`${base}.url`),
      meta: this.transloco.translate(`${base}.meta`),
    });
  }

  /** Retient un fait — alimenté par memory_fact_saved (websocket) et memory_notes (réponses de chat). */
  remember(note: Omit<MemoryNote, 'id'>): void {
    const entry: MemoryNote = { ...note, id: this.nextId++ };
    this.companyMemory.update((list) => [entry, ...list]);
  }

  approve(id: number): void {
    this.approved.update((list) => (list.includes(id) ? list : [...list, id]));
  }

  isApproved(id: number): boolean {
    return this.approved().includes(id);
  }

  /** Nouveau fil : la mémoire indexée et les fils passés sont conservés. */
  resetConversation(): void {
    this.isThinking.set(false);
    this.liveTrace.set([]);
    this.activeConversationId.set(null);
  }

  /** Titre d'un fil : clé de traduction pour les exemples, texte sinon. */
  conversationTitle(conversation: Conversation): { key?: string; text?: string } {
    return conversation.titleKey
      ? { key: conversation.titleKey }
      : { text: conversation.title || '' };
  }

}
