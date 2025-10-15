#!/usr/bin/env python3
"""Smoke test: simulate host + player + spectator SSE clients and trigger a host kill.

Run after the server is started on http://127.0.0.1:5051
"""
import requests
import threading
import time
import json
import sys

BASE = 'http://127.0.0.1:5051'
ROOM = 'smoke_test_room'

# Simple SSE reader using requests streaming
def sse_listener(session, url, name, events, stop_evt):
    try:
        with session.get(url, stream=True) as resp:
            if resp.status_code != 200:
                print(f"[{name}] SSE connect failed: {resp.status_code}")
                return
            print(f"[{name}] SSE connected")
            buffer = ''
            for line in resp.iter_lines(decode_unicode=True):
                if stop_evt.is_set():
                    break
                if line is None:
                    continue
                line = line.strip()
                if not line:
                    continue
                # SSE comments start with ':'
                if line.startswith(':'):
                    continue
                if line.startswith('data:'):
                    data = line[5:].strip()
                    try:
                        payload = json.loads(data)
                    except Exception:
                        # ignore non-json events
                        continue
                    events.append(payload)
                    # quick exit if we saw game_over
                    try:
                        if (payload.get('message') and payload['message'].get('type') == 'game_over') or (
                            payload.get('messages') and any(m.get('type') == 'game_over' for m in payload.get('messages', []))
                        ):
                            print(f"[{name}] got game_over via SSE")
                            break
                    except Exception:
                        pass
    except Exception as e:
        print(f"[{name}] SSE error: {e}")


def main():
    s_host = requests.Session()
    s_p1 = requests.Session()
    s_p2 = requests.Session()

    # Give each session a distinct User-Agent so server-side deterministic device fingerprint treats them as different devices
    s_host.headers.update({'User-Agent': 'smoke-host/1.0'})
    s_p1.headers.update({'User-Agent': 'smoke-player1/1.0'})
    s_p2.headers.update({'User-Agent': 'smoke-player2/1.0'})

    # 1) create room as host
    print('[orchestrator] creating room')
    r = s_host.post(BASE + '/create_room', data={'room_name': ROOM, 'host_password': 'pw'})
    if r.status_code not in (302,200,200):
        print('create_room failed', r.status_code, r.text)
        sys.exit(1)
    print('[orchestrator] room created')
    # Ensure host session has host cookies by logging in as host (host_login will set host_token cookie)
    hlogin = s_host.post(f"{BASE}/host_login", data={'room_name': ROOM, 'host_password': 'pw'})
    print('[orchestrator] host_login response', hlogin.status_code)

    # 2) two players join
    for s, name in [(s_p1, 'Alice'), (s_p2, 'Bob')]:
        print(f"[orchestrator] {name} joining")
        j = s.post(f"{BASE}/room/{ROOM}/join", data={'name': name})
        if j.status_code not in (302,200):
            print('join failed', name, j.status_code, j.text)
            sys.exit(1)
        print(f"[orchestrator] {name} joined")

    # 3) attach SSE listeners for host, player1, player2
    events_host = []
    events_p1 = []
    events_p2 = []
    stop_evt = threading.Event()

    url = f"{BASE}/api/rooms/{ROOM}/chat/stream"
    th = threading.Thread(target=sse_listener, args=(s_host, url, 'HOST', events_host, stop_evt), daemon=True)
    t1 = threading.Thread(target=sse_listener, args=(s_p1, url, 'PLAYER1', events_p1, stop_evt), daemon=True)
    t2 = threading.Thread(target=sse_listener, args=(s_p2, url, 'PLAYER2', events_p2, stop_evt), daemon=True)

    th.start(); t1.start(); t2.start()

    # give SSE some time to connect
    time.sleep(1.2)

    # 4) prepare roles: add 2 villagers so assignment is valid, assign roles, and start the game
    print('[orchestrator] adding roles and assigning')
    # remove any existing roles and then add two Villager roles
    s_host.post(f"{BASE}/api/rooms/{ROOM}/reset-roles")
    s_host.post(f"{BASE}/api/rooms/{ROOM}/roles", data={'role_name': 'Villager', 'role_count': '2', 'role_faction': 'Villagers'})
    # assign roles (host must be authenticated via host cookie set on create_room)
    a = s_host.post(f"{BASE}/api/rooms/{ROOM}/assign")
    print('[orchestrator] assign response', a.status_code, a.text[:200])
    print('[debug] host cookies after create:', s_host.cookies.get_dict())
    try:
        print('[debug] assign request headers:', dict(a.request.headers))
    except Exception:
        pass
    # start the game
    st = s_host.post(f"{BASE}/api/rooms/{ROOM}/start-game")
    print('[orchestrator] start-game response', st.status_code, st.text[:200])
    print('[debug] host cookies before start-game:', s_host.cookies.get_dict())
    try:
        print('[debug] start-game request headers:', dict(st.request.headers))
    except Exception:
        pass

    # 5) host kills Bob — this should trigger game_over because mafia count will be 0 (all villagers)
    print('[orchestrator] host killing Bob to trigger win')
    resp = s_host.post(f"{BASE}/api/rooms/{ROOM}/kill-player", data={'player_name': 'Bob'})
    print('[orchestrator] kill-player response', resp.status_code, resp.text[:200])

    # wait for SSE listeners to pick up
    timeout = 8
    start = time.time()
    while time.time() - start < timeout:
        # check if all listeners saw game_over
        def got_game(evlist):
            for p in evlist:
                # check single message
                if p.get('message') and p['message'].get('type') == 'game_over':
                    return True
                # check backlog
                if p.get('messages') and any(m.get('type') == 'game_over' for m in p.get('messages', [])):
                    return True
            return False
        h = got_game(events_host)
        a = got_game(events_p1)
        b = got_game(events_p2)
        if h and a and b:
            print('[orchestrator] ALL clients received game_over')
            break
        time.sleep(0.25)

    stop_evt.set()
    time.sleep(0.2)

    print('HOST events:', json.dumps(events_host, indent=2)[:1000])
    print('PLAYER1 events:', json.dumps(events_p1, indent=2)[:1000])
    print('PLAYER2 events:', json.dumps(events_p2, indent=2)[:1000])

    if not (h and a and b):
        print('[orchestrator] NOT ALL clients received game_over within timeout')
        sys.exit(2)
    print('[orchestrator] smoke test PASSED')

if __name__ == '__main__':
    main()
