import os
import sys
os.environ['PYTEST_RUNNING'] = '1'
# ensure project root is on sys.path so tests can import mafia.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import json
import pytest
from mafia import app, rooms, _init_night_state, _start_game

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        # clear global rooms
        rooms.clear()
        yield client

def make_room_with_players():
    room = {
        'host_password': 'h',
        'player_password': None,
        'host_token': 't',
        'created_at': float(__import__('time').time()),
        'players': [],
        'roles': [],
        'assignments': {},
        'game_started': False,
        'eliminated_players': [],
        'chat': [],
        'chat_next_id': 1,
        'chat_colors': {},
        'chat_palette': [],
        'chat_palette_orig': []
    }
    return room

def test_start_game_initializes_night(client):
    rooms['r1'] = make_room_with_players()
    room = rooms['r1']
    # add players and assignments
    room['players'] = [{'name': 'A'}, {'name': 'B'}]
    room['roles'] = [{'name': 'Mafia', 'count': 1}, {'name': 'Doctor', 'count': 1}]
    room['assignments'] = {'A': 'Mafia', 'B': 'Doctor'}

    # host cookie
    # set host cookies using test client's set_cookie signature in this environment
    try:
        client.set_cookie('host_token', 't')
        client.set_cookie('host_room', 'r1')
    except TypeError:
        # fallback to environ_base header
        client.environ_base['HTTP_COOKIE'] = 'host_token=t; host_room=r1'
    rv = client.post('/api/rooms/r1/start-game')
    assert rv.status_code == 200
    data = rv.get_json()
    assert data['success'] is True
    # room should be in night phase
    assert room['phase'] == 'night'
    assert 'night_actions' in room
    assert 'mafia_final_chooser' in room['night_actions']

def test_restart_preserves_players_and_roles(client):
    rooms['r2'] = make_room_with_players()
    room = rooms['r2']
    room['players'] = [{'name': 'P1'}, {'name': 'P2'}]
    room['roles'] = [{'name': 'R1', 'count': 2}]
    room['assignments'] = {'P1': 'R1', 'P2': 'R1'}
    room['eliminated_players'] = ['P2']
    room['game_started'] = True

    try:
        client.set_cookie('host_token', 't')
        client.set_cookie('host_room', 'r2')
    except TypeError:
        client.environ_base['HTTP_COOKIE'] = 'host_token=t; host_room=r2'
    rv = client.post('/api/rooms/r2/restart')
    assert rv.status_code == 200
    data = rv.get_json()
    assert data['success'] is True
    assert room['players'] == [{'name': 'P1'}, {'name': 'P2'}]
    assert room['roles'] == [{'name': 'R1', 'count': 2}]
    assert room.get('assignments') == {}
    assert room.get('eliminated_players') == []
    assert room['game_started'] is False
    assert room['phase'] == 'lobby'

def test_mafia_final_chooser_priority(client):
    rooms['r3'] = make_room_with_players()
    room = rooms['r3']
    room['players'] = [{'name': 'M1'}, {'name': 'F1'}, {'name': 'G1'}]
    # assignments: G1 = godfather, F1 = framer, M1 = mafia
    room['assignments'] = {'M1': 'Mafia', 'F1': 'Framer', 'G1': 'Godfather'}
    room['roles'] = [{'name': 'Godfather', 'count': 1}, {'name': 'Framer', 'count': 1}, {'name': 'Mafia', 'count': 1}]
    _start_game(room)
    _init_night_state(room)
    # godfather should be chosen
    chooser = room['night_actions'].get('mafia_final_chooser')
    assert chooser == 'G1'

def test_doctor_save_and_bodyguard_interaction(client):
    rooms['r4'] = make_room_with_players()
    room = rooms['r4']
    room['players'] = [{'name': 'V'}, {'name': 'D'}, {'name': 'B'}]
    room['assignments'] = {'V': 'Mafia', 'D': 'Doctor', 'B': 'Bodyguard'}
    room['roles'] = [{'name': 'Mafia', 'count': 1}, {'name': 'Doctor', 'count': 1}, {'name': 'Bodyguard', 'count': 1}]
    _start_game(room)
    _init_night_state(room)

    # mafia selects V -> kill target is D
    room.setdefault('night_actions', {})['mafia_final'] = 'D'
    # doctor saves D
    room['night_actions']['doctor_save'] = 'D'
    # bodyguard protects D (shouldn't die because doctor saved)
    room['night_actions']['bodyguard_save'] = 'D'

    # run start_day resolution
    client.post('/api/rooms/r4/start-day', headers={'Cookie': 'host_token=t; host_room=r4'})
    # no deaths
    assert 'D' not in room.get('eliminated_players', [])

def test_vigilante_and_doctor(client):
    rooms['r5'] = make_room_with_players()
    room = rooms['r5']
    room['players'] = [{'name': 'V'}, {'name': 'Doc'}, {'name': 'X'}]
    room['assignments'] = {'V': 'Vigilante', 'Doc': 'Doctor', 'X': 'Villager'}
    room['roles'] = [{'name': 'Vigilante', 'count': 1}, {'name': 'Doctor', 'count': 1}, {'name': 'Villager', 'count': 1}]
    _start_game(room)
    _init_night_state(room)

    room.setdefault('night_actions', {})['vigilante_kill'] = 'X'
    room['night_actions']['doctor_save'] = 'X'

    client.post('/api/rooms/r5/start-day', headers={'Cookie': 'host_token=t; host_room=r5'})
    # doctor saved X so no death
    assert 'X' not in room.get('eliminated_players', [])
