#!/bin/sh
set -e

# Reconstruit les .env réels à partir des .env.template — Dokploy injecte
# les variables directement dans l'environnement du conteneur (pas de
# fichier .env monté), mais app/chat et app/xauth déclarent
# envconfiguration.inject=true, qui EXIGE qu'un fichier existe
# physiquement : xcore.kernel.security.validation._inject_dotenv lève
# ManifestError (le plugin entier échoue à charger, pas juste un warning)
# si absent, quel que soit son contenu. python-dotenv interpole ${VAR}
# contre l'environnement réel à la lecture (vérifié : une variable absente
# résout en chaîne vide, jamais une erreur) — une copie verbatim du
# template suffit, aucune vraie substitution à coder ici.
#
# Idempotent — ne touche jamais un .env déjà présent : utile si quelqu'un
# monte un vrai .env en volume plutôt que de compter sur les variables
# d'environnement de la plateforme.
reconstruct() {
  template="$1"
  target="$2"
  if [ -f "$template" ] && [ ! -f "$target" ]; then
    cp "$template" "$target"
  fi
}

reconstruct app/chat/.env.template app/chat/.env
reconstruct app/xauth/.env.template app/xauth/.env

# Clés JWT (RS256) — jamais commitées (*.pem gitignored), générées une fois
# et écrites dans data/ (volume persistant) pour survivre aux
# redéploiements : régénérer à chaque déploiement invaliderait tous les
# jetons déjà émis, déconnectant tout le monde.
: "${XAUTH_JWT_PRIVATE_KEY_PATH:=data/xauth_keys/private.pem}"
: "${XAUTH_JWT_PUBLIC_KEY_PATH:=data/xauth_keys/public.pem}"
export XAUTH_JWT_PRIVATE_KEY_PATH XAUTH_JWT_PUBLIC_KEY_PATH

if [ ! -f "$XAUTH_JWT_PRIVATE_KEY_PATH" ]; then
  echo "[docker-entrypoint] Génération des clés JWT (première exécution) -> $XAUTH_JWT_PRIVATE_KEY_PATH"
  mkdir -p "$(dirname "$XAUTH_JWT_PRIVATE_KEY_PATH")"
  openssl genrsa -out "$XAUTH_JWT_PRIVATE_KEY_PATH" 2048
  openssl rsa -in "$XAUTH_JWT_PRIVATE_KEY_PATH" -pubout -out "$XAUTH_JWT_PUBLIC_KEY_PATH"
fi

# Attend que Redis soit résolvable ET joignable avant de lancer quoi que ce
# soit qui en dépend (cache, pubsub, xworker) — un conteneur (API ou
# worker) peut démarrer avant que le DNS interne de la stack ait fini de
# propager le nom du service Redis, faisant planter xcore.boot() au tout
# premier essai. Simple TCP connect (pas un vrai PING Redis), suffisant
# pour distinguer "DNS pas encore prêt" de "vraiment injoignable" ; via
# python3 (déjà sur le PATH), pas nc/redis-cli qui ne sont pas dans l'image.
if [ -n "$REDIS_URL" ]; then
  python3 - "$REDIS_URL" <<'PY'
import sys, socket, time
from urllib.parse import urlparse

url = urlparse(sys.argv[1])
host, port = url.hostname, url.port or 6379
deadline = time.monotonic() + 60
attempt = 0
while True:
    attempt += 1
    try:
        with socket.create_connection((host, port), timeout=3):
            print(f"[docker-entrypoint] Redis {host}:{port} joignable (essai {attempt}).")
            break
    except OSError as exc:
        if time.monotonic() >= deadline:
            print(f"[docker-entrypoint] Redis {host}:{port} injoignable après {attempt} essais ({exc}) — démarrage quand même, xcore.boot() donnera l'erreur détaillée.")
            break
        print(f"[docker-entrypoint] Redis {host}:{port} pas encore joignable ({exc}), nouvel essai...")
        time.sleep(2)
PY
fi

exec "$@"
