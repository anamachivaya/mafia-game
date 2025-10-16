import requests
import time

BASE = 'http://127.0.0.1:5051'
ROOM = 'testroom'
HOST_PW = 'hpw'

s_host = requests.Session()
s_bomber = requests.Session()
s_victim = requests.Session()

# Give each player session a unique device_id cookie so server treats them as different devices
s_bomber.cookies.set('device_id', 'dev-bomber')
s_victim.cookies.set('device_id', 'dev-victim')

# Helper
def p(msg):
    print('\n=== ' + msg)

# Wait for server
for i in range(20):
    try:
        r = requests.get(BASE + '/healthz', timeout=1)
        if r.status_code == 200:
            print('Server healthy')
            break
    except Exception:
        pass
    time.sleep(0.5)
else:
    print('Server did not become ready');
    raise SystemExit(1)

p('Create room as host')
r = s_host.post(BASE + '/create_room', data={'room_name': ROOM, 'host_password': HOST_PW})
print('create_room status', r.status_code, r.url)
print('host cookies:', s_host.cookies.get_dict())

p('Player join: bomber')
r = s_bomber.post(f"{BASE}/room/{ROOM}/join", data={'name': 'Bomber'})
print('bomber join status', r.status_code, r.url)
print('bomber cookies:', s_bomber.cookies.get_dict())

p('Player join: victim')
r = s_victim.post(f"{BASE}/room/{ROOM}/join", data={'name': 'Victim'})
print('victim join status', r.status_code, r.url)
print('victim cookies:', s_victim.cookies.get_dict())

p('Host adds roles (Suicide Bomber and Villager)')
r = s_host.post(f"{BASE}/api/rooms/{ROOM}/roles", data={'role_name': 'Suicide Bomber', 'role_count': '1', 'role_faction': ''})
print('add role1', r.status_code, r.text)
r = s_host.post(f"{BASE}/api/rooms/{ROOM}/roles", data={'role_name': 'Villager', 'role_count': '1', 'role_faction': ''})
print('add role2', r.status_code, r.text)

p('Host assign roles')
r = s_host.post(f"{BASE}/api/rooms/{ROOM}/assign")
print('assign', r.status_code, r.text)

p('Start game')
r = s_host.post(f"{BASE}/api/rooms/{ROOM}/start-game")
print('start-game', r.status_code, r.text)

# Let clients fetch assignments
time.sleep(0.3)

p('Check players from bomber perspective')
r = s_bomber.get(f"{BASE}/api/rooms/{ROOM}/players")
print('bomber players GET', r.status_code, r.json())

p('Check players from victim perspective')
r = s_victim.get(f"{BASE}/api/rooms/{ROOM}/players")
print('victim players GET', r.status_code, r.json())

# Identify who is bomber according to assignments
assigns = r.json().get('assignments', {})
# assignments returned only if game_started true - check host debug
r2 = s_host.get(f"{BASE}/api/rooms/{ROOM}/debug")
print('host debug assignments:', r2.json().get('assignments'))
assigns = r2.json().get('assignments', {})
print('assigns map', assigns)

bname = None
for k, v in assigns.items():
    if 'suicide' in (v or '').lower() or 'bomber' in (v or '').lower():
        bname = k
print('detected bomber assigned to:', bname)
if not bname:
    print('Could not detect bomber assignment; abort')
    raise SystemExit(2)

p('Host lynches the bomber (no suicide_target)')
r = s_host.post(f"{BASE}/api/rooms/{ROOM}/lynch", data={'player_name': bname})
print('lynch response', r.status_code, r.text)

p('Bomber polls for suicide_prompt')
for i in range(10):
    r = s_bomber.get(f"{BASE}/api/rooms/{ROOM}/players")
    j = r.json()
    print('poll', i, 'suicide_prompt', j.get('suicide_prompt'))
    if j.get('suicide_prompt', {}).get('active'):
        choices = j.get('suicide_prompt', {}).get('choices') or []
        print('choices', choices)
        break
    time.sleep(0.3)
else:
    print('Bomber did not receive suicide prompt'); raise SystemExit(3)

# Pick first available choice
if not choices:
    print('No choices to kill; abort'); raise SystemExit(4)
choice = choices[0]
print('Bomber chooses to kill', choice)

p('Bomber submits suicide choice')
r = s_bomber.post(f"{BASE}/api/rooms/{ROOM}/suicide", data={'target': choice})
print('suicide POST', r.status_code, r.text)

p('Final room debug state')
r = s_host.get(f"{BASE}/api/rooms/{ROOM}/debug")
print(r.status_code, r.json())

p('Players view final')
r = s_bomber.get(f"{BASE}/api/rooms/{ROOM}/players")
print('bomber players', r.status_code, r.json())
r = s_victim.get(f"{BASE}/api/rooms/{ROOM}/players")
print('victim players', r.status_code, r.json())

print('\nSMOKE TEST COMPLETE')
