/**
 * Interdit les classes de largeur dont le nom entre en collision avec
 * l'échelle d'espacement du design system (voir le bloc @theme de styles.scss).
 * `max-w-lg` y vaut 24px, pas 32rem — c'est un bug silencieux et coûteux.
 */
import { readFileSync, readdirSync } from 'node:fs';

const SHADOWED = ['xs', 'sm', 'md', 'lg', 'xl', 'xxl'];
const FORBIDDEN = new RegExp(`\\b(max-w|min-w|max-h|min-h)-(${SHADOWED.join('|')})\\b`, 'g');

const files = [];
(function walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = `${dir}/${entry.name}`;
    if (entry.isDirectory()) walk(path);
    else if (/\.(html|ts)$/.test(entry.name)) files.push(path);
  }
})('src/app');

const hits = [];
for (const file of files) {
  readFileSync(file, 'utf8')
    .split('\n')
    .forEach((line, i) => {
      // On ignore les commentaires qui citent le piège pour l'expliquer.
      if (/^\s*(\/\/|\/\*|<!--)/.test(line)) return;
      for (const m of line.matchAll(FORBIDDEN)) hits.push(`${file}:${i + 1}  ${m[0]}`);
    });
}

// Les directives uiButton / uiChip posent `display` et `border-color` via leur
// host binding. Une classe concurrente dans le template n'est PAS garantie de
// gagner : Tailwind ordonne son CSS lui-même. On les interdit à la source.
const DISPLAY = 'hidden|block|inline-block|flex|inline-flex|grid|inline-grid|contents';
const BORDER_COLOR = 'border-(?:line|primary|transparent|success|danger|ink)[a-z-]*';
const WHITESPACE = 'whitespace-[a-z-]+';
const HOSTED = /<[a-z][^>]*\b(uiButton|uiChip)\b[^>]*>/gi;

for (const file of files.filter((f) => f.endsWith('.html'))) {
  const content = readFileSync(file, 'utf8');
  for (const tag of content.match(HOSTED) ?? []) {
    const cls = tag.match(/class="([^"]*)"/)?.[1];
    if (!cls) continue;
    const bad = cls
      .split(/\s+/)
      .filter((c) =>
        new RegExp(`^(?:[a-z0-9]+:)*(?:${DISPLAY}|${BORDER_COLOR}|${WHITESPACE})$`).test(c),
      );
    for (const c of bad) {
      const line = content.slice(0, content.indexOf(tag)).split('\n').length;
      hits.push(`${file}:${line}  « ${c} » sur un élément uiButton/uiChip — sera écrasé`);
    }
  }
}

if (hits.length) {
  console.error(`\n❌ ${hits.length} classe(s) en conflit :\n`);
  for (const h of hits) console.error('   ' + h);
  console.error(
    '\n   Largeurs : utilisez max-w-page / max-w-measure / max-w-form / max-w-aside.' +
      '\n   display / border-color / white-space : passez par une entrée de la directive' +
      '\n   (variant, size, wrap) ou par un élément conteneur.\n',
  );
  process.exit(1);
}
console.log('✅ aucune classe en conflit (largeurs, display, border-color)');
