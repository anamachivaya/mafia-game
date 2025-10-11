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


def test_cop_sees_framed_as_mafia_over_faction():
    # Setup: Bob is framed by Framer; Cop checks Bob -> should reveal 'Mafia'
    players = ['Cop', 'Framer', 'Bob']
    assignments = {'Cop': 'Cop', 'Framer': 'Framer', 'Bob': 'Villager'}
    assignment_factions = {'Cop': 'Villagers', 'Framer': 'Villagers', 'Bob': 'Villagers'}
    pending_actions = [
        {'player': 'Framer', 'role': 'Framer', 'action': 'frame', 'target': 'Bob'},
        {'player': 'Cop', 'role': 'Cop', 'action': 'check', 'target': 'Bob'}
    ]
    room = make_room(players, assignments, assignment_factions, pending_actions)
    results = _resolve_night_actions(room)
    # Expect one check reveal and it should be 'Mafia'
    checks = results.get('checks', [])
    assert len(checks) == 1
    assert checks[0]['target'] == 'Bob'
    assert checks[0]['revealed'] == 'Mafia'


def test_godfather_reveals_as_villager_even_if_framed():
    # Godfather should still reveal Villager even if framed
    players = ['Cop', 'Framer', 'GF']
    assignments = {'Cop': 'Cop', 'Framer': 'Framer', 'GF': 'Godfather'}
    assignment_factions = {'Cop': 'Villagers', 'Framer': 'Villagers', 'GF': 'Mafia'}
    pending_actions = [
        {'player': 'Framer', 'role': 'Framer', 'action': 'frame', 'target': 'GF'},
        {'player': 'Cop', 'role': 'Cop', 'action': 'check', 'target': 'GF'}
    ]
    room = make_room(players, assignments, assignment_factions, pending_actions)
    results = _resolve_night_actions(room)
    checks = results.get('checks', [])
    assert len(checks) == 1
    assert checks[0]['target'] == 'GF'
    # godfather reveals as Villager per rules
    assert checks[0]['revealed'] == 'Villager'
