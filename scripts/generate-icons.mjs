/**
 * Génère src/app/shared/ui/icon-set.ts depuis lucide-static.
 * Seules les icônes listées ici sont embarquées — on garde le bundle minimal.
 * Ajouter une icône = ajouter son nom ci-dessous + `npm run icons`.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ICONS = [
  'brain',
  'search',
  'file-pen-line',
  'zap',
  'user',
  'folder',
  'file-text',
  'calendar-days',
  'menu',
  'x',
  'chevron-right',
  'shield-check',
  'arrow-right',
  'sparkles',
  'eye',
  'eye-off',
  'mail',
  'lock',
  'arrow-left',
  'loader-circle',
  'circle-check',
  'menu',
  'panel-left',
  'bell',
  'plus',
  'mic',
  'arrow-up',
  'message-square',
  'settings',
  'plug',
  'square-pen',
  'paperclip',
  'log-out',
  'clock',
  'check',
  'external-link',
  'globe',
  'chevron-down',
];

// Une même icône listée deux fois produirait une clé dupliquée, donc un build
// cassé. On dédoublonne ici plutôt que de compter sur la vigilance humaine.
const duplicates = ICONS.filter((name, i) => ICONS.indexOf(name) !== i);
if (duplicates.length) {
  console.warn(`⚠️  doublons ignorés : ${[...new Set(duplicates)].join(', ')}`);
}
const UNIQUE = [...new Set(ICONS)].sort();

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const srcDir = join(root, 'node_modules', 'lucide-static', 'icons');

const entries = UNIQUE.map((name) => {
  const svg = readFileSync(join(srcDir, `${name}.svg`), 'utf8');
  const body = svg
    .replace(/^[\s\S]*?<svg[^>]*>/, '')
    .replace(/<\/svg>\s*$/, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!body) throw new Error(`Icône vide : ${name}`);
  return `  '${name}': '${body.replace(/'/g, "\\'")}',`;
}).join('\n');

const version = JSON.parse(
  readFileSync(join(root, 'node_modules', 'lucide-static', 'package.json'), 'utf8'),
).version;

writeFileSync(
  join(root, 'src', 'app', 'shared', 'ui', 'icon-set.ts'),
  `// GÉNÉRÉ PAR scripts/generate-icons.mjs — NE PAS ÉDITER À LA MAIN.
// Source : lucide-static v${version} (ISC). Régénérer : npm run icons
export const ICON_SET = {
${entries}
} as const;

export type IconName = keyof typeof ICON_SET;
`,
);

console.log(`✅ ${UNIQUE.length} icônes générées depuis lucide-static v${version}`);
