# tests/test_game_events.py
import pytest

# On importe TON module applicatif
import app as appmod  # app.py à la racine
# on récupère les symboles utiles
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
    # Avant chaque test : on repart d'un état propre
    rooms.clear()
    yield
    rooms.clear()


def make_client():
    """Crée un client Socket.IO de test lié à l'app Flask."""
    return socketio.test_client(flask_app, flask_test_client=flask_app.test_client())


# 1) player_ready --------------------------------------------------------------
def test_player_ready_sets_status_and_broadcasts():
    client = make_client()

    room = "r1"
    username = "alice"

    # Le client rejoint d'abord la room (nécessaire pour recevoir les emits de room)
    client.emit("join_room", {"username": username, "room": room})
    client.get_received()  # on purge les messages d'accueil pour le test

    # On émet player_ready avec un rôle unique pour NE PAS démarrer le timer/partie
    client.emit(
        "player_ready", {"username": username, "room": room, "role": "Médecin"}
    )

    # L'état serveur doit marquer alice comme prête dans rooms
    assert room in rooms
    assert "alice" in rooms[room]["ready_players"]
    assert rooms[room]["ready_players"]["alice"]["role"] == "Médecin"

    # Et un événement 'player_status_update' doit être diffusé dans la room
    events = client.get_received()
    names = [e["name"] for e in events]
    assert "player_status_update" in names


# 2) submit_diagnosis ----------------------------------------------------------
def test_submit_diagnosis_sets_value_and_emits():
    client = make_client()
    room = "r2"
    username = "bob"

    client.emit("join_room", {"username": username, "room": room})
    setup_room(room)  # on garantit que la room existe côté serveur

    client.get_received()  # purge

    client.emit(
        "submit_diagnosis",
        {"username": username, "room": room, "diagnosis": "Grippe saisonnière"},
    )

    # L'état serveur doit être mis à jour
    assert rooms[room]["diagnosis"] == "Grippe saisonnière"

    # Et un événement de confirmation doit être reçu
    events = client.get_received()
    assert any(e["name"] == "diagnosis_submitted" for e in events)


# 3) submit_medication ---------------------------------------------------------
def test_submit_medication_appends_once_and_emits():
    client = make_client()
    room = "r3"
    username = "carol"

    client.emit("join_room", {"username": username, "room": room})
    setup_room(room)

    client.get_received()  # purge

    med = "Paracétamol"
    client.emit(
        "submit_medication", {"username": username, "room": room, "medication": med}
    )
    client.emit(
        "submit_medication", {"username": username, "room": room, "medication": med}
    )  # pas de doublon

    # La médication ne doit apparaître qu'une seule fois
    assert rooms[room]["medications"].count(med) == 1

    events = client.get_received()
    assert any(e["name"] == "medication_submitted" for e in events)


# 4) validate_solution (cas victoire) -----------------------------------------
def test_validate_solution_victory_path():
    client = make_client()
    room = "r4"
    username = "dave"

    client.emit("join_room", {"username": username, "room": room})
    setup_room(room)

    # On aligne l'état de la room sur une solution correcte
    diagnosis = "Grippe saisonnière"
    meds = SOLUTIONS[diagnosis]  # ["Paracétamol", "Oseltamivir"]

    rooms[room]["diagnosis"] = diagnosis
    rooms[room]["medications"] = meds.copy()

    client.get_received()  # purge

    # Quand on valide, le serveur doit annoncer "victory"
    client.emit("validate_solution", {"room": room})

    events = client.get_received()
    payloads = [e["args"][0] for e in events if e["name"] == "game_result"]
    assert payloads, f"Pas d'événement 'game_result' reçu: {events}"
    assert payloads[-1]["result"] == "victory"
