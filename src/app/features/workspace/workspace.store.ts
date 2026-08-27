import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { TranslocoService } from '@jsverse/transloco';
import { Toasts } from '../../core/notifications/toasts';

/** Étapes de l'indexation initiale. L'ordre du tableau EST le déroulé. */
export const INGEST_STEPS = ['reading', 'extracting', 'indexing'] as const;
export type IngestStep = (typeof INGEST_STEPS)[number];

/** Une source consultée pendant la recherche, telle qu'elle s'affiche dans le fil. */
export interface TraceEntry {
  readonly kind: 'document' | 'web';
  /** Suffixe de clé sous `workspace.research.entries`. */
  readonly key: string;
}

/** Le déroulé de recherche rejoué pour la démonstration. */
const TRACE: readonly TraceEntry[] = [
  { kind: 'document', key: 'one' },
  { kind: 'document', key: 'two' },
  { kind: 'web', key: 'three' },
  { kind: 'document', key: 'four' },
];

/**
 * Un dossier client.
 *
 * Un projet CLASSE des documents, il ne les cloisonne pas : tout part dans le
 * même index. DONNA peut donc citer une pièce d'un autre dossier — c'est voulu.
 */
/** Un fait que DONNA a retenu. Sa portée dit qui peut s'en servir. */
export interface MemoryNote {
  readonly id: number;
  /** Clé de traduction pour les faits d'exemple. */
  readonly textKey?: string;
  readonly text?: string;
}

/**
 * Un dossier client.
 *
 * Ses DOCUMENTS rejoignent la base de connaissances générale : DONNA les
 * interroge depuis n'importe quelle conversation. Sa MÉMOIRE, elle, lui est
 * propre — ce qu'elle a retenu de ce client ne fuite pas vers un autre dossier.
 */
export interface Project {
  readonly id: number;
  readonly name: string;
  readonly client: string;
  readonly documents: number;
  readonly memory: readonly MemoryNote[];
}

/** Un outil branché. Le couper doit couper l'accès, pas seulement l'affichage. */
export interface Connection {
  readonly key: string;
  readonly icon: string;
  readonly connected: boolean;
}

/** Un fil. Ouvrir une conversation ancienne doit rendre son contenu, pas un écran vide. */
export interface Conversation {
  readonly id: number;
  /** Clé de traduction pour les fils d'exemple. */
  readonly titleKey?: string;
  /** Titre déduit de la première question, pour les fils créés à l'usage. */
  readonly title?: string;
  readonly messages: readonly Message[];
}

export interface Message {
  readonly id: number;
  readonly author: 'user' | 'donna';
  /** Texte saisi par l'utilisateur. */
  readonly text?: string;
  /** Clé de traduction, pour les réponses scénarisées de DONNA. */
  readonly textKey?: string;
  readonly sources?: readonly string[];
  /** Action proposée, en attente de validation. */
  readonly actionKey?: string;
  /** Sources consultées pour bâtir cette réponse. */
  readonly trace?: readonly TraceEntry[];
  /**
   * Message que DONNA amène d'elle-même, sans qu'on l'ait sollicitée.
   * Ce n'est pas un rappel : c'est une arrivée, avec le travail déjà fait.
   */
  readonly kind?: 'interjection' | 'clarification';
  /** Réponses proposées, quand DONNA demande une précision. */
  readonly optionKeys?: readonly string[];
}

// Durées du scénario de démonstration, en millisecondes.
const INGEST_DURATION = 1200;
const THINKING_DURATION = 1600;
const DOCUMENTS_PER_STEP = 47;
// Délai avant que DONNA revienne d'elle-même. Raccourci pour la démonstration ;
// dans le produit, c'est elle qui juge le bon moment.
const INTERJECTION_DELAY = 5000;
// Entités connues : si l'une est nommée, la demande n'est plus ambiguë.
const KNOWN_SUBJECTS = ['meridian', 'halloway', 'kestrel'];
const SEED_CONVERSATIONS: readonly Conversation[] = ['one', 'two', 'three'].map((key, i) => ({
  id: -10 - i,
  titleKey: `workspace.conversations.${key}.title`,
  messages: [
    { id: -100 - i * 2, author: 'user', textKey: `workspace.conversations.${key}.question` },
    { id: -101 - i * 2, author: 'donna', textKey: `workspace.conversations.${key}.answer` },
  ],
}));

const SEED_CONNECTIONS: readonly Connection[] = [
  { key: 'drive', icon: 'folder', connected: true },
  { key: 'calendar', icon: 'calendar-days', connected: true },
  { key: 'gmail', icon: 'mail', connected: true },
  { key: 'slack', icon: 'message-square', connected: false },
];

const seedMemory = (client: string, keys: readonly string[], from: number): MemoryNote[] =>
  keys.map((key, i) => ({
    id: from - i,
    textKey: `workspace.projects.seedMemory.${client}.${key}`,
  }));

const SEED_PROJECTS: readonly Project[] = [
  {
    id: -1,
    name: 'workspace.projects.seed.meridian',
    client: 'Meridian Legal',
    documents: 34,
    memory: seedMemory('meridian', ['one', 'two', 'three'], -200),
  },
  {
    id: -2,
    name: 'workspace.projects.seed.halloway',
    client: 'Halloway Group',
    documents: 18,
    memory: seedMemory('halloway', ['one', 'two'], -210),
  },
  {
    id: -3,
    name: 'workspace.projects.seed.kestrel',
    client: 'Kestrel Partners',
    documents: 61,
    memory: seedMemory('kestrel', ['one'], -220),
  },
];

const CLARIFY_OPTIONS = [
  'workspace.clarify.options.meridian',
  'workspace.clarify.options.halloway',
  'workspace.clarify.options.all',
] as const;

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
 * ⚠️ Aucun backend n'est branché : les deux déroulés sont scénarisés.
 */
@Injectable()
export class WorkspaceStore {
  /**
   * Deux minuteurs SÉPARÉS, et c'est structurel : l'indexation et la
   * conversation tournent en parallèle. Une liste commune faisait qu'une
   * question posée pendant l'indexation effaçait le minuteur de celle-ci et
   * la laissait figée à jamais.
   */
  private ingestTimer?: ReturnType<typeof setTimeout>;
  private chatTimers: ReturnType<typeof setTimeout>[] = [];
  private nextId = 1;

  private readonly toasts = inject(Toasts);
  private readonly transloco = inject(TranslocoService);

  // — Indexation initiale —
  readonly initialised = signal(false);
  readonly ingestStep = signal<IngestStep | null>(null);
  readonly documentCount = signal(0);
  readonly processedCount = signal(0);
  readonly isIndexing = computed(() => this.ingestStep() !== null);

  // — Conversations —
  readonly conversations = signal<readonly Conversation[]>(SEED_CONVERSATIONS);
  readonly activeConversationId = signal<number | null>(null);
  readonly activeConversation = computed(
    () => this.conversations().find((c) => c.id === this.activeConversationId()) ?? null,
  );
  /** Le fil affiché découle de la conversation ouverte : aucune copie à resynchroniser. */
  readonly messages = computed<readonly Message[]>(() => this.activeConversation()?.messages ?? []);
  readonly isThinking = signal(false);
  /** Sources déjà consultées pour la question en cours, dans l'ordre d'arrivée. */
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
  readonly openSource = signal<TraceEntry | null>(null);

  // — Connecteurs —
  readonly connections = signal<readonly Connection[]>(SEED_CONNECTIONS);

  // — Profil —
  readonly profile = signal({
    name: 'Harvey Specter',
    email: 'harvey@pearsonhardman.com',
    role: 'Managing Partner',
  });

  // — Projets —
  readonly projects = signal<readonly Project[]>(SEED_PROJECTS);
  /** Ce que DONNA retient hors de tout dossier : valable partout. */
  readonly companyMemory = signal<readonly MemoryNote[]>([]);
  readonly activeProjectId = signal<number | null>(null);
  readonly activeProject = computed(
    () => this.projects().find((p) => p.id === this.activeProjectId()) ?? null,
  );
  readonly isEmpty = computed(() => this.messages().length === 0);

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      clearTimeout(this.ingestTimer);
      this.clearChatTimers();
    });
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

  /** Dépose des documents à indexer, avant le lancement. */
  addDocuments(count: number): void {
    if (count <= 0 || this.isIndexing()) return;
    this.documentCount.update((total) => total + count);
  }

  /**
   * Lance l'indexation ET ouvre l'espace dans la foulée.
   *
   * On n'attend PAS la fin : sur un fonds documentaire d'entreprise, cela
   * signifierait plusieurs minutes d'écran bloqué. L'utilisateur discute
   * pendant que la mémoire se construit ; le rail droit montre l'avancement.
   */
  initialise(): void {
    if (this.isIndexing() || this.initialised()) return;
    this.initialised.set(true);
    this.startIndexing();
  }

  /** Relance le déroulé d'indexation, quelle qu'en soit l'origine. */
  private startIndexing(): void {
    clearTimeout(this.ingestTimer);
    this.processedCount.set(0);
    this.runIngestStep(0);
  }

  /** Entre dans l'espace sans indexer — la mémoire se construira plus tard. */
  skipSetup(): void {
    clearTimeout(this.ingestTimer);
    this.ingestStep.set(null);
    this.initialised.set(true);
  }

  send(text: string): void {
    const question = text.trim();
    if (!question || this.isThinking() || !this.initialised()) return;

    // On ne touche PAS au minuteur d'indexation : elle continue en fond.
    this.clearChatTimers();
    this.pushMessage({ author: 'user', text: question });
    this.isThinking.set(true);
    this.liveTrace.set([]);

    // Demande de rappel : DONNA ne cherche pas, elle prend note — puis revient.
    if (this.looksLikeReminder(question)) {
      this.chatTimers.push(setTimeout(() => this.confirmReminder(), 900));
      return;
    }

    // Demande ambiguë : elle demande avant de répondre, plutôt que de deviner.
    if (this.looksAmbiguous(question)) {
      this.chatTimers.push(setTimeout(() => this.askForPrecision(), 900));
      return;
    }

    this.runAnswer();
  }

  /** Réponse à une demande de précision : on la traite comme une question. */
  chooseOption(labelKey: string): void {
    if (this.isThinking()) return;

    this.clearChatTimers();
    this.pushMessage({ author: 'user', textKey: labelKey });
    this.isThinking.set(true);
    this.liveTrace.set([]);
    this.runAnswer();
  }

  private runAnswer(): void {
    // Les sources apparaissent une à une : on voit DONNA chercher, pas attendre.
    const interval = THINKING_DURATION / (TRACE.length + 1);
    TRACE.forEach((entry, index) => {
      this.chatTimers.push(
        setTimeout(() => this.liveTrace.update((list) => [...list, entry]), interval * (index + 1)),
      );
    });

    this.chatTimers.push(
      setTimeout(() => {
        this.isThinking.set(false);
        this.pushMessage({
          author: 'donna',
          textKey: 'workspace.demo.answer',
          sources: ['workspace.connections.drive', 'workspace.connections.calendar'],
          actionKey: 'workspace.demo.action',
          trace: TRACE,
        });
        this.liveTrace.set([]);

        // DONNA retient ce qu'elle vient d'établir : on le signale, sans bloquer.
        // Ce qu'elle vient d'établir est retenu — et on dit OÙ.
        this.remember({ textKey: 'workspace.memory.detail' });
        const project = this.activeProject();
        this.toasts.push(
          {
            titleKey: project
              ? 'workspace.projects.memory.savedToProject'
              : 'workspace.projects.memory.savedToCompany',
            titleParams: project ? { client: project.client } : undefined,
            bodyKey: 'workspace.memory.detail',
            linkLabelKey: 'workspace.memory.view',
            url: 'https://drive.google.com/file/meridian-msa',
          },
          'Saved to memory',
        );
      }, THINKING_DURATION),
    );
  }

  /**
   * Reconnaissance d'intention volontairement rudimentaire : la démonstration
   * n'a pas de modèle derrière elle. C'est le seul endroit à remplacer.
   */
  private looksLikeReminder(question: string): boolean {
    const trigger = this.transloco.translate('workspace.reminder.trigger').toLowerCase();
    return question.toLowerCase().includes(trigger);
  }

  /** Le sujet est évoqué, mais aucune partie n'est nommée : il faut trancher. */
  private looksAmbiguous(question: string): boolean {
    const asked = question.toLowerCase();
    const subject = this.transloco.translate('workspace.clarify.trigger').toLowerCase();
    return asked.includes(subject) && !KNOWN_SUBJECTS.some((name) => asked.includes(name));
  }

  private askForPrecision(): void {
    this.isThinking.set(false);
    this.pushMessage({
      author: 'donna',
      kind: 'clarification',
      textKey: 'workspace.clarify.question',
      optionKeys: CLARIFY_OPTIONS,
    });
  }

  private confirmReminder(): void {
    this.isThinking.set(false);
    this.pushMessage({ author: 'donna', textKey: 'workspace.reminder.confirm' });

    // Elle ne prévient pas qu'elle va revenir. Elle revient.
    this.chatTimers.push(
      setTimeout(() => {
        this.pushMessage({ author: 'donna', kind: 'interjection' });
      }, INTERJECTION_DELAY),
    );
  }

  /**
   * Crée un dossier et verse ses documents dans la mémoire commune.
   * L'indexation reste en arrière-plan : on peut travailler pendant.
   */
  createProject(name: string, client: string, documents: number): Project | null {
    const label = name.trim();
    if (!label) return null;

    const project: Project = {
      id: this.nextId++,
      name: label,
      client: client.trim(),
      documents,
      // Un dossier neuf part sans mémoire : elle se constitue à l'usage.
      memory: [],
    };
    this.projects.update((list) => [project, ...list]);
    this.activeProjectId.set(project.id);

    if (documents > 0) {
      this.documentCount.update((total) => total + documents);
      this.startIndexing();
    }

    this.toasts.push(
      { titleKey: 'workspace.projects.created', bodyKey: 'workspace.projects.indexing' },
      'Project created',
    );
    return project;
  }

  /** Bascule un connecteur. C'est l'action qui donne son sens à la promesse. */
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
    clearTimeout(this.ingestTimer);
    this.ingestStep.set(null);
    this.documentCount.set(0);
    this.processedCount.set(0);
    this.toasts.push({ titleKey: 'workspace.settings.memory.purged' }, 'Memory erased');
  }

  selectProject(id: number | null): void {
    this.activeProjectId.set(id);
  }

  /** Le nom d'un projet peut être une clé de traduction (jeu d'exemple) ou un texte saisi. */
  isProjectNameKey(project: Project): boolean {
    return project.id < 0;
  }

  readSource(entry: TraceEntry): void {
    this.openSource.set(entry);
  }

  closeSource(): void {
    this.openSource.set(null);
  }

  defer(id: number): void {
    this.deferred.update((list) => (list.includes(id) ? list : [...list, id]));
  }

  isDeferred(id: number): boolean {
    return this.deferred().includes(id);
  }

  /** Ouvre un fil existant. Son contenu revient tel qu'il était. */
  openConversation(id: number): void {
    this.clearChatTimers();
    this.isThinking.set(false);
    this.liveTrace.set([]);
    this.activeConversationId.set(id);
  }

  private pushMessage(message: Omit<Message, 'id'>): void {
    const entry: Message = { ...message, id: this.nextId++ };
    let target = this.activeConversationId();

    // Aucun fil ouvert : la première question en crée un, titré par elle-même.
    if (target === null) {
      const conversation: Conversation = {
        id: this.nextId++,
        title: message.text?.slice(0, 60),
        messages: [entry],
      };
      this.conversations.update((list) => [conversation, ...list]);
      this.activeConversationId.set(conversation.id);
      return;
    }

    this.conversations.update((list) =>
      list.map((c) => (c.id === target ? { ...c, messages: [...c.messages, entry] } : c)),
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

  /** Ouvre le brouillon d'ordre du jour préparé par DONNA. */
  readAgenda(): void {
    this.openSource.set({ kind: 'document', key: 'agenda' });
  }

  /**
   * Retient un fait. La portée découle du contexte, pas d'un réglage : ouvert
   * dans un dossier, DONNA le range chez ce client ; sinon, en mémoire commune.
   */
  remember(note: Omit<MemoryNote, 'id'>): void {
    const entry: MemoryNote = { ...note, id: this.nextId++ };
    const project = this.activeProject();

    if (project) {
      this.projects.update((list) =>
        list.map((p) => (p.id === project.id ? { ...p, memory: [entry, ...p.memory] } : p)),
      );
      return;
    }

    this.companyMemory.update((list) => [entry, ...list]);
  }

  approve(id: number): void {
    this.approved.update((list) => (list.includes(id) ? list : [...list, id]));
  }

  isApproved(id: number): boolean {
    return this.approved().includes(id);
  }

  /** Nouvelle conversation : la mémoire indexée, elle, est conservée. */
  /** Nouveau fil : la mémoire indexée et les fils passés sont conservés. */
  resetConversation(): void {
    this.clearChatTimers();
    this.activeConversationId.set(null);
    this.isThinking.set(false);
    this.liveTrace.set([]);
  }

  /** Titre d'un fil : clé de traduction pour les exemples, texte sinon. */
  conversationTitle(conversation: Conversation): { key?: string; text?: string } {
    return conversation.titleKey
      ? { key: conversation.titleKey }
      : { text: conversation.title || '' };
  }

  private clearChatTimers(): void {
    for (const timer of this.chatTimers) clearTimeout(timer);
    this.chatTimers = [];
  }

  private runIngestStep(index: number): void {
    if (index >= INGEST_STEPS.length) {
      this.ingestStep.set(null);
      return;
    }

    this.ingestStep.set(INGEST_STEPS[index]);
    this.processedCount.set(DOCUMENTS_PER_STEP * (index + 1));
    this.ingestTimer = setTimeout(() => this.runIngestStep(index + 1), INGEST_DURATION);
  }
}
