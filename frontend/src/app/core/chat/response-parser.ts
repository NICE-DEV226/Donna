import { Injectable } from '@angular/core';

/**
 * Parsing des réponses structurées du LLM.
 *
 * Le backend renvoie une chaîne brute pouvant contenir :
 *   <thinking>...</thinking>   → raisonnement interne du modèle
 *   <search query="...">...</search>  → recherche web exécutée
 *   <answer>...</answer>      → réponse finale (toujours présente)
 *
 * Tolérance au streaming : les chunks arrivent au fil de l'eau. Une balise
 * peut être ouverte et pas encore fermée, `<search>` peut arriver sans son
 * attribut `query=` encore complet, `<answer>` peut être vide sur la première
 * micro-partie. Le parseur ne doit JAMAIS lever d'exception ni rendre un écran
 * blanc — il repart du texte complet à chaque delta, donc les erreurs
 * transitoires d'un chunk se corrigent au chunk suivant.
 */
export interface ParsedResponse {
  /** Contenu brut de <thinking>, si présent et non vide. */
  thinking?: string;
  /** Contenu de <search>, si présent. */
  search?: { query: string; content: string };
  /** Réponse finale. */
  answer: string;
}

/** Vrai si le texte contient au moins une balise structurée (think/search/answer). */
export function containsStructureTags(raw: string | null | undefined): boolean {
  return /<(?:thinking|search|answer)\b/i.test(raw ?? '');
}

/** Toutes les occurrences des balises, dans l'ordre où elles apparaissent dans le flux. */
interface Token {
  index: number;
  end: number;
  full: string;
  tag: 'thinking' | 'search' | 'answer';
  close: boolean;
}

const TOKEN_RE = /<\/?(thinking|search|answer)\b[^>]*>/gi;
const SEARCH_QUERY_RE = /<search\s+query\s*=\s*["']([^"']*)["']/i;

export function parseResponse(raw: string | null | undefined): ParsedResponse {
  const source = raw ?? '';

  // 1. Indexer les balises — sans préjuger de leur validité (fermées ou non).
  const tokens: Token[] = [];
  let match: RegExpExecArray | null;
  while ((match = TOKEN_RE.exec(source)) !== null) {
    const full = match[0];
    tokens.push({
      index: match.index,
      end: match.index + full.length,
      full,
      tag: match[1].toLowerCase() as Token['tag'],
      close: full.startsWith('</'),
    });
  }

  // 2. Rejouer le flux : le texte avant chaque balise alimente la section
  //    courante. On part de 'answer' pour que du texte sans balise (ou après
  //    la fermeture d'une section) reste une réponse visible.
  const sections: Record<'thinking' | 'search' | 'answer', string> = {
    thinking: '',
    search: '',
    answer: '',
  };
  let active: 'thinking' | 'search' | 'answer' = 'answer';
  let cursor = 0;
  let query = '';

  for (const token of tokens) {
    sections[active] += source.slice(cursor, token.index);

    if (token.close) {
      // Une section fermée : le prochain texte va à la réponse (ou à ce qui suit).
      active = 'answer';
    } else {
      if (token.tag === 'search') {
        const extracted = SEARCH_QUERY_RE.exec(token.full);
        // L'attribut peut être encore en train d'arriver (streaming) → query vide.
        if (extracted) query = extracted[1];
      }
      active = token.tag;
    }
    cursor = token.end;
  }

  // 3. Reste du texte : soit après la dernière balise, soit le contenu d'une
  //    balise ouverte mais jamais fermée (streaming) — on le garde tel quel.
  if (cursor < source.length) sections[active] += source.slice(cursor);

  const thinking = sections.thinking.trim();
  const content = sections.search.trim();

  return {
    thinking: thinking || undefined,
    search: query || content ? { query, content } : undefined,
    answer: sections.answer.trim(),
  };
}

/** Wrapper injectable — le parseur reste une fonction pure, testable sans DI. */
@Injectable({ providedIn: 'root' })
export class ResponseParserService {
  parse(raw: string | null | undefined): ParsedResponse {
    return parseResponse(raw);
  }
}