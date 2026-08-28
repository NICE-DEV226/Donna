# googleService

Extension XCore — point d'entrée `ext.google` : gestion Gmail + Google
Calendar au nom d'un utilisateur ayant lié son compte Google.

**Volontairement stateless** : ce service ne connaît ni les utilisateurs ni
la base de données. Chaque appel reçoit un `access_token` déjà valide — la
résolution utilisateur → `OAuthAccount` → access_token (avec rafraîchissement
si expiré) est la responsabilité du plugin auth (actions IPC `xauth.google.*`),
seul détenteur des jetons chiffrés. `googleService` ne fait que composer les
appels HTTP vers Gmail et Calendar et gérer le cycle de vie `BaseService`
(client HTTP partagé).

## Fonctionnalités

**Gmail** (scope `gmail.modify`) :
- Messages : envoi (`send_email`), liste/lecture, corbeille/restauration,
  suppression permanente, gestion des labels, pièces jointes
- Threads : liste, lecture, corbeille, labels
- Labels : CRUD complet
- Drafts : CRUD + envoi
- Profil (`get_profile`)

**Google Calendar** :
- Agendas : liste, lecture, création, mise à jour, suppression, purge
  (`clear_calendar`)
- Événements : CRUD, déplacement entre agendas (`move_event`), création
  rapide en langage naturel (`quick_add_event`)
- Disponibilité (`query_freebusy`)

## Configuration

```yaml
services:
  extensions:
    google:
      module: extensions.googleService.service:GoogleServiceClient
      config:
        timeout: 10
```

## Utilisation (normalement uniquement depuis le plugin auth)

```python
google = self.get_service("ext.google")

await google.send_email(access_token, to="a@b.com", subject="Hi", body_text="...")
await google.create_event(access_token, {
    "summary": "Réunion",
    "start": {"dateTime": "2026-09-01T10:00:00+02:00"},
    "end": {"dateTime": "2026-09-01T11:00:00+02:00"},
})
```

Détail complet des méthodes dans [INTEGRATION.md](INTEGRATION.md).

## Gestion d'erreurs

Toute réponse 4xx/5xx de l'API Google lève `GoogleAPIError(status_code, detail)` :

```python
from googleService.errors import GoogleAPIError

try:
    await google.send_email(access_token, to="a@b.com", subject="Hi", body_text="...")
except GoogleAPIError as exc:
    logger.warning("Gmail error %s: %s", exc.status_code, exc.detail)
```

## Structure

```
googleService/
├── service.yaml          # Manifeste de l'extension
├── service.py             # GoogleServiceClient (BaseService) — point d'entrée
├── _http.py                # GoogleHTTPMixin — requête Bearer + gestion d'erreur commune
├── errors.py                 # GoogleAPIError
└── services/
    ├── gmail.py               # GmailMixin — messages, threads, labels, drafts
    └── calendar.py             # CalendarMixin — agendas, événements, freebusy
```

## Scopes OAuth requis

Voir `app/auth/src/providers/google.py` pour les scopes demandés au
consentement (`gmail.modify` a minima ; la suppression permanente de
message nécessite le scope restreint `https://mail.google.com/`, non
demandé par défaut).
