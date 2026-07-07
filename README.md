# Cockpit Server

Dashboard web pour monitorer et piloter les services d'un serveur Linux (conteneurs Docker, services systemd utilisateur, scripts bash).

## Fonctionnalites

- **Metriques systeme** : CPU, RAM, disque, uptime (temps reel)
- **Conteneurs Docker** : statut, start/stop/restart, ports exposes
- **Services systemd utilisateur** : statut, start/stop/restart
- **Scripts bash** : raccourcis vers des scripts .sh, execution depuis l'interface
- **Groupes** : regrouper des services pour les piloter ensemble
- **Masquage** : masquer les services non pertinents du dashboard

## Prerequis

- Python 3.8+
- `pip install flask psutil`
- Docker (optionnel, pour la gestion des conteneurs)

## Installation

```bash
git clone https://github.com/MrLouix/Cockpit_server.git
cd Cockpit_server
pip install flask psutil
python3 app.py
```

Le dashboard est accessible sur `http://localhost:5000`.

## Architecture

```
app.py                      # Backend Flask (API REST)
index.html                  # Frontend (HTML/JS, single page)
support.js                  # Framework UI
SKILL.md                    # Guide : enregistrer une app dans le dashboard
systemd-user-service.md     # Skill Claude Code : creation automatisee de services
```

## API

| Endpoint | Methode | Description |
|---|---|---|
| `/api/status` | GET | Statut complet (metriques, services, scripts, groupes) |
| `/api/docker/<action>/<name>` | POST | Action sur un conteneur Docker |
| `/api/app/<action>` | POST | Action sur un service systemd utilisateur |
| `/api/scripts/run/<name>` | POST | Executer un script |
| `/api/shortcuts` | GET/POST | Lister/ajouter des raccourcis scripts |
| `/api/shortcuts/<name>` | DELETE | Supprimer un raccourci |
| `/api/groups` | GET/POST | Lister/creer des groupes |
| `/api/groups/<id>` | PUT/DELETE | Modifier/supprimer un groupe |
| `/api/groups/<id>/<action>` | POST | Action groupee (start/stop/restart) |
| `/api/hidden` | GET/POST/DELETE | Gerer les services masques |

## Configuration

Les fichiers de configuration sont stockes dans `~/.config/server_cockpit/` :
- `groups.json` : groupes de services
- `hidden.json` : services masques

Les services systemd utilisateur affiches sont ceux dont le fichier `.service` se trouve dans `~/.config/systemd/user/`.

## Ajouter une application au dashboard

Pour qu'une application apparaisse dans le dashboard, il suffit de creer un service systemd utilisateur. Le guide complet est dans [SKILL.md](SKILL.md).

En resume :

```bash
# Creer le fichier service
cat > ~/.config/systemd/user/mon-app.service << 'EOF'
[Unit]
Description=Mon application

[Service]
Type=simple
WorkingDirectory=/chemin/vers/mon-app
ExecStart=/chemin/vers/mon-app/start.sh
Restart=on-failure

[Install]
WantedBy=default.target
EOF

# Activer et demarrer
systemctl --user daemon-reload
systemctl --user enable mon-app
systemctl --user start mon-app
```

L'application apparait automatiquement dans le dashboard. Voir [SKILL.md](SKILL.md) pour des exemples Python, Node.js et les options avancees.
