# .

Projet xcore généré avec `xcli init`.

## Démarrage

```bash
pip install -r requirements.txt
xcli manager start --reload
```

## Endpoints

- API docs : http://localhost:8000/docs
- Health   : http://localhost:8000/health

## Commandes utiles

```bash
xcli plugin new <nom>        # Créer un plugin
xcli plugin list             # Lister les plugins
xcli health                  # Vérifier les services
xcli manager top             # Dashboard live
xcli migration init          # Initialiser Alembic
```
