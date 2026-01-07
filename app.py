from flask import Flask, request, jsonify
from flask_cors import CORS
from pathlib import Path
import json
import unicodedata

# -------------------------------------------------------------------
# APP SETUP
# -------------------------------------------------------------------

app = Flask(__name__)

# CORS: autoriser GitHub Pages + dev local, et couvrir OPTIONS (preflight)
CORS(
    app,
    resources={r"/api/*": {"origins": [
        "https://lucasveiga02.github.io",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]}},
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

PLAYERS_FILE = DATA_DIR / "players.json"
ASSIGNMENTS_FILE = DATA_DIR / "assignments.json"
STATE_FILE = DATA_DIR / "state.json"

ADMIN_PASSWORD = "Veiga"  # tu peux le passer en variable d'env plus tard


# -------------------------------------------------------------------
# UTILS
# -------------------------------------------------------------------

def normalize(text: str) -> str:
    """Normalise une chaîne pour comparaison fiable (accents / casse / espaces)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.lower().strip().split())


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def ensure_player_state(state: dict, player_id: str) -> dict:
    """Crée l'entrée state pour un joueur si absente. ID = nom."""
    if player_id not in state:
        state[player_id] = default_player_state()
    return state[player_id]


def default_player_state() -> dict:
    """Valeurs par défaut pour un joueur."""
    return {
        "mission_done": False,
        "guess": None,                 # {killer_id, killer_display, mission} ou None
        "points": 0,
        "discovered_by_target": False
    }


def build_default_state(players: list) -> dict:
    """Construit un state complet avec tous les joueurs aux valeurs par défaut."""
    state = {}
    for p in players:
        pid = p.get("id")
        if pid:
            state[pid] = default_player_state()
    return state


def load_assignments():
    """
    Supporte 2 formats :
    1) Nouveau (recommandé) : dict
       { "Maxence": {"target": "...", "mission": "..."}, ... }
    2) Ancien : list
       [{"killer":"...", "target":"...", "mission":"..."}, ...]
    """
    raw = load_json(ASSIGNMENTS_FILE, {})
    if isinstance(raw, dict):
        return raw, "dict"
    if isinstance(raw, list):
        return raw, "list"
    return {}, "unknown"


def find_killer_key(assignments_dict: dict, player_display: str):
    """Trouve la clé killer dans assignments_dict via normalisation."""
    wanted = normalize(player_display)
    # match exact normalisé
    for k in assignments_dict.keys():
        if normalize(k) == wanted:
            return k
    return None


# -------------------------------------------------------------------
# HEALTH CHECK
# -------------------------------------------------------------------

@app.get("/")
def health():
    return "Backend is running"


# -------------------------------------------------------------------
# GET /api/players
# -> utilisé pour autocomplete (accueil + accusation)
# -------------------------------------------------------------------

@app.get("/api/players")
def get_players():
    players = load_json(PLAYERS_FILE, [])
    return jsonify(players)


# -------------------------------------------------------------------
# GET /api/mission?player=<display>
# -> récup mission + cible + statut mission_done
# -------------------------------------------------------------------

@app.get("/api/mission")
def get_mission():
    player_display = request.args.get("player")
    if not player_display:
        return jsonify(ok=False, error="Missing player parameter"), 400

    players = load_json(PLAYERS_FILE, [])
    state = load_json(STATE_FILE, {})

    assignments, fmt = load_assignments()

    # --- Nouveau format dict ---
    if fmt == "dict":
        killer_key = find_killer_key(assignments, player_display)
        if not killer_key:
            return jsonify(ok=False, error="Player not found in assignments"), 404

        a = assignments.get(killer_key, {}) or {}
        player_state = ensure_player_state(state, killer_key)
        save_json(STATE_FILE, state)

        return jsonify(
            ok=True,
            player={"id": killer_key, "display": killer_key},
            mission={"text": a.get("mission", "—")},
            target={"display": a.get("target", "—")},
            mission_done=bool(player_state.get("mission_done", False))
        )

    # --- Ancien format list (fallback) ---
    if fmt == "list":
        norm_input = normalize(player_display)
        for a in assignments:
            if normalize(a.get("killer", "")) == norm_input:
                killer_name = a["killer"]
                player_state = ensure_player_state(state, killer_name)
                save_json(STATE_FILE, state)

                return jsonify(
                    ok=True,
                    player={"id": killer_name, "display": killer_name},
                    mission={"text": a.get("mission", "—")},
                    target={"display": a.get("target", "—")},
                    mission_done=bool(player_state.get("mission_done", False))
                )

        return jsonify(ok=False, error="Player not found in assignments"), 404

    return jsonify(ok=False, error="Invalid assignments format"), 500


# -------------------------------------------------------------------
# POST /api/mission_done
# body: { player_id: "<nom>" }  (ou player_display)
# -> valide "J’ai effectué ma mission"
# -------------------------------------------------------------------

@app.post("/api/mission_done")
def mission_done():
    data = request.get_json(silent=True) or {}
    player_id = (data.get("player_id") or data.get("player_display") or "").strip()

    if not player_id:
        return jsonify(ok=False, error="Missing player_id"), 400

    state = load_json(STATE_FILE, {})
    entry = ensure_player_state(state, player_id)
    entry["mission_done"] = True
    save_json(STATE_FILE, state)

    return jsonify(ok=True, mission_done=True)


# -------------------------------------------------------------------
# POST /api/guess
# body: {
#   player_id: "<nom>",
#   accused_killer_id: "<nom>" (ou accused_killer_display),
#   guessed_mission: "..."
# }
# -> enregistre le guess
# -------------------------------------------------------------------

@app.post("/api/guess")
def submit_guess():
    data = request.get_json(silent=True) or {}

    player_id = (data.get("player_id") or data.get("player_display") or "").strip()
    accused_id = (data.get("accused_killer_id") or data.get("accused_killer_display") or "").strip()
    guessed_mission = (data.get("guessed_mission") or "").strip()

    if not player_id:
        return jsonify(ok=False, error="Missing player_id"), 400
    if not accused_id:
        return jsonify(ok=False, error="Missing accused_killer_id"), 400
    if not guessed_mission:
        return jsonify(ok=False, error="Missing guessed_mission"), 400

    state = load_json(STATE_FILE, {})
    entry = ensure_player_state(state, player_id)

    entry["guess"] = {
        "killer_id": accused_id,          # ID = nom
        "killer_display": accused_id,     # affichage = nom
        "mission": guessed_mission
    }

    save_json(STATE_FILE, state)
    return jsonify(ok=True)


# -------------------------------------------------------------------
# GET /api/leaderboard
# -> tableau admin
# -------------------------------------------------------------------

@app.get("/api/leaderboard")
def leaderboard():
    players = load_json(PLAYERS_FILE, [])
    state = load_json(STATE_FILE, {})

    rows = []
    for p in players:
        name = p.get("id")  # ID = nom
        if not name:
            continue

        s = state.get(name, {})
        guess = s.get("guess") or {}

        rows.append({
            "display": name,
            "points": s.get("points", 0),
            "mission_done": bool(s.get("mission_done", False)),
            "discovered_by_target": bool(s.get("discovered_by_target", False)),
            "found_killer": bool(guess),
            "guess_killer_display": guess.get("killer_display"),
            "guess_mission": guess.get("mission")
        })

    return jsonify(rows)


# -------------------------------------------------------------------
# POST /api/admin/reset
# body: { password: "Veiga" }
# -> remet STATE_FILE aux valeurs par défaut (sans effacer les joueurs)
# -------------------------------------------------------------------

@app.post("/api/admin/reset")
def admin_reset():
    data = request.get_json(silent=True) or {}
    password = (data.get("password") or "").strip()

    if password != ADMIN_PASSWORD:
        return jsonify(ok=False, error="Bad password"), 403

    players = load_json(PLAYERS_FILE, [])

    # Reconstruit un state complet (tous joueurs présents) aux valeurs par défaut
    new_state = build_default_state(players)
    save_json(STATE_FILE, new_state)

    return jsonify(ok=True, reset=True, players=len(new_state))


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
