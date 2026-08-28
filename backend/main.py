from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from xcore import Xcore
from extensions.xwebsocket.main import WsManager


xcore = Xcore(config_path="integration.yaml")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await xcore.boot(app)

    print(xcore.plugins_lists)
    yield
    await xcore.shutdown()


app = FastAPI(
    title=".",
    version="0.1.0",
    lifespan=lifespan,
)

# Le frontend Angular (ng serve, :4200) tourne sur une origine distincte du
# backend (:8000) — sans ça, le navigateur bloque tout (curl ne le voit
# jamais, seul un vrai navigateur applique CORS). allow_credentials=True
# nécessaire pour l'en-tête Authorization ; True + wildcard "*" est interdit
# par la spec, d'où une liste explicite plutôt que allow_origins=["*"].
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
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
