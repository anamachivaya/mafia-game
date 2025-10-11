import copy
import pytest

from mafia import _resolve_night_actions


def make_room(players, assignments, assignment_factions, pending_actions):
    return {
        'players': [{'name': p} for p in players],
        'assignments': assignments.copy(),
        'assignment_factions': assignment_factions.copy(),
        'pending_actions': pending_actions.copy(),
        'eliminated_players': [],
        'night_history': [],
        'last_night_results': {}
    }


def test_mafia_kill_and_doctor_save():
    players = ['Alice', 'Bob', 'Carol']
    assignments = {'Alice': 'Mafia', 'Bob': 'Villager', 'Carol': 'Doctor'}
    assignment_factions = {'Alice': 'Mafia', 'Bob': 'Villagers', 'Carol': 'Villagers'}
    pending_actions = [
        {'player': 'Alice', 'role': 'Mafia', 'action': 'mafia_kill', 'target': 'Bob'},
        {'player': 'Carol', 'role': 'Doctor', 'action': 'save', 'target': 'Bob'}
    ]
    room = make_room(players, assignments, assignment_factions, pending_actions)
    results = _resolve_night_actions(room)
    assert 'Bob' not in room['eliminated_players']
    assert results['saved'] == ['Bob'] or 'Bob' in results.get('notes', [])


def test_suicide_bomber_final_action():
    players = ['Sam', 'Tina', 'Liam']
    assignments = {'Sam': 'Suicide Bomber', 'Tina': 'Mafia', 'Liam': 'Villager'}
    assignment_factions = {'Sam': 'Mafia', 'Tina': 'Mafia', 'Liam': 'Villagers'}
    # Sam is killed by mafia, but had previously submitted a suicide_target
    pending_actions = [
        {'player': 'Tina', 'role': 'Mafia', 'action': 'mafia_kill', 'target': 'Sam'},
        {'player': 'Sam', 'role': 'Suicide Bomber', 'action': 'suicide_target', 'target': 'Liam'}
    ]
    room = make_room(players, assignments, assignment_factions, pending_actions)
    results = _resolve_night_actions(room)
    # Sam killed, and suicide bomber kills Liam
    assert 'Sam' in room['eliminated_players']
    assert 'Liam' in room['eliminated_players']
    assert any('Suicide bomber' in note for note in results.get('notes', []))


def test_win_detection_villagers_win():
    players = ['A', 'B']
    assignments = {'A': 'Villager', 'B': 'Villager'}
    assignment_factions = {'A': 'Villagers', 'B': 'Villagers'}
    pending_actions = []
    room = make_room(players, assignments, assignment_factions, pending_actions)
    results = _resolve_night_actions(room)
    assert room.get('game_over') is True
    assert room.get('winner') == 'villagers'