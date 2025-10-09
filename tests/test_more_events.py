# tests/test_more_events.py
import sys
import importlib.util
from pathlib import Path
import pytest

# --- Import robuste de app.py (sans dépendre du PYTHONPATH) ---
try:
    import app as appmod
except ModuleNotFoundError:
    root = Path(__file__).resolve().parents[1]
    app_path = root / "app.py"
    spec = importlib.util.spec_from_file_location("app", app_path)
    appmod = importlib.util.module_from_spec(spec)
    sys.modules["app"] = appmod
    assert spec and spec.loader
    spec.loader.exec_module(appmod)

flask_app = appmod.app
socketio = appmod.socketio
rooms = appmod.rooms
SOLUTIONS = appmod.SOLUTIONS
cleanup_room = appmod.cleanup_room
start_timer = appmod.start_timer


def setup_room(room: str):
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


# ---------------------------------------------------------------------------
# chat_message -> chat_response
# ---------------------------------------------------------------------------
def test_chat_message_emits_chat_response():
    client = make_client()
    room = "r_chat"
    username = "tom"
    msg = "hello"

    client.emit("join_room", {"username": username, "room": room})
    client.get_received()  # purge

    client.emit("chat_message", {"room": room, "username": username, "msg": msg})

    events = client.get_received()
    payloads = [e["args"][0] for e in events if e["name"] == "chat_response"]
    assert payloads, f"Pas d'événement chat_response: {events}"
    assert payloads[-1]["username"] == username
    assert payloads[-1]["msg"] == msg
    client.disconnect()


# ---------------------------------------------------------------------------
# remove_medication -> medication_removed
# ---------------------------------------------------------------------------
def test_remove_medication_removes_and_emits():
    client = make_client()
    room = "r_rm"
    username = "eve"

    client.emit("join_room", {"username": username, "room": room})
    setup_room(room)
    rooms[room]["medications"] = ["Paracétamol", "Amoxicilline"]

    client.get_received()  # purge

    client.emit(
        "remove_medication",
        {"username": username, "room": room, "medication": "Paracétamol"},
    )

    # Vérifie que le médoc a disparu
    assert "Paracétamol" not in rooms[room]["medications"]

    events = client.get_received()
    assert any(e["name"] == "medication_removed" for e in events)
    client.disconnect()


# ---------------------------------------------------------------------------
# cleanup_room (fonction directe)
# ---------------------------------------------------------------------------
def test_cleanup_room_sets_flags_and_keeps_room():
    room = "r_clean"
    setup_room(room)
    # Simule un thread en cours
    rooms[room]["thread"] = object()
    rooms[room]["game_over"] = False

    cleanup_room(room)

    assert rooms[room]["game_over"] is True
    assert rooms[room]["thread"] is None
    # La room n'est pas supprimée par cleanup_room
    assert room in rooms


# ---------------------------------------------------------------------------
# reset_room -> supprime la room + room_reset
# ---------------------------------------------------------------------------
def test_reset_room_deletes_room_and_emits():
    client = make_client()
    room = "r_reset"
    client.emit("join_room", {"username": "zoe", "room": room})

    setup_room(room)
    # simule un "thread" présent pour vérifier qu'on passe par la logique d'arrêt
    rooms[room]["thread"] = object()
    rooms[room]["game_over"] = False

    client.get_received()  # purge

    client.emit("reset_room", {"room": room})

    # La room doit être supprimée
    assert room not in rooms

    events = client.get_received()
    assert any(e["name"] == "room_reset" for e in events)
    client.disconnect()


# ---------------------------------------------------------------------------
# start_game -> lance le "timer" via un thread et émet message de départ
# ---------------------------------------------------------------------------
def test_start_game_starts_timer_and_emits(monkeypatch):
    client = make_client()
    room = "r_start"
    client.emit("join_room", {"username": "luc", "room": room})
    client.get_received()  # purge

    # Monkeypatch: exécute la "thread" de façon synchrone
    called = {}

    class FakeThread:
        def __init__(self, target, args=()):
            self._target = target
            self._args = args
        def start(self):
            # exécute immédiatement la target SANS thread
            called["ran"] = True
            # on ne lance pas start_timer réel ici : on remplace plus bas
            self._target(*self._args)

    def fake_start_timer(room_arg, duration):
        # on remplace la vraie logique longue
        called["start_timer"] = (room_arg, duration)

    monkeypatch.setattr(appmod.threading, "Thread", FakeThread)
    monkeypatch.setattr(appmod, "start_timer", fake_start_timer)

    client.emit("start_game", {"room": room, "duration": 42})

    assert "ran" in called
    assert "start_timer" in called
    assert called["start_timer"][0] == room
    assert called["start_timer"][1] == 42

    events = client.get_received()
    # message "Partie lancée"
    payloads = [e["args"][0] for e in events if e["name"] == "server_message"]
    assert any("Partie lancée" in p.get("msg", "") for p in payloads)

    client.disconnect()


# ---------------------------------------------------------------------------
# start_timer -> timeout -> game_result (defeat / timeout) + nettoyage
# ---------------------------------------------------------------------------
def test_start_timer_emits_timeout_and_cleans_room(monkeypatch):
    client = make_client()
    room = "r_timer"
    client.emit("join_room", {"username": "sam", "room": room})
    setup_room(room)

    # Empêche le vrai sleep pour que ça aille instantanément
    monkeypatch.setattr(appmod.time, "sleep", lambda s: None)

    client.get_received()  # purge

    # Exécute la boucle avec une durée minuscule
    start_timer(room, duration=2)

    # Le serveur doit émettre game_result avec reason "timeout"
    events = client.get_received()
    payloads = [e["args"][0] for e in events if e["name"] == "game_result"]
    assert payloads, f"Aucun game_result: {events}"
    assert payloads[-1]["result"] == "defeat"
    assert payloads[-1]["reason"] == "timeout"

    # Room nettoyée (thread=None) + game_over=True
    assert rooms[room]["thread"] is None
    assert rooms[room]["game_over"] is True

    client.disconnect()
