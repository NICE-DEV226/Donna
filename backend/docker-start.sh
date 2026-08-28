#!/bin/bash
set -e

# Lance l'API (uvicorn) et le worker Celery dans le MÊME conteneur, en
# arrière-plan tous les deux. `wait -n` (bash — nécessite bash, pas juste
# sh/dash) rend la main dès que l'UN OU L'AUTRE se termine, quel qu'il soit
# — si le worker crashe pendant que l'API tourne encore, on ne veut pas
# rester dans cet état dégradé sans que personne ne le remarque : on tue
# l'autre processus et on sort avec le code d'erreur, pour que Docker
# (restart policy côté Dokploy) relance le conteneur ENTIER, pas la moitié
# cassée. Le SIGTERM d'un `docker stop`/redéploiement est aussi relayé aux
# deux enfants (sinon Docker les tue au bout du grace period par SIGKILL —
# pas de arrêt propre, tâches Celery en cours coupées net).
#
# Compromis assumé : API et worker ne scalent plus indépendamment (avant,
# un second service Dokploy pouvait n'avoir que le worker et scaler à part
# — voir l'historique de ce fichier). 4 workers uvicorn + 4 concurrency
# Celery dans le même conteneur = jusqu'à 8 process actifs simultanément,
# dimensionnez la ressource Dokploy en conséquence.
#
# docker-watch.sh (auto-update marketplace, optionnel — voir plus bas) est
# le même genre de job de fond, mais volontairement pas mentionné dans
# cette dimension "API + worker" : quand il tourne, il ne consomme quasi
# rien entre deux sondes (voir MARKETPLACE_WATCH_INTERVAL).

trap 'kill -TERM $(jobs -p) 2>/dev/null; wait' TERM INT

uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4 &

celery -A xcore.services.xworker.xworker:_celery_worker worker \
  --loglevel info -Q submissions,default,result --concurrency 4 &

# docker-watch.sh (auto-update des ~14 plugins/extensions marketplace, voir
# ce script) est un 3e job de fond au même titre que l'API et le worker —
# STRICTEMENT optionnel : sans XCORE_MARKETPLACE_API_KEY configurée
# (Dokploy → Environment), on ne le lance pas du tout plutôt que de le
# laisser échouer immédiatement (xcore-agent watch-sources exige cette
# variable) et faire sortir tout le conteneur via wait -n ci-dessous pour
# un déploiement qui n'a simplement pas activé cette fonctionnalité.
if [ -n "$XCORE_MARKETPLACE_API_KEY" ]; then
  /app/docker-watch.sh &
else
  echo "[docker-start] XCORE_MARKETPLACE_API_KEY absente — auto-update marketplace désactivé."
fi

wait -n
exit_code=$?
kill -TERM $(jobs -p) 2>/dev/null
wait
exit "$exit_code"
