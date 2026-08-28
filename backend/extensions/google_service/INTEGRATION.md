# Intégration — googleService

## 1. Déclarer l'extension dans `integration.yaml`

```yaml
services:
  extensions:
    google:
      module: extensions.googleService.service:GoogleServiceClient
      config:
        timeout: 10
```

## 2. Récupérer le service depuis un plugin

Ce service est pensé pour n'être consommé que par le plugin `auth` (seul
détenteur des access tokens Google déchiffrés) :

```python
class MyPlugin(XCorePlugin):
    async def on_load(self):
        self.google = self.get_service("ext.google")
```

Chaque méthode prend `access_token` en premier argument — jamais résolu par
`googleService` lui-même.

## 3. API Gmail

### `send_email(access_token, to, subject, body_text=None, body_html=None, *, cc=None, bcc=None)`
```python
await google.send_email(access_token, to="a@b.com", subject="Hi", body_text="Bonjour")
```

### `list_messages(access_token, *, query=None, label_ids=None, max_results=50, page_token=None, include_spam_trash=False)`
```python
data = await google.list_messages(access_token, query="from:x@y.com is:unread")
```

### `get_message(access_token, message_id, *, format="full")`
`format` : `full` | `metadata` | `minimal` | `raw`.

### `trash_message` / `untrash_message` / `delete_message(access_token, message_id)`
`delete_message` est une suppression **permanente**, irréversible — nécessite
le scope restreint `https://mail.google.com/` non demandé par défaut
(403 sinon). Préférer `trash_message`.

### `modify_message_labels(access_token, message_id, *, add_label_ids=None, remove_label_ids=None)`

### `get_attachment(access_token, message_id, attachment_id)`
Retourne `{"size": int, "data": <base64url>}` — décoder avec
`base64.urlsafe_b64decode`.

### Threads : `list_threads`, `get_thread`, `trash_thread`, `modify_thread_labels`
Mêmes conventions que les messages.

### Labels : `list_labels`, `get_label`, `create_label`, `update_label`, `delete_label`

### Drafts : `list_drafts`, `get_draft`, `create_draft`, `update_draft`, `send_draft`, `delete_draft`

### `get_profile(access_token)`
```python
profile = await google.get_profile(access_token)
# → {"emailAddress": "...", "messagesTotal": ..., "threadsTotal": ..., "historyId": "..."}
```

## 4. API Calendar

### Agendas : `list_calendar_list`, `get_calendar_list_entry`, `subscribe_calendar`,
`unsubscribe_calendar`, `create_calendar`, `get_calendar`, `update_calendar`,
`delete_calendar`, `clear_calendar`

### `list_events(access_token, calendar_id="primary", *, time_min=None, time_max=None, query=None, max_results=50, page_token=None, single_events=True, order_by="startTime")`
```python
events = await google.list_events(access_token, time_min="2026-09-01T00:00:00Z")
```

### `get_event` / `create_event` / `update_event` / `delete_event`
```python
await google.create_event(access_token, {
    "summary": "Réunion",
    "start": {"dateTime": "2026-09-01T10:00:00+02:00"},
    "end": {"dateTime": "2026-09-01T11:00:00+02:00"},
    "attendees": [{"email": "a@b.com"}],
}, send_updates="all")
```
`event` suit le schéma Event de l'API Google Calendar tel quel — aucune
validation applicative côté `googleService`. `send_updates` :
`"all"` | `"externalOnly"` | `"none"`.

### `move_event(access_token, event_id, destination_calendar_id, calendar_id="primary")`

### `quick_add_event(access_token, text, calendar_id="primary")`
Création en langage naturel (ex. `"Déjeuner demain midi"`).

### `query_freebusy(access_token, time_min, time_max, calendar_ids)`

## 5. Gestion d'erreurs

Toute réponse HTTP ≥ 400 lève `GoogleAPIError(status_code, detail)` — capturer
autour de chaque appel si l'appelant doit distinguer les cas (token expiré,
quota dépassé, ressource introuvable, etc.).

## 6. Health check

```python
ok, msg = await google.health_check()
```

## 7. Portée volontairement hors de ce service

- Résolution `user_id` → `OAuthAccount` → `access_token` (avec refresh) :
  plugin `auth`, actions IPC `xauth.google.*`.
- Stockage/chiffrement des tokens Google (Fernet, clé `OAUTH_TOKEN_KEY`) :
  plugin `auth` également.
