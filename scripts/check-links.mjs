/**
 * Refuse les liens qui ne mènent nulle part.
 *
 * `href="#"` remonte en haut de page : pour l'utilisateur, le lien est cassé.
 * Un lien doit viser une ancre réelle, une route, ou une adresse.
 */
import { readFileSync, readdirSync } from 'node:fs';

/**
 * Exceptions assumées, avec leur raison. Le compte est vérifié : si un lien
 * mort apparaît ailleurs — ou si l'un de ceux-ci est enfin branché — le
 * contrôle le signale.
 */
const ALLOWED = [
  {
    file: 'src/app/features/auth/login-page.html',
    count: 1,
    reason: '« Mot de passe oublié » — écran de réinitialisation pas encore construit',
  },
  {
    file: 'src/app/features/auth/signup-page.html',
    count: 2,
    reason: 'CGU et confidentialité — textes juridiques à rédiger, on ne les invente pas',
  },
];

const files = [];
(function walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = `${dir}/${entry.name}`;
    if (entry.isDirectory()) walk(path);
    else if (/\.(html|ts)$/.test(entry.name) && !/\.spec\.ts$/.test(entry.name)) files.push(path);
  }
})('src/app');

let failed = false;
const pending = new Map(ALLOWED.map((a) => [a.file, a]));

for (const file of files) {
  const content = readFileSync(file, 'utf8');
  const hits = [...content.matchAll(/href\s*=\s*"(#|)"/g)];
  const allowance = pending.get(file);

  if (!hits.length) {
    if (allowance) {
      failed = true;
      console.error(`\n❌ ${file} : ${allowance.count} lien(s) mort(s) attendus, aucun trouvé.`);
      console.error('   Retirez l’exception dans scripts/check-links.mjs.');
    }
    continue;
  }

  if (!allowance) {
    failed = true;
    console.error(`\n❌ ${file} : ${hits.length} lien(s) vide(s) — href="#"`);
    for (const hit of hits) {
      console.error(`   ligne ${content.slice(0, hit.index).split('\n').length}`);
    }
    continue;
  }

  if (hits.length !== allowance.count) {
    failed = true;
    console.error(
      `\n❌ ${file} : ${hits.length} lien(s) vide(s), ${allowance.count} tolérés.\n   ${allowance.reason}`,
    );
  }
  pending.delete(file);
}

if (failed) {
  console.error('\n   Visez une ancre réelle, une route, ou une adresse.\n');
  process.exit(1);
}

const tolerated = ALLOWED.reduce((sum, a) => sum + a.count, 0);
console.log(`✅ aucun lien mort (${tolerated} exception(s) documentée(s))`);
for (const entry of ALLOWED) console.log(`   · ${entry.reason}`);
