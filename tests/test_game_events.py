# tests/test_game_events.py
import sys
import importlib.util
from pathlib import Path
import pytest

# --- Import robuste de app.py (sans dépendre du PYTHONPATH) ---
try:
    import app as appmod
except ModuleNotFoundError:
    root = Path(__file__).resolve().parents[1]  # racine du repo
    app_path = root / "app.py"
    spec = importlib.util.spec_from_file_location("app", app_path)
    appmod = importlib.util.module_from_spec(spec)
    sys.modules["app"] = appmod
    assert spec and spec.loader
    spec.loader.exec_module(appmod)

# Raccourcis utiles
flask_app = appmod.app
socketio = appmod.socketio
rooms = appmod.rooms
SOLUTIONS = appmod.SOLUTIONS


def setup_room(room: str):
    """Prépare une room minimaliste, non finie, pour les tests."""
    rooms[room] = {
        "users": set(),
        "timer": 0,
        "thread": None,
        "ready_players": {},
        "diagnosis": None,
        "medications": [],
        "game_over": False,
    }


@pytest.fixture(autouse=True)
def clean_rooms():
    rooms.clear()
    yield
    rooms.clear()


def make_client():
    return socketio.test_client(flask_app, flask_test_client=flask_app.test_client())


# 1) player_ready --------------------------------------------------------------
def test_player_ready_sets_status_and_broadcasts():
    client = make_client()
    room = "r1"
    username = "alice"

    # Rejoindre la room pour recevoir les emits de room
    client.emit("join_room", {"username": username, "room": room})
    client.get_received()  # purge

    # Rôle unique pour ne PAS démarrer le timer
    client.emit("player_ready", {"username": username, "room": room, "role": "Médecin"})

    assert room in rooms
    assert "alice" in rooms[room]["ready_players"]
    assert rooms[room]["ready_players"]["alice"]["role"] == "Médecin"

    events = client.get_received()
    names = [e["name"] for e in events]
    assert "player_status_update" in names

    client.disconnect()


# 2) submit_diagnosis ----------------------------------------------------------
def test_submit_diagnosis_sets_value_and_emits():
    client = make_client()
    room = "r2"
    username = "bob"

    client.emit("join_room", {"username": username, "room": room})
    setup_room(room)
    client.get_received()  # purge

    client.emit(
        "submit_diagnosis",
        {"username": username, "room": room, "diagnosis": "Grippe saisonnière"},
    )

    assert rooms[room]["diagnosis"] == "Grippe saisonnière"
    events = client.get_received()
    assert any(e["name"] == "diagnosis_submitted" for e in events)

    client.disconnect()


# 3) submit_medication ---------------------------------------------------------
def test_submit_medication_appends_once_and_emits():
    client = make_client()
    room = "r3"
    username = "carol"

    client.emit("join_room", {"username": username, "room": room})
    setup_room(room)
    client.get_received()  # purge

    med = "Paracétamol"
    client.emit("submit_medication", {"username": username, "room": room, "medication": med})
    client.emit("submit_medication", {"username": username, "room": room, "medication": med})  # pas de doublon

    assert rooms[room]["medications"].count(med) == 1
    events = client.get_received()
    assert any(e["name"] == "medication_submitted" for e in events)

    client.disconnect()


# 4) validate_solution (victoire) ----------------------------------------------
def test_validate_solution_victory_path():
    client = make_client()
    room = "r4"
    username = "dave"

    client.emit("join_room", {"username": username, "room": room})
    setup_room(room)
    client.get_received()  # purge

    diagnosis = "Grippe saisonnière"
    meds = SOLUTIONS[diagnosis].copy()  # ["Paracétamol", "Oseltamivir"]

    rooms[room]["diagnosis"] = diagnosis
    rooms[room]["medications"] = meds

    client.emit("validate_solution", {"room": room})

    events = client.get_received()
    payloads = [e["args"][0] for e in events if e["name"] == "game_result"]
    assert payloads, f"Pas d'événement 'game_result' reçu: {events}"
    assert payloads[-1]["result"] == "victory"

    client.disconnect()
