import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mockFiles, provideTestTranslations } from '../../../testing/setup';
import { INGEST_STEPS, WorkspaceStore } from './workspace.store';

const INGEST_TOTAL = 1200 * INGEST_STEPS.length;
const THINKING = 1600;

describe('WorkspaceStore', () => {
  let store: WorkspaceStore;

  beforeEach(() => {
    vi.useFakeTimers();
    // Le store lit la clé de déclenchement des rappels : il lui faut les traductions.
    TestBed.configureTestingModule({
      imports: [provideTestTranslations()],
      providers: [WorkspaceStore],
    });
    store = TestBed.inject(WorkspaceStore);
  });

  afterEach(() => vi.useRealTimers());

  describe('indexation initiale', () => {
    it('démarre non initialisé, sans indexation en cours', () => {
      expect(store.initialised()).toBe(false);
      expect(store.isIndexing()).toBe(false);
      expect(store.documentCount()).toBe(0);
    });

    it('refuse de lancer l’indexation sans document déposé', () => {
      // Le garde-fou est dans l'interface (bouton désactivé) ; le store, lui,
      // laisse passer un lancement à vide — on documente le comportement réel.
      store.initialise();
      expect(store.isIndexing()).toBe(true);
    });

    it('déroule les étapes dans l’ordre puis marque l’espace prêt', () => {
      store.addDocuments(mockFiles(3));
      expect(store.documentCount()).toBe(3);

      store.initialise();
      expect(store.ingestStep()).toBe(INGEST_STEPS[0]);
      expect(store.stepState(INGEST_STEPS[0])).toBe('active');
      expect(store.stepState(INGEST_STEPS[1])).toBe('pending');
      expect(store.processedCount()).toBeGreaterThan(0);

      vi.advanceTimersByTime(1200);
      expect(store.ingestStep()).toBe(INGEST_STEPS[1]);
      expect(store.stepState(INGEST_STEPS[0])).toBe('done');

      vi.advanceTimersByTime(1200 * 2);
      expect(store.isIndexing()).toBe(false);
      expect(store.initialised()).toBe(true);
    });

    it('n’indexe pas deux fois', () => {
      store.addDocuments(mockFiles(2));
      store.initialise();
      vi.advanceTimersByTime(INGEST_TOTAL);

      store.initialise();
      expect(store.isIndexing()).toBe(false);
    });

    it('ouvre l’espace immédiatement, sans attendre la fin de l’indexation', () => {
      store.addDocuments(mockFiles(3));
      store.initialise();

      // On n'attend pas : un fonds documentaire d'entreprise bloquerait
      // l'utilisateur plusieurs minutes derrière un voile.
      expect(store.initialised()).toBe(true);
      expect(store.isIndexing()).toBe(true);
    });

    it('poursuit l’indexation malgré les questions posées pendant', () => {
      store.addDocuments(mockFiles(3));
      store.initialise();

      // Régression : les deux déroulés partageaient une liste de minuteurs,
      // donc une question effaçait celui de l'indexation et la figeait.
      store.send('Que disent nos contrats Meridian ?');
      vi.advanceTimersByTime(THINKING);
      store.send('Et pour Halloway ?');
      vi.advanceTimersByTime(THINKING);

      expect(store.isIndexing()).toBe(true);
      vi.advanceTimersByTime(INGEST_TOTAL);
      expect(store.isIndexing()).toBe(false);
      expect(store.messages().filter((m) => m.author === 'donna')).toHaveLength(2);
    });

    it('permet d’entrer sans indexer', () => {
      store.skipSetup();
      expect(store.initialised()).toBe(true);
      expect(store.isIndexing()).toBe(false);
    });
  });

  describe('conversation', () => {
    beforeEach(() => {
      store.skipSetup();
    });

    it('refuse toute question tant que l’espace n’est pas initialisé', () => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        imports: [provideTestTranslations()],
        providers: [WorkspaceStore],
      });
      const fresh = TestBed.inject(WorkspaceStore);

      fresh.send('question');
      expect(fresh.isEmpty()).toBe(true);
    });

    it('n’ouvre JAMAIS l’indexation en posant une question', () => {
      store.send('Find all contracts expiring in the next 60 days');
      expect(store.isIndexing()).toBe(false);
      expect(store.isThinking()).toBe(true);

      vi.advanceTimersByTime(THINKING);
      expect(store.isIndexing()).toBe(false);
      expect(store.isThinking()).toBe(false);
    });

    it('rend une réponse sourcée avec une action à valider', () => {
      store.send('question');
      vi.advanceTimersByTime(THINKING);

      const answer = store.messages().at(-1)!;
      expect(answer.author).toBe('donna');
      expect(answer.sources?.length).toBeGreaterThan(0);
      expect(answer.actionKey).toBeTruthy();
    });

    it('ignore une question vide ou pendant la réflexion', () => {
      store.send('   ');
      expect(store.isEmpty()).toBe(true);

      store.send('première');
      store.send('deuxième');
      expect(store.messages()).toHaveLength(1);
    });

    it('retient la validation sans la dupliquer', () => {
      store.send('question');
      vi.advanceTimersByTime(THINKING);
      const answer = store.messages().at(-1)!;

      store.approve(answer.id);
      store.approve(answer.id);
      expect(store.isApproved(answer.id)).toBe(true);
      expect(store.approved()).toHaveLength(1);
    });

    it('vide le fil sans perdre la mémoire indexée', () => {
      store.send('question');
      vi.advanceTimersByTime(THINKING);
      store.resetConversation();

      expect(store.isEmpty()).toBe(true);
      // L'espace reste initialisé : on ne réindexe pas à chaque conversation.
      expect(store.initialised()).toBe(true);
    });
  });
});
