"""
Simulation script that uses the Flask test client to create a room, add players,
assign roles, start a game, submit night actions, resolve night, and fetch
payloads to verify reveal entries are present.

Run: python3 tools/simulate_game_flow.py
"""
import json
import sys
import os
# ensure repo root is on path so `mafia` can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from mafia import app, rooms, lock


def pretty(o):
    return json.dumps(o, indent=2, sort_keys=True)


def run():
    client = app.test_client()

    room_name = 'simroom'

    # Create room
    resp = client.post('/create_room', data={'room_name': room_name, 'host_password': 'hp'})
    # follow redirect to host dashboard
    assert resp.status_code in (302, 200)

    with lock:
        room = rooms.get(room_name)
        if not room:
            # create minimal room structure directly
            rooms[room_name] = {
                'host_password': 'hp',
                'player_password': None,
                'host_token': 'host-token-sim',
                'created_at': 0,
                'last_host_activity': 0,
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
            room = rooms[room_name]

    # Add players
    players = ['alice', 'bob', 'carol']
    for p in players:
        with lock:
            room['players'].append({'name': p, 'device_id': f'device-{p}'})

    # Assign roles: mafia -> alice, cop -> bob, villager -> carol
    with lock:
        room['assignments'] = {'alice': 'Godfather', 'bob': 'Cop', 'carol': 'Villager'}
        room['assignment_factions'] = {'alice': 'mafia', 'bob': 'villagers', 'carol': 'villagers'}

    # Start the game
    resp = client.post(f'/api/rooms/{room_name}/start-game')
    print('start-game status:', resp.status_code, resp.get_json())

    # Simulate night actions: mafia kill carol
    with lock:
        room['night_actions'] = {'mafia_final': 'carol'}

    # Resolve night via host endpoint (simulate host advancing to day)
    resp = client.post(f'/api/rooms/{room_name}/start-day')
    print('start-day status:', resp.status_code, resp.get_json())

    # Fetch game-state and players payloads
    resp = client.get(f'/api/rooms/{room_name}/game-state')
    print('\n--- game-state payload ---')
    print(pretty(resp.get_json()))

    resp = client.get(f'/api/rooms/{room_name}/players')
    print('\n--- players payload ---')
    print(pretty(resp.get_json()))


if __name__ == '__main__':
    run()
