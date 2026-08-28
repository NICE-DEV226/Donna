# 🚀 XCore PubSub Extension

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Framework: XCore](https://img.shields.io/badge/Framework-XCore-red.svg)](https://github.com/traoreera/xcore)
[![Backend: Redis](https://img.shields.io/badge/Backend-Redis-red.svg)](https://redis.io/)
[![Backend: HiveMQ](https://img.shields.io/badge/Backend-HiveMQ-orange.svg)](https://www.hivemq.com/)

Une extension Pub/Sub flexible et performante pour le framework **XCore**, offrant une interface unifiée pour le message-passing via Redis, MQTT ou une implémentation In-Memory.

---

## 📖 Sommaire
- [✨ Fonctionnalités](#-fonctionnalités)
- [⚙️ Installation](#️-installation)
- [🛠️ Configuration XCore](#️-configuration-xcore)
- [🚀 Utilisation](#-utilisation)
- [🔌 Providers Supportés](#-providers-supportés)
- [📂 Structure du Projet](#-structure-du-projet)

---

## ✨ Fonctionnalités

- 🔄 **Multi-Provider** : Basculez entre Redis, HiveMQ ou Memory sans changer votre code.
- 📡 **Streaming SSE** : Support natif pour le streaming compatible *Server-Sent Events*.
- 🛡️ **Pydantic Driven** : Configuration validée et typée au démarrage de XCore.
- ⚡ **Asyncio Native** : Entièrement non-bloquant pour des performances optimales.
- 🧩 **XCore Action Support** : Méthodes décorées avec `@action` pour une invocation croisée entre plugins.

---

## ⚙️ Installation

Ajoutez les dépendances nécessaires à votre environnement XCore :

```bash
pip install redis gmqtt pydantic
```

---

## 🛠️ Configuration XCore

L'extension s'intègre directement dans votre fichier `xcore.yaml`. Elle s'attend à trouver sa configuration sous la clé `services.pubsub`.

### Exemple de configuration complète
```yaml
services:
  extensions:
    pubsub:
      provider: "redis" # Options: redis, hivemq, memory
      redis:
        url: "redis://localhost:6379/0"
        heartbeat: 0.01
      hivemq:
        url: "mqtt://broker.hivemq.com:1883"
        username: "admin"
        password: "password"
      memory:
        heartbeat: 0.1
```

---

## 🚀 Utilisation

Une fois configurée, l'extension est accessible via le conteneur de services de XCore.

### Publication de messages
```python
pubsub_service = get_service("ext.pubsub")
await pubsub_service.publish(
    channel="alerts", 
    identified="user_001", 
    msg="Alerte de sécurité !"
)
```

### Streaming de messages (SSE)
```python
# Utilisation dans un endpoint FastAPI ou similaire
pubsub_service = get_service("ext.pubsub")
stream_gen = await pubsub_service.stream(
    channel="chat", 
    identified="user_001"
)
async for event in stream_gen:
    yield event
```

---

## 🔌 Providers Supportés

| Provider | Clé Config | Usage Recommandé |
| :--- | :--- | :--- |
| **Redis** | `redis` | Production, haute disponibilité, clustering. |
| **HiveMQ** | `hivemq` | IoT, protocoles MQTT, messagerie externe. |
| **Memory** | `memory` | Tests unitaires, développement local sans infra. |

---

## 📂 Structure du Projet

```text
pubsub/
├── provider/
│   ├── base.py       # Interface abstraite
│   ├── redis.py      # Implémentation Redis (Pool, Error handling)
│   ├── hyvemq.py     # Implémentation MQTT/HiveMQ
│   ├── memory.py     # Implémentation locale (Asyncio Queue)
│   └── section.py    # Modèles Pydantic (Validation)
├── service.py        # Point d'entrée Extension XCore
└── plugin.yaml       # Manifeste du plugin
```

---

## 📄 Licence

Distribué sous la licence MIT. Voir `LICENSE` pour plus d'informations.
