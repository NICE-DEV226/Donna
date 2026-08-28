# 🚀 Plan d'Action : Développement d'un RAG Local Multi-Tenant Haute Performance

Ce document sert de feuille de route pour transformer notre script de base en un système RAG (Retrieval-Augmented Generation) de niveau production, entièrement local, sécurisé et cloisonné par utilisateur.

---

## 📋 Architecture Globale du Projet

```text
       [ Client / Utilisateur ]
                  │  (Requête + Tenant_ID)
                  ▼
         [ API FastAPI ]  ◄─── Authentification (JWT / Tenant Isolation)
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
 [ Ollama Llama3 ]   [ Chroma DB ]
   (Génération)       └─── Collection: tenant_A
                      └─── Collection: tenant_B
```

---

## 🛠️ Étape 1 : Fondations & Isolation (Multi-Tenancy)
*L'objectif est d'assurer l'étanchéité totale des données entre vos clients.*

- [ ] **Découpage par Collection Chroma** : Utiliser explicitement l'argument `collection_name="tenant_{id_tenant}"` à chaque écriture et lecture.
- [ ] **Persistance des données** : Configurer un dossier de stockage permanent (`persist_directory="./chroma_db"`) pour éviter de recalculer les fichiers à chaque redémarrage.
- [ ] **Couche API (FastAPI)** : Créer des endpoints sécurisés où le `tenant_id` est extrait automatiquement du token d'authentification de l'utilisateur (ex: JWT).

---

## 📈 Étape 2 : Amélioration de la Qualité (Le "Bon" RAG)
*Passer d'un prototype à un système qui donne des réponses précises et sans hallucinations.*

### 1. Préparation des données (Data Prep)
- [ ] **Nettoyage de texte** : Supprimer les en-têtes, pieds de page et caractères spéciaux des documents avant de les découper.
- [ ] **Découpage Sémantique (Semantic Chunking)** : Remplacer le découpage par nombre de caractères par un découpage basé sur le sens des phrases (disponible dans `langchain_experimental`).

### 2. Moteur de Recherche Avancé (Retrieval)
- [ ] **Recherche Hybride** : Combiner la recherche vectorielle (Ollama) avec une recherche textuelle classique (BM25) pour ne pas rater les mots-clés exacts (codes, noms propres).
- [ ] **Intégration d'un Reranker** : Ajouter une étape de re-classement locale (ex: avec un modèle *BGE-Rerank* léger en local via HuggingFace) pour trier les 5 meilleurs morceaux avant de les envoyer à l'IA.

### 3. Contrôle de la Génération
- [ ] **Prompt Strict** : Verrouiller le comportement de Llama 3 avec des consignes strictes (ex: *"Interdiction d'inventer, si l'information n'est pas dans le contexte, réponds : 'Je ne sais pas'"*).

---

## 🧪 Étape 3 : Évaluation & Optimisation
*Vérifier scientifiquement si le système fonctionne bien.*

- [ ] **Suivi des métriques clés** : Installez le framework `ragas` pour mesurer :
  - La **Fidélité** (L'IA invente-t-elle des faits ?).
  - La **Pertinence du contexte** (Le moteur de recherche trouve-t-il les bons documents ?).
- [ ] **Optimisation Matérielle** : Ajuster la taille du modèle Ollama selon votre machine (ex: basculer sur `llama3:8b` si vous avez un GPU dédié, ou un modèle plus petit comme `phi3` si vous êtes uniquement sur CPU).

---

## 🔥 Prochaines étapes immédiates

1. **Créer la structure des dossiers** de votre application :
   ```bash
   mkdir -p src/api src/rag src/data
   ```
2. **Encapsuler le script précédent** dans une classe réutilisable `MultiTenantRAG` dans `src/rag/engine.py`.
