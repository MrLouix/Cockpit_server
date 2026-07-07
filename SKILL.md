# Enregistrer une application dans Cockpit Server

Ce guide explique comment rendre une application visible et pilotable depuis le dashboard Cockpit Server.

## Principe

Cockpit Server affiche uniquement les services systemd **utilisateur** dont le fichier `.service` se trouve dans `~/.config/systemd/user/`. Il suffit de creer un fichier service dans ce dossier pour que l'application apparaisse automatiquement.

## Creer un service systemd utilisateur

### 1. Creer le fichier service

```bash
mkdir -p ~/.config/systemd/user
nano ~/.config/systemd/user/mon-app.service
```

### 2. Contenu minimal

```ini
[Unit]
Description=Mon application

[Service]
Type=simple
WorkingDirectory=/chemin/vers/mon-app
ExecStart=/chemin/vers/mon-app/start.sh
Restart=on-failure

[Install]
WantedBy=default.target
```

### 3. Activer et demarrer

```bash
systemctl --user daemon-reload
systemctl --user enable mon-app
systemctl --user start mon-app
```

## Exemples

### Application Python (Flask/FastAPI)

```ini
[Unit]
Description=Mon API Flask

[Service]
Type=simple
WorkingDirectory=/home/user/mon-api
ExecStart=/home/user/mon-api/venv/bin/python app.py
Restart=on-failure
Environment=FLASK_ENV=production

[Install]
WantedBy=default.target
```

### Application Node.js

```ini
[Unit]
Description=Mon app Node

[Service]
Type=simple
WorkingDirectory=/home/user/mon-app
ExecStart=/usr/bin/node server.js
Restart=on-failure
Environment=NODE_ENV=production PORT=3000

[Install]
WantedBy=default.target
```

### Script bash en boucle

```ini
[Unit]
Description=Mon worker

[Service]
Type=simple
WorkingDirectory=/home/user/worker
ExecStart=/home/user/worker/worker.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

## Options utiles

| Directive | Description |
|---|---|
| `Restart=on-failure` | Redemarre uniquement en cas d'erreur |
| `Restart=always` | Redemarre systematiquement |
| `RestartSec=5` | Delai avant redemarrage (secondes) |
| `Environment=KEY=VAL` | Variable d'environnement |
| `EnvironmentFile=/path/.env` | Charger les variables depuis un fichier |
| `ExecStartPre=/cmd` | Commande executee avant le demarrage |
| `ExecStop=/cmd` | Commande d'arret personnalisee |

## Commandes de reference

```bash
# Recharger apres modification d'un fichier .service
systemctl --user daemon-reload

# Gerer un service
systemctl --user start mon-app
systemctl --user stop mon-app
systemctl --user restart mon-app
systemctl --user status mon-app

# Activer au demarrage / desactiver
systemctl --user enable mon-app
systemctl --user disable mon-app

# Voir les logs
journalctl --user -u mon-app -f
```

## Supprimer un service

```bash
systemctl --user stop mon-app
systemctl --user disable mon-app
rm ~/.config/systemd/user/mon-app.service
systemctl --user daemon-reload
```

L'application disparaitra automatiquement du dashboard Cockpit Server.
