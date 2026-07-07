# Enregistrer une application dans Cockpit Server

Ce guide explique comment rendre une application visible et pilotable depuis le dashboard Cockpit Server, en utilisant des **services systemd utilisateur** (`systemctl --user`).

## Principe

Cockpit Server affiche uniquement les services systemd **utilisateur** dont le fichier `.service` se trouve dans `~/.config/systemd/user/`. Il suffit de créer un fichier service dans ce dossier pour que l'application apparaisse automatiquement.

**Règles fondamentales :**
- Toujours utiliser `systemctl --user` (jamais `sudo systemctl` ou `/etc/systemd/system/`)
- **Ne jamais** définir `User=` ou `Group=` dans un service utilisateur (il s'exécute déjà sous l'utilisateur courant)
- Installer les fichiers dans `~/.config/systemd/user/`
- Utiliser `WantedBy=default.target` (pas `multi-user.target`)
- Toujours faire `daemon-reload` avant la première utilisation et après toute modification

## Créer un service systemd utilisateur

### 1. Créer le fichier service

```bash
mkdir -p ~/.config/systemd/user
nano ~/.config/systemd/user/mon-app.service
```

### 2. Contenu minimal

```ini
[Unit]
Description=Mon application
After=network.target

[Service]
Type=simple
WorkingDirectory=/chemin/vers/mon-app
ExecStart=/chemin/vers/mon-app/start.sh
Restart=on-failure
RestartSec=5
StandardOutput=append:/chemin/vers/mon-app/server.log
StandardError=append:/chemin/vers/mon-app/server.log

[Install]
WantedBy=default.target
```

### 3. Installer et démarrer

```bash
systemctl --user daemon-reload
systemctl --user enable --now mon-app.service
```

### 4. Vérifier

```bash
systemctl --user status mon-app.service
journalctl --user -u mon-app.service --tail=30
```

---

## Script de mise à jour

Créez un script `<app>-update.sh` dans le répertoire de l'application pour faciliter les mises à jour :

```bash
#!/bin/bash
set -e
SERVICE="mon-app.service"

echo "=== Mise à jour de Mon App ==="

# 1. Arrêter
 echo "[1/3] Arrêt du service..."
systemctl --user stop "$SERVICE"
echo "  ✓ Service arrêté"

# 2. Réinstaller/Mettre à jour (spécifique à l'application)
echo "[2/3] Réinstallation..."
# Remplacer par les commandes spécifiques : pip install, npm install, git pull, etc.
echo "  ✓ Réinstallé"

# 3. Redémarrer
echo "[3/3] Redémarrage du service..."
systemctl --user daemon-reload
systemctl --user start "$SERVICE"
sleep 2

# Vérification
if systemctl --user is-active --quiet "$SERVICE"; then
    echo "  ✓ Service actif"
    echo "  Logs: journalctl --user -u $SERVICE --tail=30 -f"
    exit 0
else
    echo "  ✗ Échec du démarrage du service"
    echo "  Logs: journalctl --user -u $SERVICE --no-pager -n 50"
    exit 1
fi
```

---

## Exemples complets

### Application Python (Flask/FastAPI)

```ini
[Unit]
Description=Mon API Flask
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/user/mon-api
ExecStart=/home/user/mon-api/venv/bin/python app.py
Restart=on-failure
RestartSec=5
Environment=FLASK_ENV=production
StandardOutput=append:/home/user/mon-api/server.log
StandardError=append:/home/user/mon-api/server.log

[Install]
WantedBy=default.target
```

### Application Node.js

```ini
[Unit]
Description=Mon app Node
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/user/mon-app
ExecStart=/usr/bin/node server.js
Restart=on-failure
RestartSec=5
Environment=NODE_ENV=production PORT=3000
StandardOutput=append:/home/user/mon-app/server.log
StandardError=append:/home/user/mon-app/server.log

[Install]
WantedBy=default.target
```

### Script bash en boucle

```ini
[Unit]
Description=Mon worker
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/user/worker
ExecStart=/home/user/worker/worker.sh
Restart=always
RestartSec=5
StandardOutput=append:/home/user/worker/worker.log
StandardError=append:/home/user/worker/worker.log

[Install]
WantedBy=default.target
```

---

## Applications Electron en mode headless

Les applications basées sur Electron (AionUi, VS Code, etc.) nécessitent des flags spécifiques pour fonctionner sans serveur d'affichage :

| Flag | But |
|------|-----|
| `--no-sandbox` | Requise sur Linux en root/WSL |
| `--headless=new` | Nouveau mode headless (non obsolète) |
| `--disable-gpu` | Pas de matériel GPU disponible |
| `--disable-dev-shm-usage` | Éviter les problèmes de mémoire partagée |
| `--remote` | Exposer l'interface web pour un accès distant |

**Exemple ExecStart :**
```ini
ExecStart=/usr/bin/AionUi --no-sandbox --headless=new --webui --remote --disable-gpu --disable-dev-shm-usage
```

---

## Options utiles

| Directive | Description |
|---|---|
| `After=network.target` | Attendre que le réseau soit disponible |
| `Restart=on-failure` | Redémarre uniquement en cas d'erreur |
| `Restart=always` | Redémarre systématiquement |
| `RestartSec=5` | Délai avant redémarrage (secondes) |
| `Environment=KEY=VAL` | Variable d'environnement |
| `EnvironmentFile=/path/.env` | Charger les variables depuis un fichier |
| `ExecStartPre=/cmd` | Commande exécutée avant le démarrage |
| `ExecStop=/cmd` | Commande d'arrêt personnalisée |
| `StandardOutput=append:...` | Rediriger la sortie standard vers un fichier |
| `StandardError=append:...` | Rediriger la sortie d'erreur vers un fichier |

---

## Commandes de référence

```bash
# Recharger après modification d'un fichier .service
systemctl --user daemon-reload

# Gérer un service
systemctl --user start mon-app
systemctl --user stop mon-app
systemctl --user restart mon-app
systemctl --user status mon-app

# Activer au démarrage / désactiver
systemctl --user enable mon-app
systemctl --user disable mon-app

# Voir les logs
journalctl --user -u mon-app -f
journalctl --user -u mon-app --no-pager -n 50
```

---

## Pièges courants

### WSL / Environnements sans XDG_RUNTIME_DIR

Sur WSL ou tout environnement où `XDG_RUNTIME_DIR` n'est pas défini, `systemctl --user` échoue avec :
```
Failed to connect to bus: No medium found
```

**Solution :** Exporter la variable avant chaque appel à `systemctl --user` :
```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
```

Ajoutez cette ligne à votre `~/.bashrc` si vous utilisez `systemctl --user` régulièrement.

### Session utilisateur et services persistants

Si `systemctl --user` retourne une erreur ou rien du tout, la session utilisateur peut nécessiter :
```bash
sudo loginctl enable-linger <user>
```
Cela permet aux services utilisateur de persister après la déconnexion.

---

## Supprimer un service

```bash
systemctl --user stop mon-app
systemctl --user disable mon-app
rm ~/.config/systemd/user/mon-app.service
systemctl --user daemon-reload
```

L'application disparaîtra automatiquement du dashboard Cockpit Server.
