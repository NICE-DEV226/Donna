/**
 * Vérifie que toutes les langues exposent exactement les mêmes clés.
 * Une clé absente d'une langue = un texte qui disparaît à la bascule.
 */
import { readFileSync, readdirSync } from 'node:fs';

const DIR = 'public/i18n';
const flatten = (obj, prefix = '') =>
  Object.entries(obj).flatMap(([key, value]) =>
    value !== null && typeof value === 'object'
      ? flatten(value, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );

const locales = readdirSync(DIR)
  .filter((f) => f.endsWith('.json'))
  .map((file) => ({
    lang: file.replace('.json', ''),
    keys: flatten(JSON.parse(readFileSync(`${DIR}/${file}`, 'utf8'))).sort(),
  }));

const [reference, ...others] = locales;
let failed = false;

for (const locale of others) {
  const missing = reference.keys.filter((k) => !locale.keys.includes(k));
  const extra = locale.keys.filter((k) => !reference.keys.includes(k));

  if (missing.length || extra.length) {
    failed = true;
    console.error(`\n❌ ${locale.lang} vs ${reference.lang}`);
    for (const k of missing) console.error(`   manquante : ${k}`);
    for (const k of extra) console.error(`   en trop   : ${k}`);
  }
}

// Un placeholder non traduit est un texte anglais qui subsiste après la bascule.
for (const locale of locales) {
  const data = JSON.parse(readFileSync(`${DIR}/${locale.lang}.json`, 'utf8'));
  const empty = flatten(data).filter((key) => {
    const value = key.split('.').reduce((o, k) => o?.[k], data);
    return typeof value === 'string' && value.trim() === '';
  });
  if (empty.length) {
    failed = true;
    console.error(`\n❌ ${locale.lang} : ${empty.length} valeur(s) vide(s)`);
    for (const k of empty) console.error(`   ${k}`);
  }
}

// Le surlignage découpe l'extrait autour du passage : si le passage n'y figure
// pas au caractère près, rien ne serait surligné — en silence.
for (const locale of locales) {
  const data = JSON.parse(readFileSync(`${DIR}/${locale.lang}.json`, 'utf8'));
  const entries = data?.workspace?.research?.entries ?? {};
  for (const [key, entry] of Object.entries(entries)) {
    if (!entry.excerpt?.includes(entry.match)) {
      failed = true;
      console.error(
        `\n❌ ${locale.lang} : research.entries.${key} — le passage à surligner` +
          `\n   « ${entry.match} »\n   est absent de son extrait.`,
      );
    }
  }
}

if (failed) process.exit(1);
console.log(`✅ ${locales.length} langues, ${reference.keys.length} clés, parité complète`);
