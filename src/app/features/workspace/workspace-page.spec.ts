import { By } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { EN, FR, provideTestTranslations, stubIntersectionObserver } from '../../../testing/setup';
import { Language } from '../../core/i18n/language';
import { WorkspaceHome } from './workspace-home';
import { WorkspacePage } from './workspace-page';
import { Toasts } from '../../core/notifications/toasts';
import { INGEST_STEPS, WorkspaceStore } from './workspace.store';

const INGEST_TOTAL = 1200 * INGEST_STEPS.length;

describe('WorkspacePage', () => {
  let harness: RouterTestingHarness;
  let host: HTMLElement;
  let store: WorkspaceStore;

  const detect = () => harness.detectChanges();

  beforeAll(stubIntersectionObserver);

  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      imports: [provideTestTranslations()],
      providers: [
        // On monte le VRAI routage : la coquille et sa vue par défaut, comme en
        // production. Rendre la page seule laisserait le router-outlet vide.
        provideRouter([
          {
            path: 'workspace',
            component: WorkspacePage,
            children: [{ path: '', component: WorkspaceHome }],
          },
          { path: 'login', children: [] },
        ]),
      ],
    }).compileComponents();

    harness = await RouterTestingHarness.create('/workspace');
    host = harness.fixture.nativeElement as HTMLElement;
    store = harness.fixture.debugElement
      .query(By.directive(WorkspacePage))
      .injector.get(WorkspaceStore);

    // Les faux minuteurs viennent APRÈS la navigation, qui s'appuie sur des
    // promesses : les activer avant ferait attendre indéfiniment.
    vi.useFakeTimers();
    detect();
  });

  afterEach(() => vi.useRealTimers());

  describe('mise en place de la mémoire', () => {
    it('ouvre sur la configuration, pas sur la conversation', () => {
      expect(host.querySelector('workspace-setup')).not.toBeNull();
      expect(host.querySelector('conversation-panel')).toBeNull();
      expect(host.querySelector('h1')?.textContent?.trim()).toBe(EN.workspace.setup.title);
      expect(host.querySelector('aside')).toBeNull();
    });

    it('n’autorise le lancement qu’une fois des documents déposés', () => {
      const start = [...host.querySelectorAll('button')].find(
        (b) => b.textContent?.trim() === EN.workspace.setup.start,
      ) as HTMLButtonElement;

      expect(start.disabled).toBe(true);
      store.addDocuments(3);
      detect();
      expect(start.disabled).toBe(false);
    });

    it('suit l’indexation dans le rail droit, sans rien bloquer', () => {
      store.addDocuments(3);
      store.initialise();
      detect();

      const panel = host.querySelector('aside indexing-progress section');
      expect(panel).not.toBeNull();
      expect(panel!.getAttribute('aria-busy')).toBe('true');
      expect(panel!.textContent).toContain(EN.workspace.setup.indexing.reading);

      // Surtout PAS de voile modal : l'utilisateur doit pouvoir écrire.
      expect(host.querySelector('[role="dialog"][aria-modal="true"]')).toBeNull();
      expect(host.querySelector('conversation-panel')).not.toBeNull();
      expect(host.querySelector('conversation-panel textarea')).not.toBeNull();

      vi.advanceTimersByTime(INGEST_TOTAL);
      detect();

      // Le rail disparaît quand il n'a plus rien à dire.
      expect(host.querySelector('aside')).toBeNull();
    });

    it('laisse poser des questions pendant que la mémoire se construit', () => {
      store.addDocuments(3);
      store.initialise();
      detect();

      store.send('Que disent nos contrats Meridian ?');
      vi.advanceTimersByTime(1600);
      detect();

      expect(store.messages()).toHaveLength(2);
      // L'indexation n'a pas été interrompue par la question.
      expect(host.querySelector('aside indexing-progress section')).not.toBeNull();
    });
  });

  describe('conversation', () => {
    beforeEach(() => {
      store.skipSetup();
      detect();
    });

    it('n’ouvre JAMAIS le panneau d’indexation en posant une question', () => {
      for (const question of ['première', 'deuxième', 'troisième']) {
        store.send(question);
        detect();
        expect(host.querySelector('indexing-progress section'), question).toBeNull();
        // Le seul retour visuel est dans le fil.
        expect(host.querySelectorAll('conversation-panel .thinking-dot')).toHaveLength(3);

        vi.advanceTimersByTime(1600);
        detect();
        expect(host.querySelector('indexing-progress section'), question).toBeNull();
        expect(host.querySelectorAll('conversation-panel .thinking-dot')).toHaveLength(0);
      }

      expect(store.messages().filter((m) => m.author === 'donna')).toHaveLength(3);
    });

    it('n’affiche aucun avatar de profil dans le fil', () => {
      store.send('question');
      vi.advanceTimersByTime(1600);
      detect();

      expect(host.querySelectorAll('conversation-panel ui-icon[name="user"]')).toHaveLength(0);
      expect(host.querySelectorAll('conversation-panel ui-avatar')).toHaveLength(0);
      // DONNA garde sa marque : le fil reste attribuable.
      expect(host.querySelectorAll('conversation-panel donna-mark').length).toBeGreaterThan(0);
    });

    it('égrène les sources consultées pendant la recherche', () => {
      store.send('Quels contrats expirent ?');
      detect();

      // Au départ, rien de consulté : seuls les points battent.
      expect(host.querySelectorAll('research-trace li')).toHaveLength(0);

      vi.advanceTimersByTime(400);
      detect();
      const early = host.querySelectorAll('research-trace li').length;
      expect(early).toBeGreaterThan(0);

      vi.advanceTimersByTime(1200);
      detect();
      expect(host.querySelectorAll('research-trace li').length).toBeGreaterThan(early);
    });

    it('attache les sources à la réponse, repliées mais conservées', () => {
      store.send('question');
      vi.advanceTimersByTime(1600);
      detect();

      const card = host.querySelector('conversation-panel research-trace details')!;
      expect(card).not.toBeNull();
      // Repliée pour ne pas encombrer la lecture…
      expect((card as HTMLDetailsElement).open).toBe(false);
      // …mais la preuve est toujours là.
      expect(card.querySelectorAll('li').length).toBeGreaterThan(0);
      expect(card.querySelector('mark')).not.toBeNull();
    });

    it('signale l’ajout en mémoire par une notification non bloquante', () => {
      const toasts = TestBed.inject(Toasts);
      expect(toasts.items()).toHaveLength(0);

      store.send('question');
      vi.advanceTimersByTime(1600);
      detect();

      expect(toasts.items()).toHaveLength(1);
      const card = host.querySelector('toast-stack article')!;
      expect(card.textContent).toContain(EN.workspace.memory.saved);

      // Jamais de modal, et la pile laisse passer les clics.
      expect(host.querySelector('toast-stack [role="dialog"]')).toBeNull();
      expect(host.querySelector('toast-stack > div')!.classList).toContain('pointer-events-none');
      expect(card.classList).toContain('pointer-events-auto');

      // Et elle se ferme d'elle-même.
      vi.advanceTimersByTime(6000);
      detect();
      expect(toasts.items()).toHaveLength(0);
    });

    describe('lecture d’une source', () => {
      function openFirstSource(): void {
        store.send('What does the Meridian contract say?');
        vi.advanceTimersByTime(1600);
        detect();
        (host.querySelector('research-trace li button') as HTMLButtonElement).click();
        detect();
      }

      it('ouvre le document à côté, sans quitter la conversation', () => {
        openFirstSource();

        const panel = host.querySelector('document-preview aside')!;
        expect(panel).not.toBeNull();
        // La conversation n'a pas disparu : on compare sans perdre le fil.
        expect(host.querySelector('conversation-panel ol')).not.toBeNull();

        const entry = EN.workspace.research.entries.one;
        expect(panel.textContent).toContain(entry.title);
        expect(panel.textContent).toContain(entry.meta);
        // Le passage cité, et son contexte autour.
        expect(panel.textContent).toContain(entry.excerpt);
        expect(panel.textContent).toContain(entry.before);
        expect(panel.textContent).toContain(entry.after);
      });

      it('garde l’original accessible, mais comme un choix explicite', () => {
        openFirstSource();

        const external = host.querySelector<HTMLAnchorElement>('document-preview a[target="_blank"]')!;
        expect(external).not.toBeNull();
        expect(external.getAttribute('href')).toBe(EN.workspace.research.entries.one.url);
        // Sans `noopener`, la page ouverte garde une prise sur la nôtre.
        expect(external.getAttribute('rel')).toContain('noopener');
      });

      it('se referme et range la notification à côté, jamais dessus', () => {
        openFirstSource();
        const stack = host.querySelector('toast-stack > div')!;
        expect(stack.classList).toContain('toast-stack--shifted');

        store.closeSource();
        detect();
        expect(host.querySelector('document-preview aside')).toBeNull();
        expect(stack.classList).not.toContain('toast-stack--shifted');
      });
    });

    describe('elle demande avant de deviner', () => {
      const options = () => host.querySelectorAll('.clarify-options button');

      it('propose des réponses cliquables quand aucune partie n’est nommée', () => {
        store.send('What does our contract say about the notice period?');
        vi.advanceTimersByTime(900);
        detect();

        expect(host.textContent).toContain(EN.workspace.clarify.question);
        expect(options()).toHaveLength(Object.keys(EN.workspace.clarify.options).length);
        expect(options()[0].textContent?.trim()).toBe(EN.workspace.clarify.options.meridian);

        // Elle n'a rien cherché : chercher sans savoir quoi serait du gaspillage.
        expect(host.querySelector('research-trace')).toBeNull();
        // Et elle dit pourquoi elle demande.
        expect(host.textContent).toContain(EN.workspace.clarify.note);
      });

      it('reprend le choix comme un message, puis répond vraiment', () => {
        store.send('What does our contract say?');
        vi.advanceTimersByTime(900);
        detect();

        (options()[0] as HTMLButtonElement).click();
        detect();

        // Le choix devient une phrase de l'utilisateur : le fil reste lisible.
        const said = host.querySelectorAll('conversation-panel ol > li')[2];
        expect(said.textContent?.trim()).toBe(EN.workspace.clarify.options.meridian);

        vi.advanceTimersByTime(1600);
        detect();
        expect(store.messages().filter((m) => m.author === 'donna')).toHaveLength(2);
        expect(host.querySelector('research-trace')).not.toBeNull();
      });

      it('ne demande rien quand la partie est nommée', () => {
        store.send('What does the Meridian contract say?');
        vi.advanceTimersByTime(900);
        detect();

        expect(host.querySelector('.clarify-options')).toBeNull();
        // Elle cherche directement.
        expect(store.isThinking()).toBe(true);
      });

      it('traduit la question et ses options', () => {
        TestBed.inject(Language).set('fr');
        detect();

        store.send('Que dit notre contrat sur le préavis ?');
        vi.advanceTimersByTime(900);
        detect();

        expect(host.textContent).toContain(FR.workspace.clarify.question);
        expect(options()[2].textContent?.trim()).toBe(FR.workspace.clarify.options.all);
      });
    });

    describe('rappel à la manière de Donna', () => {
      it('prend note sans chercher : ce n’est pas une question', () => {
        store.send('Remind me at 3pm about the Meridian review');
        vi.advanceTimersByTime(900);
        detect();

        // Aucune recherche : elle n'a rien à consulter, elle a à retenir.
        expect(host.querySelector('research-trace')).toBeNull();
        expect(host.textContent).toContain(EN.workspace.reminder.confirm);
      });

      it('ne fait aucun bruit pendant l’attente', () => {
        const toasts = TestBed.inject(Toasts);
        store.send('Remind me at 3pm about the Meridian review');
        vi.advanceTimersByTime(900 + 2000);
        detect();

        // Ni notification, ni compte à rebours, ni pastille : elle attend.
        expect(toasts.items()).toHaveLength(0);
        expect(host.querySelector('donna-interjection')).toBeNull();
      });

      it('revient d’elle-même, avec ce qui a changé et le travail déjà fait', () => {
        store.send('Remind me at 3pm about the Meridian review');
        vi.advanceTimersByTime(900 + 5000);
        detect();

        const card = host.querySelector('donna-interjection')!;
        expect(card).not.toBeNull();

        // Les trois marques d'une assistante plutôt que d'une alarme :
        expect(card.textContent).toContain(EN.workspace.reminder.time);
        expect(card.textContent).toContain(EN.workspace.reminder.changedLabel);
        expect(card.textContent).toContain(EN.workspace.reminder.prepared);

        // Elle ne rend pas sa propre phrase à l'utilisateur.
        expect(card.textContent).not.toContain('Remind me at 3pm');
      });

      it('se laisse repousser sans disparaître', () => {
        store.send('Remind me at 3pm about the Meridian review');
        vi.advanceTimersByTime(900 + 5000);
        detect();

        const later = [...host.querySelectorAll('donna-interjection button')].find(
          (b) => b.textContent?.trim() === EN.workspace.reminder.later,
        ) as HTMLButtonElement;
        later.click();
        detect();

        // Repoussée, pas supprimée : elle repasse.
        expect(host.querySelector('donna-interjection')).not.toBeNull();
        expect(host.querySelector('donna-interjection')!.textContent).toContain(
          EN.workspace.reminder.deferred,
        );
      });
    });

    it('affiche l’état vide avec ses trois suggestions', () => {
      expect(host.querySelector('h1')?.textContent?.trim()).toBe(EN.workspace.empty.greeting);
      expect(
        host.querySelectorAll('conversation-panel button.rounded-full').length,
      ).toBeGreaterThanOrEqual(3);
    });
  });

  describe('dossiers clients', () => {
    beforeEach(() => {
      store.skipSetup();
      detect();
    });

    const openDialog = () => {
      // Le bouton vit dans le panneau déployant, donc dans le conteneur
      // d'overlay du CDK — hors de l'arbre du composant.
      host.querySelector('workspace-sidebar button')!.dispatchEvent(
        new MouseEvent('mouseenter', { bubbles: false }),
      );
      detect();

      const trigger = [...document.body.querySelectorAll('button')].find(
        (b) => b.getAttribute('aria-label') === EN.workspace.projects.new,
      ) as HTMLButtonElement;
      expect(trigger, 'bouton « nouveau projet » introuvable').toBeDefined();
      trigger.click();
      detect();
    };

    it('ouvre le rail sur les dossiers existants', () => {
      host.querySelector('workspace-sidebar button')!.dispatchEvent(
        new MouseEvent('mouseenter', { bubbles: false }),
      );
      detect();

      expect(store.projects().length).toBeGreaterThan(0);
      expect(document.body.textContent).toContain(EN.workspace.projects.title);
    });

    it('exige un nom avant de créer', () => {
      openDialog();
      const before = store.projects().length;

      host.querySelector('project-dialog form')!.dispatchEvent(new Event('submit'));
      detect();

      expect(store.projects()).toHaveLength(before);
      expect(host.querySelector('project-dialog [role="alert"]')?.textContent?.trim()).toBe(
        EN.workspace.projects.nameRequired,
      );
    });

    it('dit franchement que le dossier classe sans cloisonner', () => {
      openDialog();
      // Le modèle doit être lisible AVANT de verser des documents.
      expect(host.querySelector('project-dialog')!.textContent).toContain(
        EN.workspace.projects.sharedNote,
      );
    });

    it('crée le dossier, l’active, et verse ses documents dans la mémoire commune', () => {
      const before = store.projects().length;
      const project = store.createProject('Zane — arbitration', 'Zane Specter Litt', 4);
      detect();

      expect(store.projects()).toHaveLength(before + 1);
      expect(store.activeProjectId()).toBe(project!.id);
      // Les documents rejoignent l'index général, pas un index de projet.
      expect(store.documentCount()).toBeGreaterThanOrEqual(4);
      expect(store.isIndexing()).toBe(true);

      // Et l'indexation ne bloque pas : on peut écrire pendant.
      expect(host.querySelector('conversation-panel textarea')).not.toBeNull();
      expect(host.querySelector('[role="dialog"][aria-modal="true"]')).toBeNull();

      // Le dossier actif se lit dans la barre haute.
      expect(host.querySelector('workspace-topbar')!.textContent).toContain('Zane — arbitration');
    });

    it('refuse un nom vide au niveau du store aussi', () => {
      const before = store.projects().length;
      expect(store.createProject('   ', '', 3)).toBeNull();
      expect(store.projects()).toHaveLength(before);
    });
  });

  describe('rails', () => {
    it('n’ouvre le panneau qu’au survol de l’icône, jamais du rail', () => {
      const rail = host.querySelector('workspace-sidebar > div')!;
      const icon = host.querySelector('workspace-sidebar button')!;
      const isOpen = () => icon.getAttribute('aria-expanded') === 'true';

      rail.dispatchEvent(new MouseEvent('mouseenter', { bubbles: false }));
      detect();
      expect(isOpen()).toBe(false);

      icon.dispatchEvent(new MouseEvent('mouseenter', { bubbles: false }));
      detect();
      expect(isOpen()).toBe(true);
    });

    it('ne met qu’un bouton dans le rail, et rien en bas', () => {
      const rail = host.querySelector('workspace-sidebar')!;
      expect(rail.querySelectorAll('button')).toHaveLength(1);
      expect(rail.textContent?.trim()).toBe('');
    });

    it('ne pose aucun filet sur les rails : la séparation est tonale', () => {
      // Le rail droit n'existe que pendant l'indexation : on la déclenche.
      store.addDocuments(1);
      store.initialise();
      detect();

      const rail = host.querySelector('workspace-sidebar > div')!;
      const aside = host.querySelector('aside')!;
      for (const element of [rail, aside]) {
        expect([...element.classList].filter((c) => /^border(-[trbl])?(-|$)/.test(c))).toHaveLength(
          0,
        );
        expect(element.classList).toContain('bg-surface-sunken');
      }
    });
  });
});
