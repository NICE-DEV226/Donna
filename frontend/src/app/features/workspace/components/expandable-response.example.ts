import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ExpandableResponseComponent } from './expandable-response';

/**
 * Exemple d'utilisation dans un composant parent — avec une string de test
 * contenant les trois balises. (Démo de référence, non routée : elle sert de
 * documentation exécutable pour l'intégration réelle, voir conversation-panel.)
 */
@Component({
  selector: 'expandable-response-demo',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ExpandableResponseComponent],
  template: `
    <expandable-response [content]="sample" />
  `,
})
export class ExpandableResponseExample {
  protected readonly sample = `<thinking>L'utilisateur demande les dernières actualités IA ; une recherche web est pertinente car le sujet évolue vite et ma mémoire peut être périmée.</thinking><search query="dernières actualités intelligence artificielle 2026"><title>La recherche renvoie les résultats les plus récents issus de DuckDuckGo.</title></search><answer>Voici les dernières actualités IA : <strong>OpenAI</strong> a ouvert un nouveau modèle raisonneur, <strong>Google</strong> a mis à jour Gemini, et l'écosystème open source continue de progresser avec Llama.</answer>`;
}