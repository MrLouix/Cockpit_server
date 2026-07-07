#!/usr/bin/env python3
"""
server_cockpit — backend Flask
Requires: pip install flask psutil
Run:      python app.py   (port 5000)

Sécurité :
- Mot de passe sudo demandé une fois au lancement (getpass), gardé en RAM,
  injecté via stdin (sudo -S) → invisible dans ps aux.
- debug/reloader désactivés : le reloader relancerait le prompt sudo.
- Validation stricte des noms de services/scripts (anti path-traversal).
- Suppression de raccourcis limitée aux symlinks (jamais le vrai fichier).

Performance :
- cpu_percent non bloquant (warmup au boot).
- Sondes systemctl parallélisées (ThreadPoolExecutor).
- Cache TTL 2s sur la découverte de services.
- Actions de groupe parallélisées.
"""

import json, re, shutil, subprocess, time, socket, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, abort

app = Flask(__name__, static_folder="static")

SCRIPTS_DIR = Path.home() / "scripts"
SCRIPTS_DIR.mkdir(exist_ok=True)

CONFIG_DIR  = Path.home() / ".config" / "server_cockpit"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
GROUPS_FILE = CONFIG_DIR / "groups.json"
HIDDEN_FILE = CONFIG_DIR / "hidden.json"

HOSTNAME = socket.gethostname()

# Nom valide pour un service docker/systemd/snap/script (anti-injection)
SAFE_NAME = re.compile(r"^[\w][\w.@-]*$")

def safe_name(name: str) -> bool:
    return bool(name) and bool(SAFE_NAME.match(name)) and ".." not in name

# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout après {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def human_uptime(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if d: return f"{d}j {h:02d}h {m:02d}m"
    if h: return f"{h}h {m:02d}m"
    return f"{m}m"

def atomic_write(path: Path, data: str):
    """Écrit via un fichier temporaire + rename : jamais de JSON à moitié écrit."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data)
    tmp.replace(path)

# ──────────────────────────────────────────────
# CACHE TTL (2 s) — évite de re-sonder à chaque hit
# ──────────────────────────────────────────────

_cache = {}
_cache_lock = threading.Lock()

def cached(key, ttl, fn):
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
    return val

def cache_invalidate():
    with _cache_lock:
        _cache.clear()

# ──────────────────────────────────────────────
# DOCKER
# ──────────────────────────────────────────────

def _docker_services():
    if not shutil.which("docker"):
        return []
    _, out, _ = run(["docker", "ps", "-a",
                     "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}"])
    services = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        cid, name, status_raw = parts[0], parts[1], parts[2]
        ports = parts[3] if len(parts) > 3 else ""
        running = status_raw.lower().startswith("up")
        uptime_str = "—"
        if running:
            m = re.search(r"Up\s+(.+?)(?:\s*\(|$)", status_raw, re.I)
            uptime_str = m.group(1).strip() if m else "—"
        pm = re.search(r"0\.0\.0\.0:(\d+)", ports)
        services.append({
            "id": name,          # le nom est plus stable que l'ID (l'ID change au recreate)
            "cid": cid[:12],
            "name": name, "type": "docker",
            "status": "on" if running else "off",
            "uptime": uptime_str, "port": pm.group(1) if pm else "",
        })
    return services

def get_docker_services():
    return cached("docker", 2.0, _docker_services)

def docker_action(name: str, action: str):
    if not safe_name(name):
        return False, "nom invalide"
    
    code, _, err = run(["docker", action, name], timeout=30)
    
    # Si échec sur réseau manquant, essayer de le recréer
    if code != 0 and "network" in err and "does not exist" in err:
        import re
        # Extraire le nom du réseau du message d'erreur
        # Format: "network transmute_default does not exist" ou "network abc123... does not exist"
        network_name_match = re.search(r'network\s+(\S+)\s+does not exist', err)
        if network_name_match:
            network_name = network_name_match.group(1)
            # Si c'est un ID de réseau (hash long), on ne peut pas le recréer
            if len(network_name) > 12 and all(c in '0123456789abcdef' for c in network_name):
                return False, err  # Ne peut pas recréer un réseau par ID
            
            # Vérifier si le réseau existe déjà (au cas où il aurait été créé entre-temps)
            code_network, _, _ = run(["docker", "network", "inspect", network_name], timeout=10)
            if code_network != 0:
                # Le réseau n'existe pas, essayer de le créer
                code_create, _, err_create = run(["docker", "network", "create", network_name], timeout=10)
                if code_create == 0:
                    # Réessayer l'action originale
                    code, _, err = run(["docker", action, name], timeout=30)
                    cache_invalidate()
                    return code == 0, err
                else:
                    return False, f"Erreur création réseau {network_name}: {err_create}"
    
    cache_invalidate()
    return code == 0, err

# ──────────────────────────────────────────────
# SYSTEM APPS (services systemd utilisateur)
# ──────────────────────────────────────────────

def _user_services():
    # Ne lister que les services installés par l'utilisateur (~/.config/systemd/user/)
    user_unit_dir = Path.home() / ".config" / "systemd" / "user"
    if not user_unit_dir.exists():
        return []
    own_units = {p.stem for p in user_unit_dir.glob("*.service")}
    if not own_units:
        return []

    _, out, _ = run(["systemctl", "--user", "list-units", "--type=service",
                     "--all", "--no-legend", "--no-pager", "--plain"], timeout=10)
    services = []
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0].lstrip("●").strip()
        if not unit.endswith(".service"):
            continue
        name = unit[:-len(".service")]
        if not name or "@" in name or name not in own_units:
            continue
        active = parts[2] if len(parts) > 2 else "inactive"
        status = "on" if active == "active" else ("pending" if active == "activating" else "off")
        uptime_str = "—"
        if status == "on":
            _, prop, _ = run(["systemctl", "--user", "show", unit,
                              "--property=ActiveEnterTimestamp"], timeout=5)
            val = prop.split("=", 1)[-1].strip() if prop else ""
            if val and val != "n/a":
                try:
                    ts = time.mktime(time.strptime(val, "%a %Y-%m-%d %H:%M:%S %Z"))
                    uptime_str = human_uptime(time.time() - ts)
                except Exception:
                    pass
        services.append({"id": name, "name": name, "type": "systemd-user",
                         "status": status, "uptime": uptime_str})
    return services

def get_user_services():
    return cached("user_svc", 2.0, _user_services)

def systemctl_action(unit: str, action: str):
    if not safe_name(unit):
        return False, "nom invalide"
    code, _, err = run(["systemctl", "--user", action, unit], timeout=30)
    cache_invalidate()
    return code == 0, err

# ──────────────────────────────────────────────
# METRICS — cpu_percent non bloquant (warmup au boot)
# ──────────────────────────────────────────────

import psutil
psutil.cpu_percent(interval=None)   # amorce le compteur, les appels suivants sont instantanés

def get_metrics():
    ram  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime_s = time.time() - psutil.boot_time()
    return {
        "cpu": round(psutil.cpu_percent(interval=None), 1),
        "ram": round(ram.percent, 1),
        "disk": round(disk.percent, 1),
        "uptime": human_uptime(uptime_s), "uptime_s": int(uptime_s),
        "hostname": HOSTNAME,
    }

# ──────────────────────────────────────────────
# SCRIPTS
# ──────────────────────────────────────────────

def list_shortcuts():
    results = []
    if not SCRIPTS_DIR.exists():
        return results
    for p in sorted(SCRIPTS_DIR.iterdir()):
        if p.suffix == ".sh":
            results.append({
                "id": p.stem, "name": p.name,
                "path": str(p.resolve()) if p.is_symlink() else str(p),
                "link": str(p), "is_symlink": p.is_symlink(),
            })
    return results

def browse_fs(path: str):
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        return {"path": str(p), "entries": [], "error": "dossier introuvable"}
    entries = []
    error = None
    try:
        for child in sorted(p.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                entries.append({"name": child.name, "path": str(child), "type": "dir"})
            elif child.suffix == ".sh":
                entries.append({"name": child.name, "path": str(child), "type": "sh"})
    except PermissionError:
        error = "permission refusée"
    return {"path": str(p), "entries": entries, "error": error}

def add_shortcut(script_path: str):
    src = Path(script_path).expanduser().resolve()
    if not src.exists():
        return False, "fichier introuvable"
    if src.suffix != ".sh":
        return False, "pas un fichier .sh"
    if SCRIPTS_DIR in src.parents or src.parent == SCRIPTS_DIR:
        return False, "déjà dans ~/scripts/"
    dst = SCRIPTS_DIR / src.name
    if dst.exists() or dst.is_symlink():
        return False, "un raccourci avec ce nom existe déjà"
    dst.symlink_to(src)
    return True, str(dst)

def remove_shortcut(name: str):
    """Ne supprime QUE les symlinks. Un vrai fichier n'est jamais détruit."""
    if not safe_name(name.replace(".sh", "")):
        return False, "nom invalide"
    p = SCRIPTS_DIR / Path(name).name        # neutralise tout ../
    if p.is_symlink():
        p.unlink()
        return True, "raccourci supprimé"
    if p.exists():
        return False, ("ce script est un vrai fichier dans ~/scripts/, "
                       "pas un raccourci — suppression refusée par sécurité")
    return False, "introuvable"

def run_script(name: str):
    fname = Path(name).name                   # anti path-traversal
    p = SCRIPTS_DIR / fname
    if not p.exists():
        return False, "", "script introuvable"
    code, out, err = run(["bash", str(p)], timeout=60)
    return code == 0, out, err

# ──────────────────────────────────────────────
# GROUPS — ~/.config/server_cockpit/groups.json
# ──────────────────────────────────────────────

_groups_lock = threading.Lock()

def load_groups() -> list:
    if not GROUPS_FILE.exists():
        return []
    try:
        return json.loads(GROUPS_FILE.read_text())
    except Exception:
        return []

def save_groups(groups: list):
    with _groups_lock:
        atomic_write(GROUPS_FILE, json.dumps(groups, indent=2, ensure_ascii=False))

def group_status(members: list, svc_map: dict) -> str:
    statuses = [svc_map[m["id"]].get("status", "off")
                for m in members if m["id"] in svc_map
                and svc_map[m["id"]].get("status") in ("on", "off", "pending")]
    if not statuses: return "unknown"
    if all(s == "on"  for s in statuses): return "all_on"
    if all(s == "off" for s in statuses): return "all_off"
    return "mixed"

def _member_action(m, action):
    mid, mtype = m["id"], m["type"]
    if mtype == "docker":
        ok, err = docker_action(mid, action)
    elif mtype in ("systemd-user", "systemctl", "apt"):
        ok, err = systemctl_action(mid, action)
    elif mtype == "script":
        if action in ("start", "restart"):
            ok, _, err = run_script(mid + ".sh")
        else:
            ok, err = True, "scripts non arrêtables (ignoré)"
    else:
        ok, err = False, "type inconnu"
    return {"id": mid, "type": mtype, "ok": ok, "error": err}

def execute_group_action(group: dict, action: str) -> list:
    """Actions membres exécutées en parallèle (pool de 6)."""
    members = group.get("members", [])
    if not members:
        return []
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(lambda m: _member_action(m, action), members))

# ──────────────────────────────────────────────
# HIDDEN — ~/.config/server_cockpit/hidden.json
# ──────────────────────────────────────────────

_hidden_lock = threading.Lock()

def load_hidden() -> list:
    if not HIDDEN_FILE.exists():
        return []
    try:
        return json.loads(HIDDEN_FILE.read_text())
    except Exception:
        return []

def save_hidden(hidden: list):
    with _hidden_lock:
        atomic_write(HIDDEN_FILE, json.dumps(hidden, indent=2, ensure_ascii=False))

def hidden_ids() -> set:
    return {h["id"] for h in load_hidden()}

# ──────────────────────────────────────────────
# ROUTES — STATUS
# ──────────────────────────────────────────────

@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "hostname": HOSTNAME})

@app.route("/api/status")
def api_status():
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_docker = pool.submit(get_docker_services)
        f_user   = pool.submit(get_user_services)
        docker, user_svcs = f_docker.result(), f_user.result()

    apps    = user_svcs
    scripts = list_shortcuts()
    groups  = load_groups()
    hidden  = load_hidden()
    hids    = {h["id"] for h in hidden}

    svc_all = {s["id"]: s for s in docker + apps}
    for s in scripts:
        svc_all[s["id"]] = {**s, "type": "script", "status": "—"}

    hidden_full = [svc_all.get(h["id"],
                   {"id": h["id"], "type": h["type"], "name": h["id"],
                    "status": "off", "uptime": "—"}) for h in hidden]

    enriched_groups = [{**g, "computed_status": group_status(g.get("members", []), svc_all)}
                       for g in groups]

    return jsonify({
        "metrics": get_metrics(),
        "docker":  [s for s in docker  if s["id"] not in hids],
        "apps":    [s for s in apps    if s["id"] not in hids],
        "scripts": [s for s in scripts if s["id"] not in hids],
        "groups":  enriched_groups,
        "hidden":  hidden_full,
    })

# ──────────────────────────────────────────────
# ROUTES — ACTIONS INDIVIDUELLES
# ──────────────────────────────────────────────

VALID_ACTIONS = ("start", "stop", "restart")

@app.route("/api/docker/<action>/<name>", methods=["POST"])
def api_docker_action(action, name):
    if action not in VALID_ACTIONS: abort(400)
    ok, err = docker_action(name, action)
    return jsonify({"ok": ok, "error": err})

@app.route("/api/app/<action>", methods=["POST"])
def api_app_action(action):
    if action not in VALID_ACTIONS: abort(400)
    body = request.get_json(force=True, silent=True) or {}
    svc  = body.get("id", "")
    ok, err = systemctl_action(svc, action)
    return jsonify({"ok": ok, "error": err})

@app.route("/api/scripts/run/<name>", methods=["POST"])
def api_run_script(name):
    ok, out, err = run_script(name)
    return jsonify({"ok": ok, "stdout": out, "stderr": err})

# ──────────────────────────────────────────────
# ROUTES — GROUPS CRUD
# ──────────────────────────────────────────────

@app.route("/api/groups", methods=["GET"])
def api_get_groups():
    return jsonify(load_groups())

@app.route("/api/groups", methods=["POST"])
def api_create_group():
    body = request.get_json(force=True, silent=True) or {}
    groups = load_groups()
    new_group = {
        "id":      str(time.time_ns()),
        "name":    (body.get("name") or "Nouveau groupe")[:60],
        "color":   body.get("color", "#22C55E"),
        "members": body.get("members", []),
    }
    groups.append(new_group)
    save_groups(groups)
    return jsonify({"ok": True, "group": new_group})

@app.route("/api/groups/<gid>", methods=["PUT"])
def api_update_group(gid):
    body   = request.get_json(force=True, silent=True) or {}
    groups = load_groups()
    for i, g in enumerate(groups):
        if g["id"] == gid:
            groups[i] = {**g,
                "name":    (body.get("name") or g["name"])[:60],
                "color":   body.get("color",   g["color"]),
                "members": body.get("members", g["members"]),
            }
            save_groups(groups)
            return jsonify({"ok": True, "group": groups[i]})
    abort(404)

@app.route("/api/groups/<gid>", methods=["DELETE"])
def api_delete_group(gid):
    groups = [g for g in load_groups() if g["id"] != gid]
    save_groups(groups)
    return jsonify({"ok": True})

@app.route("/api/groups/<gid>/<action>", methods=["POST"])
def api_group_action(gid, action):
    if action not in VALID_ACTIONS: abort(400)
    group = next((g for g in load_groups() if g["id"] == gid), None)
    if not group: abort(404)
    results = execute_group_action(group, action)
    return jsonify({"ok": all(r["ok"] for r in results), "results": results})

# ──────────────────────────────────────────────
# ROUTES — HIDDEN
# ──────────────────────────────────────────────

@app.route("/api/hidden", methods=["GET"])
def api_get_hidden():
    return jsonify(load_hidden())

@app.route("/api/hidden", methods=["POST"])
def api_add_hidden():
    body  = request.get_json(force=True, silent=True) or {}
    items = body.get("items", [])
    hidden = load_hidden()
    existing = {h["id"] for h in hidden}
    for item in items:
        iid = item.get("id")
        if iid and iid not in existing:
            hidden.append({"id": iid, "type": item.get("type", "unknown")})
            existing.add(iid)
    save_hidden(hidden)
    return jsonify({"ok": True, "hidden": hidden})

@app.route("/api/hidden/<hid>", methods=["DELETE"])
def api_remove_hidden(hid):
    save_hidden([h for h in load_hidden() if h["id"] != hid])
    return jsonify({"ok": True})

@app.route("/api/hidden", methods=["DELETE"])
def api_clear_hidden():
    save_hidden([])
    return jsonify({"ok": True})

# ──────────────────────────────────────────────
# ROUTES — FILE BROWSER & SHORTCUTS
# ──────────────────────────────────────────────

@app.route("/api/browse")
def api_browse():
    return jsonify(browse_fs(request.args.get("path", str(Path.home()))))

@app.route("/api/shortcuts", methods=["GET"])
def api_shortcuts():
    return jsonify(list_shortcuts())

@app.route("/api/shortcuts", methods=["POST"])
def api_add_shortcut():
    body = request.get_json(force=True, silent=True) or {}
    ok, msg = add_shortcut(body.get("path", ""))
    return jsonify({"ok": ok, "message": msg})

@app.route("/api/shortcuts/<name>", methods=["DELETE"])
def api_remove_shortcut(name):
    ok, msg = remove_shortcut(name)
    return jsonify({"ok": ok, "message": msg})

# ──────────────────────────────────────────────
# SERVE FRONTEND
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/support.js")
def support_js():
    return send_from_directory(".", "support.js")

if __name__ == "__main__":
    # debug=False impératif : le reloader relancerait le prompt sudo
    # threaded=True : les sondes lentes ne bloquent pas les autres requêtes
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
