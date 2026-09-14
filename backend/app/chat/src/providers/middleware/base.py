"""
Pipeline middleware autour des appels LLM — patron en oignon.

Contrat central : chaque middleware implémente `handle(ctx)` et appelle
`await ctx.next()` (0, 1 ou N fois) pour déléguer au reste de la chaîne
(middlewares plus internes puis cible). Rien d'autre n'est exécuté
automatiquement : un middleware qui veut du multi-usage (before/after,
retry, cache) compose lui-même ses appels à `ctx.next()`.

Deux formes d'appel :
- non-streaming : `handle(ctx)` retourne le dict (ou str pour chat()) ;
- streaming      : `handle(ctx)` retourne l'async-iterator potentiellement
                   enveloppé (chaque middleware wrapper son flux via
                   `stream(ctx, gen)`).

Pour simplifier les middlewares simples, une implémentation par défaut de
`handle()` compose les étapes optionnelles before/after/on_error/stream :
réécrire `handle` seulement pour les middlewares qui ont besoin de contrôler
le flow (retry, cache, circuit...).

Le pipeline expose la même interface que ProviderRouter (chat_with_tools,
chat_stream_with_tools, chat, chat_stream, aclose) pour pouvoir le remplacer
sans toucher aux appelants (tools.py, chat_routes.py).

Couche logique pure (in-process, sans ASGI) ; la couche HTTP (rate-limit)
est traitée à part dans http_middleware.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable


class LLMMiddlewareError(RuntimeError):
    """Classe de base des erreurs levées par le pipeline lui-même."""


class BudgetExceededError(LLMMiddlewareError):
    """Budget tokens dépassé avant l'appel — à transformer en réponse aimable
    par l'appelant (jamais en erreur 500)."""


# NOTE : CircuitOpenError vit dans resilience.py — il hérite à la fois de
# LLMMiddlewareError ET de ProviderUnavailableError pour que les replis du
# ProviderRouter (qui n'attrapent que ProviderUnavailableError) se déclenchent
# naturellement sur un court-circuit.


@dataclass
class LLMContext:
    """Contexte mutable d'un appel traversant le pipeline.

    Champs modifiés in-place par les middlewares pour que les middlewares
    suivants et la cible voient la version à jour.
    """

    provider: str = "ollama"
    model: str = ""
    messages: list[dict] = field(default_factory=list)
    tools: list[dict] | None = None
    images_b64: list[str] | None = None
    force_ollama: bool = False
    streaming: bool = False
    method: str = "chat_with_tools"  # chat_with_tools | chat

    # Observabilité
    request_id: str = ""
    started_ms: int = 0
    elapsed_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    attempts: int = 1
    tags: dict[str, str] = field(default_factory=dict)
    error: Exception | None = None

    # Fourni par le pipeline : appel au reste de la chaîne
    _next: Callable[[], Any] | None = None

    def now_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000

    async def next(self) -> Any:
        """Continue vers le middleware suivant / la cible. Réutilisable
        plusieurs fois (retry, repli, double-check)."""
        if self._next is None:
            raise LLMMiddlewareError("next() appelé hors d'un middleware actif")
        return await self._next()

    def to_span(self) -> dict:
        """Vue structurée de l'appel pour le tracing / logging."""
        return {
            "provider": self.provider,
            "model": self.model,
            "request_id": self.request_id,
            "streaming": self.streaming,
            "elapsed_ms": self.elapsed_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached": self.cached,
            "attempts": self.attempts,
            "error": repr(self.error) if self.error else None,
            "tags": dict(self.tags),
            "nb_messages": len(self.messages),
            "has_tools": bool(self.tools),
            "has_images": bool(self.images_b64),
            "force_ollama": self.force_ollama,
        }


class LLMMiddleware:
    """Brique du pipeline.

    Étapes optionnelles — l'implémentation par défaut de handle() les compose :
      before(ctx)             précède l'appel réel (budget, cache lookup...).
      after(ctx, result)      succède à l'appel réel non-streaming.
      stream(ctx, stream)     enveloppe le flux streaming.
      after_stream(ctx)       appelé après épuisement (ou erreur) du flux.
      on_error(ctx, exc)      intercepte une exception non-streaming.

    Middlewares à flow custom (cache, retry, circuit...) : réécrire handle().
    """

    name: str = "middleware"

    async def before(self, ctx: LLMContext) -> None:
        return None

    async def after(self, ctx: LLMContext, result: dict) -> dict:
        return result

    async def stream(self, ctx: LLMContext, stream: AsyncIterator[dict]) -> AsyncIterator[dict]:
        async for event in stream:
            yield event

    async def after_stream(self, ctx: LLMContext) -> None:
        return None

    async def on_error(self, ctx: LLMContext, exc: Exception) -> dict:
        raise exc

    async def handle(self, ctx: LLMContext) -> Any:
        """Composition par défaut des étapes. Réécrire pour contrôler le flow."""
        await self.before(ctx)
        if ctx.streaming:
            gen = await ctx.next()
            return self.stream(ctx, gen)
        try:
            result = await ctx.next()
        except Exception as exc:
            return await self.on_error(ctx, exc)
        return await self.after(ctx, result)


class LLMPipeline:
    """
    Chaîne de middlewares en oignon autour de la cible (ProviderRouter ou un
    autre pipeline).

    API de la cible :
      async chat_with_tools(messages, tools=None, images_b64=None,
                            force_ollama=False) → dict
      async chat_stream_with_tools(...) → AsyncIterator[dict]
      async chat(messages, images_b64=None) → str
      async chat_stream(messages, ...) → AsyncIterator[str]
      async aclose()

    Ordre : le premier middleware ajouté est le plus externe (handle exécuté
    en premier ; stream/after_stream enveloppe en dernier).
    """

    def __init__(
        self,
        target: Any,
        middlewares: list[LLMMiddleware] | None = None,
        provider_models: dict[str, str] | None = None,
    ) -> None:
        self._target = target
        self._middlewares: list[LLMMiddleware] = []
        self._provider_models = dict(provider_models or {})
        if middlewares:
            for mw in middlewares:
                self.add(mw)

    # ── Construction ────────────────────────────────────────────────────────

    def add(self, middleware: LLMMiddleware) -> "LLMPipeline":
        self._middlewares.append(middleware)
        return self

    @property
    def middlewares(self) -> list[LLMMiddleware]:
        return list(self._middlewares)

    @property
    def default_name(self) -> str:
        return self._target.default_name if hasattr(self._target, "default_name") else "ollama"

    def set_default(self, provider: Any | None, name: str) -> None:
        """Change le provider de génération en mémoire (endpoint /provider) —
        passe-plateau vers la cible si elle le supporte."""
        setter = getattr(self._target, "set_default", None)
        if setter is None:
            raise LLMMiddlewareError("la cible n'expose pas set_default")
        setter(provider, name)

    @property
    def ollama(self) -> Any:
        """Accès direct au provider Ollama pour les tâches légères."""
        if hasattr(self._target, "ollama"):
            return self._target.ollama
        raise LLMMiddlewareError("la cible n'expose pas .ollama")

    # ── Fabrication du contexte ─────────────────────────────────────────────

    def _make_ctx(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        images_b64: list[str] | None,
        force_ollama: bool,
        streaming: bool,
        method: str = "chat_with_tools",
    ) -> LLMContext:
        provider = self.default_name
        return LLMContext(
            provider=provider,
            model=self._provider_models.get(provider, ""),
            messages=[dict(m) for m in messages],
            tools=list(tools) if tools else None,
            images_b64=list(images_b64) if images_b64 else None,
            force_ollama=force_ollama,
            streaming=streaming,
            method=method,
        )

    # ── Chaîne ──────────────────────────────────────────────────────────────

    def _build_entry(self, ctx: LLMContext) -> Callable[[], Any]:
        target = self._target
        middlewares = self._middlewares

        if ctx.method == "chat":

            async def terminal() -> Any:
                if ctx.streaming:
                    return target.chat_stream(messages=ctx.messages, images_b64=ctx.images_b64)
                return await target.chat(messages=ctx.messages, images_b64=ctx.images_b64)

        else:

            async def terminal() -> Any:
                if ctx.streaming:
                    return target.chat_stream_with_tools(
                        ctx.messages,
                        tools=ctx.tools,
                        images_b64=ctx.images_b64,
                        force_ollama=ctx.force_ollama,
                    )
                return await target.chat_with_tools(
                    ctx.messages,
                    tools=ctx.tools,
                    images_b64=ctx.images_b64,
                    force_ollama=ctx.force_ollama,
                )

        def build(index: int) -> Callable[[], Any]:
            if index >= len(middlewares):
                return terminal

            mw = middlewares[index]
            inner = build(index + 1)

            async def step() -> Any:
                ctx._next = inner
                return await mw.handle(ctx)

            return step

        return build(0)

    # ── Interface publique ───────────────────────────────────────────────────

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        images_b64: list[str] | None = None,
        force_ollama: bool = False,
    ) -> dict:
        ctx = self._make_ctx(messages, tools, images_b64, force_ollama, streaming=False)
        ctx.started_ms = ctx.now_ms()
        entry = self._build_entry(ctx)
        ctx._next = None
        try:
            return await entry()
        except Exception as exc:
            ctx.error = exc
            raise
        finally:
            ctx.elapsed_ms = ctx.now_ms() - ctx.started_ms

    async def chat_stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        images_b64: list[str] | None = None,
        force_ollama: bool = False,
    ) -> AsyncIterator[dict]:
        ctx = self._make_ctx(messages, tools, images_b64, force_ollama, streaming=True)
        ctx.started_ms = ctx.now_ms()
        entry = self._build_entry(ctx)
        ctx._next = None

        async for event in await entry():
            yield event

        ctx.elapsed_ms = ctx.now_ms() - ctx.started_ms
        for mw in reversed(self._middlewares):
            await mw.after_stream(ctx)

    async def chat(
        self,
        messages: list[dict],
        images_b64: list[str] | None = None,
    ) -> str:
        ctx = self._make_ctx(messages, None, images_b64, False, streaming=False, method="chat")
        ctx.started_ms = ctx.now_ms()
        entry = self._build_entry(ctx)
        ctx._next = None
        try:
            return await entry()
        except Exception as exc:
            ctx.error = exc
            raise
        finally:
            ctx.elapsed_ms = ctx.now_ms() - ctx.started_ms

    async def chat_stream(
        self,
        messages: list[dict],
        images_b64: list[str] | None = None,
    ) -> AsyncIterator[str]:
        ctx = self._make_ctx(messages, None, images_b64, False, streaming=True, method="chat")
        ctx.started_ms = ctx.now_ms()
        entry = self._build_entry(ctx)
        ctx._next = None

        async for event in await entry():
            yield event

        ctx.elapsed_ms = ctx.now_ms() - ctx.started_ms
        for mw in reversed(self._middlewares):
            await mw.after_stream(ctx)

    async def aclose(self) -> None:
        await self._target.aclose()