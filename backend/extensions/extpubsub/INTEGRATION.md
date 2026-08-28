# Intégration — extpubsub

## 1. Déclarer l'extension dans `integration.yaml`

```yaml
services:
  extensions:
    pubsub:
      module: extensions.extpubsub.service:PubSubClient
      config:
        provider: redis          # redis | hivemq | memory
        redis:
          url: ${PUBSUB_REDIS_URL}
          heartbeat: 0.01
          max_connections: 100
        # hivemq:
        #   url: ${PUBSUB_HIVEMQ_URL}
        #   username: ${PUBSUB_HIVEMQ_USER}
        #   password: ${PUBSUB_HIVEMQ_PASSWORD}
        # memory:
        #   heartbeat: 0.1
```

`provider` sélectionne l'implémentation active — une seule des sections
`redis`/`hivemq`/`memory` est utilisée à la fois, les autres peuvent être
omises.

## 2. Récupérer le service depuis un plugin

```python
class MyPlugin(XCorePlugin):
    async def on_load(self):
        self.pubsub = self.get_service("ext.pubsub")
```

## 3. API

> Les signatures ci-dessous reflètent le code réel de `service.py` — le
> `README.md` de ce dépôt documente une API antérieure (`identified=`,
> `msg=`, `await stream(...)`) qui ne correspond plus à l'implémentation
> actuelle ; se fier à cette page.

### `publish(channel, data) -> bool`

```python
ok = await self.pubsub.publish("alerts", {"user_id": "u1", "text": "Alerte !"})
```

Si `data` contient `user_id`, le message est aussi déposé dans l'inbox de
cet utilisateur (livraison différée à la reconnexion SSE).

### `publish_many(channels, data) -> dict[str, bool]`

```python
results = await self.pubsub.publish_many(["alerts", "audit"], {"text": "..."})
# → {"alerts": True, "audit": True}
```

### `bulk_publish(channel, identified, data) -> None`

Publie le même message à plusieurs `user_id`, un envoi par destinataire :

```python
await self.pubsub.bulk_publish("notification", ["u1", "u2"], {"text": "..."})
```

### `stream(channels, user_id, filter_key="user_id", unfiltered_channels=None) -> AsyncGenerator[str, None]`

Générateur asynchrone — ne pas `await` avant d'itérer :

```python
async for chunk in self.pubsub.stream(["chat", "notification"], user_id="u1"):
    yield chunk   # "event: <channel>\n<payload>"
```

`unfiltered_channels` : ensemble de canaux diffusés sans filtrage par
`user_id` (broadcast global/tenant) — à l'appelant de vérifier en amont que
l'abonné est autorisé sur ces canaux.

### `flush_inbox(user_id) -> list[dict]` / `inbox_count(user_id) -> int`

```python
pending = await self.pubsub.flush_inbox("u1")   # vide et retourne l'inbox
count = await self.pubsub.inbox_count("u1")      # sans vider
```

### `health_check() -> tuple[bool, str]`

```python
ok, msg = await self.pubsub.health_check()
```

## 4. Providers

| Provider | Config | Usage |
|---|---|---|
| `redis` | `redis.url`, `heartbeat`, `max_connections` | Production, multi-instance |
| `hivemq` | `hivemq.url`, `username`, `password` | MQTT / IoT / messagerie externe |
| `memory` | `memory.heartbeat` | Tests, développement local sans infra |

## 5. Variables d'environnement suggérées

```dotenv
PUBSUB_REDIS_URL=redis://localhost:6379/0
```

Ne jamais versionner d'URL Redis avec identifiants réels dans
`integration.yaml` — toujours passer par une variable d'environnement.
