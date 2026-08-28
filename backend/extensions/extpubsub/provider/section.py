from typing import Literal, Optional

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    url: str
    heartbeat: float = 0.01


class RedisConfig(ProviderConfig):
    # Ne jamais remettre une URL avec identifiants réels ici — c'est un
    # défaut Pydantic versionné dans git, pas un secret runtime. La vraie
    # URL de production doit venir uniquement d'une variable d'environnement
    # ou d'un secret manager, jamais d'`integration.yaml` versionné (audit
    # XPulse Constat 1 — identifiants Redis réels précédemment en dur ici et
    # dupliqués dans integration.yaml, exposés sur le remote git du dépôt).
    url: str = "redis://localhost:6379/0"
    # stream() ouvre un pubsub (donc une connexion dédiée du pool) par canal
    # souscrit — un seul client SSE avec les 3 canaux par défaut
    # (notification/alerts/broadcast, cf. erp/src/lib/sse-bridge.ts) en
    # consomme déjà 3 ; quelques onglets/reconnexions suffisent à épuiser un
    # pool trop petit (était 10, codé en dur — cf. MaxConnectionsError).
    max_connections: int = 100


class HivemqConfig(ProviderConfig):
    url: str = "mqtt://localhost:1883"
    username: Optional[str] = None
    password: Optional[str] = None


class MemoryConfig(BaseModel):
    heartbeat: float = 0.01


class PubSubConf(BaseModel):
    provider: Literal['redis', 'hivemq', 'memory'] = 'redis'
    url: Optional[str] = None
    heartbeat: float = 0.01
    redis: Optional[RedisConfig] = Field(default_factory=RedisConfig)
    hivemq: Optional[HivemqConfig] = None
    memory: Optional[MemoryConfig] = Field(default_factory=MemoryConfig)
