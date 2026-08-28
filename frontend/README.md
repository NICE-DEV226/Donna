# DONNA — frontend

Assistante de direction augmentée. Elle lit vos documents, anticipe, prépare —
et n'agit jamais sans votre accord.

Interface Angular du projet, construite à partir d'un design system Google Stitch.

## Démarrer

```sh
npm install
npm start          # http://localhost:4200
```

## Écrans

| Route | |
|---|---|
| `/` | landing |
| `/login` · `/signup` | authentification |
| `/workspace` | espace de travail — conversation, dossiers, mémoire |
| `/workspace/settings` · `/workspace/profile` | réglages et profil |

## Stack

- **Angular 22** — standalone, *zoneless*, signaux
- **Tailwind v4** — le design system est traduit en tokens dans [`src/styles.scss`](src/styles.scss)
- **Angular CDK** — overlays, autosize du champ de saisie, annonces aux lecteurs d'écran
- **Transloco** — bascule EN/FR à l'exécution, l'anglais par défaut
- Illustrations et marque **dessinées à la main en SVG**, colorées par les tokens ; aucun asset externe

## Contrôles

```sh
npm run check          # enchaîne les quatre ci-dessous
npm run lint:classes   # conflits de classes Tailwind (voir plus bas)
npm run lint:i18n      # parité des langues, passages surlignés introuvables
npm run lint:links     # liens morts, avec exceptions documentées
npm test               # tests unitaires et de composants

npm run shots          # captures réelles via Playwright, 4 largeurs
npm run shots -- --lang=fr /workspace
npm run icons          # régénère le jeu d'icônes depuis lucide-static
```

### Deux pièges que les contrôles surveillent

1. **L'échelle `--spacing-*` masque celle des conteneurs Tailwind.** Une largeur
   max nommée d'après un palier d'espacement vaut 16px au lieu de 28rem.
   Utilisez `max-w-page` / `max-w-measure` / `max-w-form` / `max-w-aside`.
2. **Une classe de template ne peut pas contredire une directive.** Deux
   utilitaires sur la même propriété se départagent selon l'ordre de génération
   du CSS, pas celui des classes. Toute variation passe par une entrée de la
   directive (`variant`, `size`, `wrap`).

## Ce qui n'est pas branché

Aucun backend. Trois endroits, tous commentés comme tels, simulent les
aller-retours — et sont les seuls à remplacer :

- [`core/auth/auth.service.ts`](src/app/core/auth/auth.service.ts) — connexion et inscription
- [`features/workspace/workspace.store.ts`](src/app/features/workspace/workspace.store.ts) — réponses, indexation, reconnaissance d'intention
- Les témoignages et cabinets cités viennent de l'univers de *Suits* : aucun client réel n'est mentionné.

Restent à écrire avant toute mise en ligne : l'écran de réinitialisation de mot
de passe, et les textes juridiques (CGU, confidentialité).

## Modèle

- Les **documents** d'un dossier rejoignent la base de connaissances générale :
  DONNA s'en sert depuis n'importe quelle conversation.
- La **mémoire** d'un dossier lui reste propre : ce qu'elle retient d'un client
  ne fuite pas vers un autre. Un test verrouille cette séparation.
