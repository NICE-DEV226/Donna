import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from xcore import Xcore
from extensions.xwebsocket.main import WsManager


# XCORE_CONFIG_PATH : voir integration.docker.yaml (variante sans Ollama,
# utilisée en conteneur — voir Dockerfile/docker-entrypoint.sh). Absent en
# dev, où integration.yaml (le fichier par défaut) reste utilisé tel quel.
xcore = Xcore(config_path=os.environ.get("XCORE_CONFIG_PATH", "integration.yaml"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await xcore.boot(app)

    print(xcore.plugins_lists)
    yield
    await xcore.shutdown()


# Interrupteurs docs/openapi pilotés par la config xcore (section
# app.fastapi) : integration.yaml (dev) les expose, integration.docker.yaml
# (prod) les met à null. Passés AU CONSTRUCTEUR car FastAPI enregistre ces
# routes dans __init__ (un setattr après coup ne les retirerait pas) — sans
# ce câblage, /docs restait exposé en prod quel que soit le YAML (fail-open
# constaté à l'audit).
_fapi_cfg = getattr(xcore, "fastapi", None) or {}


def _docs_flag(name: str, default: str | None) -> str | None:
    value = _fapi_cfg.get(name, default)
    return value or None


app = FastAPI(
    title=".",
    version="0.1.0",
    docs_url=_docs_flag("docs_url", "/docs"),
    redoc_url=_docs_flag("redoc_url", "/redoc"),
    openapi_url=_docs_flag("openapi_url", "/openapi.json"),
    lifespan=lifespan,
)

# Le frontend Angular (ng serve, :4200 en dev) tourne sur une origine
# distincte du backend (:8000) — sans ça, le navigateur bloque tout (curl ne
# le voit jamais, seul un vrai navigateur applique CORS). allow_credentials
# =True nécessaire pour l'en-tête Authorization ; True + wildcard "*" est
# interdit par la spec, d'où une liste explicite plutôt que allow_origins=["*"].
# ALLOWED_ORIGINS (CSV) permet de pointer vers le vrai domaine en prod, sans
# retoucher le code — absente, on reste sur le défaut dev.
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:4200").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/{channel}")
async def ws(socket: WebSocket, channel: str):
    # Pas de Request injectable ici : le scope ASGI est "websocket", pas
    # "http". WebSocket expose déjà .headers/.cookies/.query_params (même
    # interface que Request), donc il tient aussi le rôle de "request".
    ws_service: WsManager | None = xcore.services.get("ext.websocket")

    if ws_service:
        await ws_service.ws_endpoint(ws=socket, request=socket, channel=channel)


@app.get("/health")
async def health():
    return {"status": "ok"}
