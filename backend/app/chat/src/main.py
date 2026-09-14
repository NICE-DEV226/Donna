from __future__ import annotations

from fastapi import APIRouter
from xcore.sdk import AutoDispatchMixin, TrustedBase, get_logger

from .models import Base
from .ollama_client import OllamaClient
from .providers.anthropic_provider import AnthropicProvider
from .providers.middleware import (
    AuditMiddleware,
    BudgetMiddleware,
    CacheMiddleware,
    CircuitBreakerProvider,
    LLMPipeline,
    LoggingMiddleware,
    RetryMiddleware,
    TraceMiddleware,
    UsageMiddleware,
)
from .providers.openai_compat_provider import OpenAICompatProvider
from .providers.router import ProviderRouter
from .routes.chat_routes import chats_router
from .transcribe import Transcriber

logger = get_logger("chat.plugin")


class Plugin(AutoDispatchMixin, TrustedBase):
    async def on_load(self) -> None:
        self._db = self.get_service("db")
        self._storage = self.get_service("ext.storage")
        self._rag = self.get_service("ext.rag")
        self._websocket = self.get_service("ext.websocket")
        try:
            self._google = self.get_service("ext.google")
        except Exception as exc:
            logger.warning("chat : ext.google indisponible (%s) — outils Gmail/Calendar désactivés.", exc)
            self._google = None
        try:
            self._mcp = self.get_service("ext.mcp_bridge")
        except Exception as exc:
            logger.warning("chat : ext.mcp_bridge indisponible (%s) — outils documents désactivés.", exc)
            self._mcp = None

        async with self._db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        cfg = self.ctx.config or {}
        env = self.ctx.env or {}
        ollama_cfg = cfg.get("ollama", {})
        system_prompt = ollama_cfg.get("system_prompt")

        self._ollama = OllamaClient(
            base_url=ollama_cfg.get("base_url", "http://localhost:11434"),
            model=ollama_cfg.get("model", "qwen2.5:3b"),
            vision_model=ollama_cfg.get("vision_model", "qwen2.5vl:3b"),
            system_prompt=system_prompt,
            timeout=float(ollama_cfg.get("timeout_seconds", 120)),
        )

        llm_provider_name = cfg.get("llm", {}).get("provider", "ollama")
        default_provider = self._build_default_provider(cfg, env, system_prompt)
        active_name = llm_provider_name if default_provider else "ollama"
        vision_provider = self._build_vision_provider(cfg, env, system_prompt)
        self._provider_router = ProviderRouter(
            self._ollama, default_provider, default_name=active_name, vision_provider=vision_provider
        )

        # Pipeline middleware LLM — configuré dans plugin.yaml sous llm:middleware:.
        # Les middlewares s'exécutent en oignon autour du router (voir
        # providers/middleware/base.py). Le circuit breaker est appliqué PAR
        # SLOT (cloud/vision) et non à l'échelle du pipeline : il faut être
        # côté provider pour connaître la cause exacte d'un échec — et donc
        # l'ennoblir en repli Ollama (CircuitOpenError hérite de
        # ProviderUnavailableError).
        middleware_cfg = cfg.get("llm", {}).get("middleware", {}) or {}
        self._pipeline = self._build_pipeline(
            self._provider_router,
            middleware_cfg,
            system_prompt=system_prompt,
            default_provider=default_provider,
            vision_provider=vision_provider,
        )

        # Fermé sur cfg/env/system_prompt — permet de reconstruire un
        # provider par son seul nom, à la demande (voir POST
        # /app/chat/provider dans chat_routes.py, pour changer le provider
        # actif à chaud sans éditer plugin.yaml ni redémarrer).
        def build_provider(name: str):
            return self._build_default_provider(cfg, env, system_prompt, provider_name=name)

        whisper_cfg = cfg.get("whisper", {})
        self._transcriber = Transcriber(
            model_size=whisper_cfg.get("model_size", "small"),
            device=whisper_cfg.get("device", "cpu"),
        )

        self.app = APIRouter()
        self.app.include_router(
            chats_router(
                self._db,
                self._pipeline,
                self._storage,
                self._transcriber,
                self._rag,
                self._websocket,
                self._google,
                self.call_plugin,
                self._mcp,
                build_provider,
            )
        )

        # Endpoint d'observabilité : dernières spans LLM du pipeline (si le
        # middleware tracing est monté). Sans auth stricte ici — lecture seule
        # de métadonnées, le vrai usage est côté logs structurés.
        if hasattr(self, "_trace"):
            @self.app.get("/traces", summary="Dernières spans LLM du pipeline", tags=["observability"])
            async def traces(limit: int = 50):
                return {"spans": self._trace.spans(limit=limit)}

        self._pipeline_default_name = active_name
        vision_name = "groq" if vision_provider else "ollama"
        logger.info("chat plugin prêt — génération=%s, vision=%s, embed=ollama", active_name, vision_name)

    def _build_default_provider(
        self, cfg: dict, env: dict, system_prompt: str | None, provider_name: str | None = None
    ):
        """
        Routage par tâche : embeddings/vision restent sur Ollama (câblés
        ailleurs) ; la génération finale texte va au provider cloud choisi en
        config s'il a une clé API — sinon on reste sur Ollama (dégradation
        propre, pas de crash si aucune clé n'est configurée).

        provider_name : override explicite (voir POST /app/chat/provider,
        set_provider dans chat_routes.py) — sinon lu dans plugin.yaml.
        """
        llm_cfg = cfg.get("llm", {})
        provider_name = provider_name or llm_cfg.get("provider", "ollama")
        # Défaut bien plus bas que celui du SDK (600s) : un appel qui traîne
        # ne doit pas bloquer tout le flux SSE en silence — voir docstring
        # des providers pour l'incident qui a motivé ce paramètre.
        timeout = float(llm_cfg.get("timeout_seconds", 30))

        if provider_name == "anthropic":
            api_key = env.get("ANTHROPIC_API_KEY")
            if not api_key:
                logger.warning("llm.provider=anthropic mais ANTHROPIC_API_KEY absente — reste sur Ollama.")
                return None
            anthropic_cfg = llm_cfg.get("anthropic", {})
            return AnthropicProvider(
                api_key=api_key,
                model=anthropic_cfg.get("model", "claude-sonnet-5"),
                system_prompt=system_prompt,
                max_tokens=int(anthropic_cfg.get("max_tokens", 4096)),
                timeout=timeout,
            )

        if provider_name == "openai":
            api_key = env.get("OPENAI_API_KEY")
            if not api_key:
                logger.warning("llm.provider=openai mais OPENAI_API_KEY absente — reste sur Ollama.")
                return None
            openai_cfg = llm_cfg.get("openai", {})
            return OpenAICompatProvider(
                api_key=api_key,
                model=openai_cfg.get("model", "gpt-4o-mini"),
                system_prompt=system_prompt,
                timeout=timeout,
            )

        if provider_name == "grok":
            api_key = env.get("XAI_API_KEY")
            if not api_key:
                logger.warning("llm.provider=grok mais XAI_API_KEY absente — reste sur Ollama.")
                return None
            grok_cfg = llm_cfg.get("grok", {})
            return OpenAICompatProvider(
                api_key=api_key,
                model=grok_cfg.get("model", "grok-2-latest"),
                base_url=grok_cfg.get("base_url", "https://api.x.ai/v1"),
                system_prompt=system_prompt,
                timeout=timeout,
            )

        # Groq (api.groq.com, inference rapide sur modèles open-source type
        # Llama/Mixtral) — à ne pas confondre avec "grok" (xAI) ci-dessus.
        if provider_name == "groq":
            api_key = env.get("GROQ_API_KEY")
            if not api_key:
                logger.warning("llm.provider=groq mais GROQ_API_KEY absente — reste sur Ollama.")
                return None
            groq_cfg = llm_cfg.get("groq", {})
            return OpenAICompatProvider(
                api_key=api_key,
                model=groq_cfg.get("model", "openai/gpt-oss-120b"),
                base_url=groq_cfg.get("base_url", "https://api.groq.com/openai/v1"),
                system_prompt=system_prompt,
                timeout=timeout,
            )

        # OpenRouter (openrouter.ai) — concentrateur multi-modèles, API
        # compatible OpenAI. Même client que openai/grok/groq.
        if provider_name == "openrouter":
            api_key = env.get("OPENROUTER_API_KEY")
            if not api_key:
                logger.warning("llm.provider=openrouter mais OPENROUTER_API_KEY absente — reste sur Ollama.")
                return None
            or_cfg = llm_cfg.get("openrouter", {})
            return OpenAICompatProvider(
                api_key=api_key,
                model=or_cfg.get("model", "openrouter/auto"),
                base_url=or_cfg.get("base_url", "https://openrouter.ai/api/v1"),
                system_prompt=system_prompt,
                timeout=timeout,
            )

        # Gemini expose une couche de compatibilité OpenAI — même client que
        # openai/grok/groq, seuls base_url/model/clé changent.
        if provider_name == "gemini":
            api_key = env.get("GEMINI_API_KEY")
            if not api_key:
                logger.warning("llm.provider=gemini mais GEMINI_API_KEY absente — reste sur Ollama.")
                return None
            gemini_cfg = llm_cfg.get("gemini", {})
            return OpenAICompatProvider(
                api_key=api_key,
                model=gemini_cfg.get("model", "gemini-2.5-flash"),
                base_url=gemini_cfg.get(
                    "base_url", "https://generativelanguage.googleapis.com/v1beta/openai/"
                ),
                system_prompt=system_prompt,
                timeout=timeout,
            )

        return None

    def _build_vision_provider(self, cfg: dict, env: dict, system_prompt: str | None):
        """
        Provider vision dédié, indépendant du provider texte par défaut — un
        modèle texte-seul (ex: openai/gpt-oss-120b sur Groq) ne "voit" pas
        d'image, il faut un modèle spécifiquement multimodal. Retourne None
        (repli Ollama, voir ProviderRouter) si non configuré ou clé absente.

        Vérifié en pratique (2026-08) : qwen/qwen3.6-27b et qwen/qwen3.8-27b
        sur Groq supportent à la fois vision ET tool-calling — contrairement
        aux modèles vision d'Ollama qui refusent tools+vision ensemble.
        """
        vision_cfg = cfg.get("llm", {}).get("vision", {})
        provider_name = vision_cfg.get("provider")
        if not provider_name:
            return None
        timeout = float(cfg.get("llm", {}).get("timeout_seconds", 30))

        if provider_name == "groq":
            api_key = env.get("GROQ_API_KEY")
            if not api_key:
                logger.warning("llm.vision.provider=groq mais GROQ_API_KEY absente — repli Ollama pour la vision.")
                return None
            return OpenAICompatProvider(
                api_key=api_key,
                model=vision_cfg.get("model", "qwen/qwen3.6-27b"),
                base_url=vision_cfg.get("base_url", "https://api.groq.com/openai/v1"),
                system_prompt=system_prompt,
                timeout=timeout,
            )

        logger.warning("llm.vision.provider=%s inconnu — repli Ollama pour la vision.", provider_name)
        return None

    def _build_pipeline(
        self,
        router: ProviderRouter,
        mw_cfg: dict,
        system_prompt: str | None,
        default_provider=None,
        vision_provider=None,
    ) -> LLMPipeline:
        """
        Assemble le pipeline middleware LLM à partir de la config plugin.yaml
        (section llm:middleware:). Les middlewares sont ajoutés dans l'ordre
        résilience → observabilité — le premier ajouté est le plus externe.

        Le circuit breaker est appliqué aux SLOTS (default/vision) AVANT le
        router : pour qu'un court-circuit aboutisse au repli Ollama, l'erreur
        doit être vue côté provider (CircuitOpenError est une sous-classe de
        ProviderUnavailableError, ce que le router intercepte).
        """
        llm_cfg = self.ctx.config.get("llm", {}) or {}
        ollama_cfg = self.ctx.config.get("ollama", {}) or {}
        vision_cfg = llm_cfg.get("vision", {}) or {}
        provider_models: dict[str, str] = {}
        if getattr(self, "_ollama", None):
            provider_models["ollama"] = ollama_cfg.get("model", "qwen2.5:3b")
        for pname in ("anthropic", "openai", "grok", "groq", "openrouter", "gemini"):
            pcfg = llm_cfg.get(pname, {}) or {}
            if pcfg.get("model"):
                provider_models[pname] = pcfg["model"]
        if vision_cfg.get("provider") and vision_cfg.get("model"):
            provider_models[f"{vision_cfg['provider']}#vision"] = vision_cfg["model"]

        # ── Circuit breaker par slot ───────────────────────────────────────
        cb_cfg = mw_cfg.get("circuit_breaker", {}) or {}
        if cb_cfg.get("enabled", True):
            failure_threshold = int(cb_cfg.get("failure_threshold", 5))
            recovery_timeout = float(cb_cfg.get("recovery_timeout", 60))
            wrapped_default = None
            if default_provider is not None:
                wrapped_default = CircuitBreakerProvider(
                    default_provider,
                    name="default",
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                )
            wrapped_vision = None
            if vision_provider is not None:
                wrapped_vision = CircuitBreakerProvider(
                    vision_provider,
                    name="vision",
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                )
            router.set_default(wrapped_default, router.default_name)
            router._vision = wrapped_vision
            logger.info(
                "chat : circuit breaker actif (default:%s, vision:%s)",
                bool(wrapped_default),
                bool(wrapped_vision),
            )

        pipeline = LLMPipeline(router, provider_models=provider_models)

        # ── Observabilité (la plus externe → elle voit tout en réponse) ────
        audit_cfg = mw_cfg.get("audit", {}) or {}
        if audit_cfg.get("enabled", True):
            pipeline.add(
                AuditMiddleware(
                    verbose=bool(audit_cfg.get("verbose", False)),
                    audit_file=audit_cfg.get("file") or "data/chat_audit.jsonl",
                    block_on_injection=bool(audit_cfg.get("block_on_injection", False)),
                )
            )

        if mw_cfg.get("tracing", {}).get("enabled", True):
            self._trace = TraceMiddleware()
            pipeline.add(self._trace)

        if mw_cfg.get("logging", {}).get("enabled", True):
            pipeline.add(LoggingMiddleware(level=str(mw_cfg.get("logging", {}).get("level", "info"))))

        if mw_cfg.get("usage", {}).get("enabled", True):
            pipeline.add(UsageMiddleware())

        # ── Résilience (interne → touche la cible en dernier) ──────────────
        budget_cfg = mw_cfg.get("budget", {}) or {}
        if budget_cfg.get("enabled", True):
            pipeline.add(BudgetMiddleware(max_tokens_per_call=int(budget_cfg.get("max_tokens", 8000))))

        cache_cfg = mw_cfg.get("cache", {}) or {}
        if cache_cfg.get("enabled", True):
            pipeline.add(
                CacheMiddleware(
                    ttl_seconds=int(cache_cfg.get("ttl_seconds", 300)),
                    max_entries=int(cache_cfg.get("max_entries", 50)),
                )
            )

        retry_cfg = mw_cfg.get("retry", {}) or {}
        if retry_cfg.get("enabled", True):
            pipeline.add(
                RetryMiddleware(
                    max_attempts=int(retry_cfg.get("max_attempts", 2)),
                    backoff_base=float(retry_cfg.get("backoff_base", 1.0)),
                )
            )

        return pipeline

    async def on_unload(self) -> None:
        await self._pipeline.aclose()

    def get_router(self) -> APIRouter | None:
        return self.app
