# Pont MCP WhatsApp (donna_whatsapp) — configuration

Ce document explique **en pratique** comment configurer **Donna ←→ WhatsApp**
via le pont stdio (`extensions.mcp_bridge`). Le serveur est un binaire Go
indépendant (`donata`, module `github.com/donna-hub/donata` — paquet natif
`github.com/donna-hub/donata/cmd/donata`), lancé en **stdio** à côté des
autres ponts natifs déjà configurés (duckduckgo, pdf, excel, word) et
appelé par le LLM via des **outils natifs `wa_*`** dans `tool_context`.

---

## 1. Ce que fait le pont — en une phrase

Donna expose 10 outils `wa_*` au LLM (`web_search.py`-style) ; chaque appel
passe par `ctx.mcp.call_tool("donna_whatsapp", "<wa_natif>", {"…"})` qui
démarre le serveur stdio déclaré ci-dessous et lui demande d'exécuter
l'action sur le compte WhatsApp réel (appairage, envoi, médias, réactions…).

Table des 10 outils exposés au LLM (définis dans
`app/chat/src/tools.py` — schémas `TOOLS_SCHEMA` + handlers `_wa_*`) :

| Outil LLM | Serveur natif stdio | But |
|---|---|---|
| `wa_status` | `wa_status` | État identité : appairage, connexion, transport |
| `wa_chats` | `wa_chats` | Liste conversations : non-lus, dernier message |
| `wa_context` | `wa_context` | Fenêtre de messages d'un chat |
| `wa_search` | `wa_search` | Recherche contacts/messages |
| `wa_send` | `wa_send` | Envoi texte (draft/auto, anti-spam) |
| `wa_media` | `wa_media` | Envoi image/document |
| `wa_voice` | `wa_voice` | Envoi note vocale .opus/.ogg |
| `wa_react` | `wa_react` | Réaction émoticône |
| `wa_read` | `wa_read` | Marquer comme lu |
| `wa_admin_approve` | `wa_admin_approve` | Approuver un ticket d'envoi (draft) |

---

## 2. Comment le configurer — les 3 étapes

### Étape 1 — Compiler le binaire `donata` (Go ≥ 1.22 requis)

```sh
cd backend/data/mcp_whatsapp
make build            # crée ./donata (binaire stdio ~10 Mo)
# ou à la main :
#   go build -o donata ./cmd/donata
```

> Le binaire est **pur stdio MCP** : la commande d'exécution est
> `./donata serve` (démarré par le pont en stdio, jamais à la main).

### Étape 2 — Déclarer le serveur dans `integration.yaml`

Le pont MCP (`extensions.mcp_bridge`) lit `integration.yaml` à la racine
du backend (clé `extensions.mcp_bridge.config.servers`) et démarre chaque
serveur en stdio. Ajoutez sous le bloc `servers:` (après `duckduckgo`) :

```yaml
        donna_whatsapp:
          command: /home/eliezer/devs/donna/backend/data/mcp_whatsapp/donata
          args: ["serve"]
          env:
            DONATA_BASE_DIR: data/donna_whatsapp
            DONATA_TELEPHONE: "+33600000000"
            DONATA_TRANSPORT: memory        # memory (démo sans numéro) OU whatsmeow (réel)
            DONATA_DATA_DIR: data/donna_whatsapp
            DONATA_LOG_LEVEL: info
            DONATA_WEBHOOK_URL: ""
            DONATA_WEBHOOK_TOKEN: ""
          cwd: /home/eliezer/devs/donna/backend
```

Variables importantes :

| Variable | Rôle |
|---|---|
| `DONATA_TRANSPORT` | `memory` (démo : files démo factices, tests LLM sans numéro réel) ou `whatsmeow` (appairage WhatsApp vrai via QR à la 1re connexion) |
| `DONATA_BASE_DIR` / `DONATA_DATA_DIR` | Racine des données (conversations, médias) — créer le dossier `data/donna_whatsapp/` |
| `DONATA_TELEPHONE` | Numéro (format international `+33…`) — requis uniquement en transport `whatsmeow` |
| `DONATA_WEBHOOK_URL` / `DONATA_WEBHOOK_TOKEN` | Webhook d'inbound (messages entrants vers Donna) — laisser `""` en mémoire |

### Étape 3 — Redémarrer le pont

Après avoir édité `integration.yaml`, redémarrez le processus qui boote le
pont MCP (`make dev` / uvicorn / le service qui charge `extensions.mcp_bridge`).
Au boot, le pont démarre `donata serve` en stdio et re-liste ses outils
(`wa_status`, `wa_chats`, …) automatiquement via la handshake MCP — aucune
clé API à ajouter.

---

## 3. Tester que tout est branché

Le plus court (la preuve que le stdio répond) :

```sh
echo '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{}}' \
  | ./backend/data/mcp_whatsapp/donata serve
```

Vous devez voir : `"serverInfo":{"name":"donata","version":"0.1.0"}` + `protocolVersion`.

Côté LLM (Donna), testez en langage naturel : *« Quels sont mes chats
WhatsApp les plus récents ? »* → Donna déclenche `wa_chats`, puis s'il y a
du concret : *« Marque X comme bien reçu puis envoie-lui ce texte en mode
draft »* → `wa_read` + `wa_send`.

---

## 4. Draft vs auto (anti-spam / approbation humaine)

Hérité de `web_search.py`-style et du pont :

- **`wa_send` / `wa_media` / `wa_voice`** passent par une **politique
  anti-spam** : mode `draft` (défaut) crée un **ticket d'envoi** à approuver
  via `wa_admin_approve` (l'agent LLM voit le résumé, un humain valide sur
  le dashboard) ; mode `auto` part directement (réservé aux appels
  explicitement autorisés).
- **`wa_react`** : émoticônes whitelistées (`👌 ✅ 👍 ❤️ 😂 🤔 😮 🙏 🎉 📎`).
- **`wa_send`** : max ~1000 caractères, une question par tour.

---

## 5. Dépannage

| Symptôme | Cause probable | Correctif |
|---|---|---|
| `wa_status` → « ext.mcp_bridge non connecté » | Le pont n'a pas booté ce serveur | Redémarrer le pont ; vérifier `data/mcp_whatsapp/donata` existe (`ls -l`) |
| Erreur `exec: "donata": file not found` | Binaire absent / mauvais chemin | Étape 1 (build) + corriger `command:` dans integration.yaml |
| `wa_send` bloque toujours en draft | Politique anti-spam active | `wa_admin_approve(ticket=…, approve=true)` OU `mode: auto` si autorisé |
| Rien ne « part » en `memory` | Transport mémoire = simule sans réseau | C'est normal : passer `DONATA_TRANSPORT: whatsmeow` + `DONATA_TELEPHONE` pour le vrai numéro |
| QR au 1er lancement (whatsmeow) | Appairage requis | Scanner le QR affiché dans les logs stdio du pont |

---

## 6. Vue d'ensemble (flux)

```
LLM (Donna)
  │  ctx.mcp.call_tool("donna_whatsapp", "wa_chats", {…})
  ▼
extensions.mcp_bridge  (integration.yaml → servers.donna_whatsapp)
  │  stdio : démarre  ./donata serve
  ▼
donata (Go, github.com/donna-hub/donata)
  │  wa_status / wa_chats / wa_context / wa_search / wa_send /
  │  wa_media / wa_voice / wa_react / wa_read / wa_admin_approve
  ▼
Transport : memory (démo) | whatsmeow (WhatsApp réel — appairage QR, envoi/réception)
```

Racine du code côté pont : `app/chat/src/tools.py` (schémas `TOOLS_SCHEMA` +
handlers `_wa_*`). Racine du serveur : `data/mcp_whatsapp/` (binaire `donata`,
module Go `github.com/donna-hub/donata`).
