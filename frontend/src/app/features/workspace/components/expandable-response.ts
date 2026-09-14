import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { parseResponse, type ParsedResponse } from '../../../core/chat/response-parser';

/**
 * Affiche une réponse structurée du LLM :
 *
 *   - `thinking` → section repliable, FERMÉE par défaut, header « 🧠 Réflexion »
 *   - `search`   → section repliable, FERMÉE par défaut, header « 🔍 Recherche : {query} »
 *   - `answer`   → toujours visible, jamais dans un accordéon
 *
 * Choix de design :
 *   - Un seul objet `computed` reparse le texte brut à chaque chunk : le
 *     streaming produit des chaînes partielles, et le composant se met à jour
 *     à chaque delta sans re-créer de sous-composants.
 *   - L'état ouvert/fermé vit dans des `signal()` (pas de logique dans le
 *     template avec des variables de template mutables) ; les sections ne
 *     réapparaissent PAS repliées à chaque chunk car on utilise `<details>`
 *     avec une source de vérité, synchronisée sur le toggle.
 *   - Aucune dépendance externe : pas d'accordéon de librairie, pas d'animation
 *     JS mesurée — la transition douce repose sur le grid-rows 0fr→1fr du SCSS.
 */
@Component({
  selector: 'expandable-response',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './expandable-response.html',
  styleUrl: './expandable-response.scss',
})
export class ExpandableResponseComponent {
  /** Texte brut reçu du backend (balises incluses), potentiellement partiel en streaming. */
  readonly content = input<string | undefined>('');

  /** État ouvert/fermé de chaque section — repliées par défaut, comme demandé. */
  protected readonly thinkingOpen = signal(false);
  protected readonly searchOpen = signal(false);

  /** Re-parse à chaque chunk : les balises incomplètes ne plantent jamais. */
  protected readonly parsed = computed<ParsedResponse>(() => parseResponse(this.content()));

  protected toggleThinking(open: boolean): void {
    this.thinkingOpen.set(open);
  }

  protected toggleSearch(open: boolean): void {
    this.searchOpen.set(open);
  }
}