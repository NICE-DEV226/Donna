/**
 * Contrôle visuel : lance le serveur de dev, capture chaque route à plusieurs
 * largeurs, puis s'arrête. Sert à VÉRIFIER un rendu au lieu de le déduire.
 *
 *   npm run shots            → toutes les routes, toutes les largeurs
 *   npm run shots -- /login  → une seule route
 */
import { execSync, spawn } from 'node:child_process';
import { mkdir, rm } from 'node:fs/promises';
import { chromium } from 'playwright';

const PORT = 4321;
const ORIGIN = `http://localhost:${PORT}`;
const OUT = '.screenshots';

const args = process.argv.slice(2);
// `npm run shots -- --lang=fr /` capture la page dans une autre langue.
const LANG = args.find((a) => a.startsWith('--lang='))?.split('=')[1] ?? 'en';
const routes = args.filter((a) => !a.startsWith('--'));
const ROUTES = routes.length ? routes : ['/', '/login', '/signup', '/workspace'];

// Les largeurs qui comptent : le pli mobile, la zone tablette où les grilles
// basculent, le desktop de référence, et le grand écran.
const WIDTHS = [375, 768, 1280, 1920];

const slug = (route) => {
  const base = route === '/' ? 'landing' : route.replace(/\//g, '-').replace(/^-/, '');
  return LANG === 'en' ? base : `${base}-${LANG}`;
};

async function waitForServer(timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(ORIGIN, { signal: AbortSignal.timeout(2000) });
      if (res.ok) return;
    } catch {
      /* pas encore prêt */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Le serveur n'a pas répondu sur ${ORIGIN}`);
}

// Un `ng serve` déjà lancé partage le cache .angular/ avec celui qu'on démarre
// ici. Les deux builds qui écrivent au même endroit peuvent figer le watcher du
// serveur de développement : il continue de répondre, mais sert un bundle périmé.
// On ne peut pas l'empêcher — on le signale, c'est déjà ce qui manquait.
try {
  const running = execSync("pgrep -af 'ng serve' || true", { encoding: 'utf8' })
    .split('\n')
    .filter((line) => line.includes('ng serve') && !line.includes(String(PORT)));
  if (running.length) {
    console.warn(
      '⚠️  un serveur de développement tourne déjà.\n' +
        "    Après cette capture, redémarrez-le : son watcher peut s'être figé\n" +
        '    et continuer à servir un bundle périmé.\n',
    );
  }
} catch {
  /* pgrep indisponible : sans conséquence */
}

const server = spawn(
  'npx',
  ['ng', 'serve', '--port', String(PORT), '--configuration', 'development'],
  { stdio: 'ignore' },
);

const shutdown = () => server.kill('SIGTERM');
process.on('exit', shutdown);
process.on('SIGINT', () => process.exit(130));

try {
  console.log('⏳ démarrage du serveur…');
  await waitForServer();

  await mkdir(OUT, { recursive: true });

  const browser = await chromium.launch();
  const problems = [];

  for (const width of WIDTHS) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      deviceScaleFactor: 1,
    });

    // La langue est lue depuis localStorage au démarrage de l'application.
    await context.addInitScript((lang) => {
      try {
        localStorage.setItem('donnat.lang', lang);
      } catch {
        /* stockage indisponible */
      }
    }, LANG);

    for (const route of ROUTES) {
      const page = await context.newPage();
      const consoleErrors = [];
      page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()));
      page.on('pageerror', (e) => consoleErrors.push(String(e)));

      await page.goto(`${ORIGIN}${route}`, { waitUntil: 'networkidle' });

      // Sans ce défilement, IntersectionObserver ne se déclenche jamais pour ce
      // qui est sous la ligne de flottaison : les blocs à révélation restent à
      // opacity 0 et la capture montre des sections vides.
      await page.evaluate(async () => {
        const step = window.innerHeight / 2;
        for (let y = 0; y < document.body.scrollHeight; y += step) {
          window.scrollTo(0, y);
          await new Promise((r) => setTimeout(r, 120));
        }
        window.scrollTo(0, 0);
      });
      await page.waitForTimeout(900);

      const file = `${OUT}/${slug(route)}-${width}.png`;
      await page.screenshot({ path: file, fullPage: true });

      // Un débordement horizontal est toujours un bug de mise en page.
      // On nomme le coupable : chercher à la main coûte bien plus cher.
      const overflow = await page.evaluate(() => {
        const limit = document.documentElement.clientWidth;
        if (document.documentElement.scrollWidth <= limit) return null;

        return [...document.querySelectorAll('*')]
          .filter((el) => el.getBoundingClientRect().right > limit + 1)
          .slice(0, 5)
          .map((el) => {
            const rect = el.getBoundingClientRect();
            const cls = (el.getAttribute('class') ?? '').slice(0, 90);
            return `<${el.tagName.toLowerCase()}> dépasse de ${Math.round(rect.right - limit)}px — ${cls}`;
          });
      });
      if (overflow) {
        for (const culprit of overflow) problems.push(`${route} @${width}px : ${culprit}`);
      }
      for (const err of consoleErrors) problems.push(`${route} @${width}px : ${err}`);

      console.log(`  📸 ${file}${overflow ? '  ⚠️ débordement' : ''}`);
      await page.close();
    }

    await context.close();
  }

  await browser.close();

  if (problems.length) {
    console.log(`\n⚠️  ${problems.length} problème(s) :`);
    for (const p of problems) console.log('   ' + p);
  } else {
    console.log('\n✅ aucun débordement, aucune erreur console.');
  }
} finally {
  shutdown();
}
