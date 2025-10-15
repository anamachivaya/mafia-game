
import os
import json
import time
from flask import Flask, request, jsonify, redirect, url_for, render_template, make_response, session, Response
from threading import Lock
from flask import send_from_directory

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')

# In-memory store (resets when the server restarts)
# rooms: map room_name -> {
#   host_password, player_password, host_token, created_at,
#   players: [{name, session_id}], roles: [{name,count}], assignments: {player: role}, game_started
# }
rooms = {}
roles_data = {}
factions_map = {}
lock = Lock()

# Room lifetime (seconds) - Extended to 4 hours
ROOM_TTL = int(os.environ.get('ROOM_TTL_SECONDS', 4 * 60 * 60))  # default 4 hours (14400 seconds)

# Cookie lifetime - Set to match room lifetime for consistency
COOKIE_TTL = ROOM_TTL  # 4 hours

def load_roles_data():
    """Load a merged roles.json file containing description and faction for each role.
    Populates roles_data and a quick lookup factions_map (lowercased keys).
    """
    global roles_data, factions_map
    try:
        with open('roles.json', 'r', encoding='utf-8') as f:
            roles_data = json.load(f)
        print(f"Loaded {len(roles_data)} roles from roles.json")
    except FileNotFoundError:
        print("Warning: roles.json not found. Role data will be empty.")
        roles_data = {}
    except json.JSONDecodeError as e:
        print(f"Error parsing roles.json: {e}")
        roles_data = {}

    # Build factions_map from roles_data for quick lookup (normalize keys)
    factions_map = {}
    for name, info in roles_data.items():
        if isinstance(info, dict):
            faction = info.get('faction') or ''
            factions_map[name.lower()] = faction

# Get role description (case insensitive)
def get_role_description(role_name):
    if not role_name:
        return "No role assigned yet."
    # exact match in roles_data (case sensitive first)
    if role_name in roles_data and isinstance(roles_data[role_name], dict):
        return roles_data[role_name].get('description', '')

    # case-insensitive search
    rn = role_name.lower()
    for k, v in roles_data.items():
        if k.lower() == rn and isinstance(v, dict):
            return v.get('description', '')

    return f"You are a {role_name}. No specific description available for this role."

# Add this helper function after the imports
def get_device_id():
    # First try to get existing device ID from cookie (most reliable)
    device_id = request.cookies.get('device_id')
    if device_id:
        return device_id
    
    # Generate deterministic device ID based on browser fingerprint (without random components)
    ip = request.remote_addr
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    
    # Collect browser characteristics (deterministic)
    user_agent = request.headers.get('User-Agent', '')
    accept_language = request.headers.get('Accept-Language', '')
    accept_encoding = request.headers.get('Accept-Encoding', '')
    accept = request.headers.get('Accept', '')
    
    # Create deterministic device fingerprint (no random components)
    import hashlib
    device_string = f"{ip}|{user_agent}|{accept_language}|{accept_encoding}|{accept}"
    device_id = hashlib.md5(device_string.encode()).hexdigest()[:16]
    
    return device_id

# Helper function to ensure device cookie is always set
def make_response_with_device_cookie(template_or_redirect, **kwargs):
    device_id = get_device_id()
    
    if hasattr(template_or_redirect, 'status_code'):  # It's already a response object
        resp = template_or_redirect
    elif template_or_redirect.startswith('http') or template_or_redirect.startswith('/'):  # It's a redirect
        resp = make_response(redirect(template_or_redirect))
    else:  # It's a template name
        resp = make_response(render_template(template_or_redirect, **kwargs))
    
    resp.set_cookie('device_id', device_id, max_age=COOKIE_TTL)  # Use COOKIE_TTL
    return resp

# Load descriptions on startup
load_roles_data()


def get_faction_for_role(role_name):
    if not role_name:
        return ''
    # check explicit mapping first
    r = role_name.strip().lower()
    if r in factions_map:
        return factions_map[r]
    # try partial match tokens
    for key, val in factions_map.items():
        if key in r:
            return val
    return ''

# ----------------- Routes -----------------
@app.route("/", methods=["GET"])
def home():
    error = request.args.get("error", "")
    player_ip = get_device_id()
    
    # Check if player has cookies for room and name
    player_name = request.cookies.get('player_name')
    room_name = request.cookies.get('room_name')
    
    if player_name and room_name:
        room = get_room_or_404(room_name)
        if room:
            with lock:
                # Verify this device is associated with this player in this room
                player_in_room = next((p for p in room['players'] if p.get('device_id') == player_ip and p['name'] == player_name), None)
                if player_in_room:
                    # Check if player is eliminated
                    is_eliminated = player_name in room.get('eliminated_players', [])
                    
                    if is_eliminated:
                        # Player has been eliminated - show elimination message
                        return make_response_with_device_cookie('eliminated.html', name=player_name, room_name=room_name, player_ip=player_ip)
                    
                    # Device matches the player - check if game started and role assigned
                    if room.get('game_started') and player_name in room.get('assignments', {}):
                        role = room['assignments'][player_name]
                        description = get_role_description(role)
                        # faction: prefer assignment_factions if present, else try auto-detect
                        faction = room.get('assignment_factions', {}).get(player_name) or get_faction_for_role(role)
                        return make_response_with_device_cookie('role.html', name=player_name, role=role, description=description, faction=faction, room_name=room_name, player_ip=player_ip)
                    else:
                        # Game not started yet or no role assigned, show thanks page
                        return make_response_with_device_cookie('thanks.html', name=player_name, room_name=room_name, player_ip=player_ip)
                else:
                    # Device doesn't match or player not in room - clear invalid cookies
                    response = make_response_with_device_cookie('home.html', error="Session invalid - please rejoin the room")
                    response.set_cookie('player_name', '', expires=0)
                    response.set_cookie('room_name', '', expires=0)
                    return response

    # Default landing page
    return make_response_with_device_cookie('home.html', error=error)


def _room_expired(room):
    import time
    # Prefer last_host_activity (activity-based TTL). Fall back to created_at for older rooms.
    last = room.get('last_host_activity') or room.get('created_at', 0)
    return (time.time() - last) > ROOM_TTL


def get_room_or_404(room_name):
    with lock:
        room = rooms.get(room_name)
        if not room:
            return None
        if _room_expired(room):
            # destroy room
            rooms.pop(room_name, None)
            return None
        return room


def _assign_chat_color_for_player(room, player_name):
    """Ensure a color is assigned for player_name in room. Thread-safe caller should hold lock."""
    if 'chat_colors' not in room:
        room['chat_colors'] = {}
    if player_name in room['chat_colors']:
        return room['chat_colors'][player_name]

    hue = None
    if room.get('chat_palette') and len(room.get('chat_palette')):
        hue = room['chat_palette'].pop(0)
    if hue is None:
        h = 0
        for ch in player_name:
            h = (h * 31 + ord(ch)) % 360
        hue = h
    col = f'hsl({hue},85%,45%)'
    room['chat_colors'][player_name] = col
    return col

@app.route("/create_room", methods=["GET", "POST"])
def create_room():
    # Host creates a room with a host password
    if request.method == 'GET':
        return render_template('create_room.html')

    room_name = request.form.get('room_name', '').strip()
    host_password = request.form.get('host_password', '').strip()

    if not room_name:
        return render_template('create_room.html', error='Room name is required')

    with lock:
        if room_name in rooms:
            return render_template('create_room.html', error='Room already exists')

        import time, secrets
        host_token = secrets.token_urlsafe(16)
    # prepare a shuffled high-contrast palette for chat colors
    import secrets
    PALETTE_SIZE = 24
    base_hues = [int(i * (360 / PALETTE_SIZE)) for i in range(PALETTE_SIZE)]
    rnd = secrets.SystemRandom()
    rnd.shuffle(base_hues)

    rooms[room_name] = {
            'host_password': host_password,
            'player_password': None,
            'host_token': host_token,
        'created_at': time.time(),
        # track last activity by the host to implement activity-based TTL
        'last_host_activity': time.time(),
            'players': [],
            'roles': [],
            'assignments': {},
            'game_started': False,
            'eliminated_players': [],
            # chat internals
            'chat': [],
            'chat_next_id': 1,
            'chat_colors': {},
            # a shuffled palette of high-contrast hues to assign per-sender
            'chat_palette': base_hues[:],  # pop from this when assigning new senders
            'chat_palette_orig': base_hues[:]
        }

    # Set host cookie to allow host access (4 hours)
    resp = make_response(redirect(url_for('host_dashboard', room_name=room_name)))
    resp.set_cookie('host_token', host_token, max_age=COOKIE_TTL)  # Changed from ROOM_TTL
    resp.set_cookie('host_room', room_name, max_age=COOKIE_TTL)    # Changed from ROOM_TTL
    return resp


@app.route('/host_login', methods=['GET', 'POST'])
def host_login():
    if request.method == 'GET':
        return render_template('host_login.html')

    room_name = request.form.get('room_name', '').strip()
    host_password = request.form.get('host_password', '').strip()

    if not room_name:
        return render_template('host_login.html', error='Room name is required')

    with lock:
        room = rooms.get(room_name)
        if not room or _room_expired(room):
            return render_template('host_login.html', error='Room not found or expired')
        if room.get('host_password') != host_password:
            return render_template('host_login.html', error='Incorrect password')

        # Issue host token
        host_token = room.get('host_token')

    resp = make_response(redirect(url_for('host_dashboard', room_name=room_name)))
    resp.set_cookie('host_token', host_token, max_age=COOKIE_TTL)  # Changed from ROOM_TTL
    resp.set_cookie('host_room', room_name, max_age=COOKIE_TTL)    # Changed from ROOM_TTL
    return resp


@app.route('/host/<room_name>', methods=['GET'])
def host_dashboard(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return 'Room not found or expired', 404

    # Validate host token cookie
    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        # Redirect to host login
        return redirect(url_for('host_login'))

    return render_template('host.html', room_name=room_name)


@app.route('/room/<room_name>', methods=['GET'])
def join_page(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return 'Room not found or expired', 404
    
    player_ip = get_device_id()
    
    with lock:
        # Check if this device has already joined this room
        existing_player = next((p for p in room['players'] if p.get('device_id') == player_ip), None)
        if existing_player:
            # Device already joined, redirect directly to thanks page
            resp = make_response_with_device_cookie('thanks.html', name=existing_player['name'], room_name=room_name, player_ip=player_ip)
            resp.set_cookie('player_name', existing_player['name'], max_age=COOKIE_TTL)
            resp.set_cookie('room_name', room_name, max_age=COOKIE_TTL)
            return resp
        
        # Check if room has a player password set
        password_required = room.get('player_password') is not None
    
    # Device hasn't joined yet, show join form
    error = request.args.get('error', '')
    return make_response_with_device_cookie('join.html', 
                                          room_name=room_name, 
                                          error=error, 
                                          password_required=password_required)  # Add this line


@app.after_request
def refresh_host_activity(response):
    """If a request includes valid host cookies for an existing room, refresh the
    room's last_host_activity timestamp and extend host cookies so that the room
    TTL is activity-based (ROOM_TTL since last host activity).
    """
    try:
        host_token = request.cookies.get('host_token')
        host_room = request.cookies.get('host_room')
        if host_token and host_room:
            with lock:
                room = rooms.get(host_room)
                if room and room.get('host_token') == host_token:
                    # update last activity
                    room['last_host_activity'] = time.time()
                    # refresh host cookies to give the host a full COOKIE_TTL from now
                    response.set_cookie('host_token', host_token, max_age=COOKIE_TTL)
                    response.set_cookie('host_room', host_room, max_age=COOKIE_TTL)
    except Exception:
        # never block response on refresh errors
        pass
    return response


@app.route('/enter', methods=['GET'])
def enter_room():
    # simple helper page to enter a room name
    return render_template('enter_room.html')


@app.route('/room/<room_name>/join', methods=['POST'])
def join_room(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return redirect(url_for('home', error='Room not found or expired'))

    name = request.form.get('name', '').strip()
    password = request.form.get('password', '').strip()
    player_ip = get_device_id()
    
    if not name:
        return redirect(url_for('join_page', room_name=room_name, error='Name is required'))

    with lock:
        # Check player password if set
        if room.get('player_password'):
            if not password or password != room.get('player_password'):
                return redirect(url_for('join_page', room_name=room_name, error='Incorrect password'))

        # Check if this device has already joined - redirect to thanks with existing name
        existing_player = next((p for p in room['players'] if p.get('device_id') == player_ip), None)
        if existing_player:
            # Device already joined, redirect to thanks page with existing name (ignore new name input)
            resp = make_response_with_device_cookie('thanks.html', name=existing_player['name'], room_name=room_name, player_ip=player_ip)
            resp.set_cookie('player_name', existing_player['name'], max_age=COOKIE_TTL)  # Changed from ROOM_TTL
            resp.set_cookie('room_name', room_name, max_age=COOKIE_TTL)                  # Changed from ROOM_TTL
            return resp

        # Check if the requested name is already taken by a different device
        existing_name_player = next((p for p in room['players'] if p['name'].lower() == name.lower()), None)
        if existing_name_player:
            return redirect(url_for('join_page', room_name=room_name, error='Name already taken'))

        # Add new player with device ID (only if device hasn't joined before)
    room['players'].append({'name': name, 'device_id': player_ip})
    # Pre-assign a chat color for this player to avoid flash on first message
    _assign_chat_color_for_player(room, name)

    resp = make_response_with_device_cookie('thanks.html', name=name, room_name=room_name, player_ip=player_ip)
    resp.set_cookie('player_name', name, max_age=COOKIE_TTL)      # Changed from ROOM_TTL
    resp.set_cookie('room_name', room_name, max_age=COOKIE_TTL)   # Changed from ROOM_TTL
    return resp



@app.route('/api/rooms/<room_name>/set-player-password', methods=['POST'])
def api_set_player_password(room_name):
    # Only host may set player password
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    password = request.form.get('password', '').strip()
    with lock:
        if password:
            room['player_password'] = password
        else:
            room['player_password'] = None

    return jsonify({'success': True, 'password_set': room['player_password'] is not None})

@app.route('/api/rooms/<room_name>/players', methods=['GET'])
def api_players(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    with lock:
        # Basic room info
        data = {
            'players': [p['name'] for p in room['players']],
            'count': len(room['players']),
            'password_set': room.get('player_password') is not None,
            'game_started': room.get('game_started', False),
            'assignments': room['assignments'] if room.get('game_started') else {},
            'eliminated_players': room.get('eliminated_players', []),
            'chat_colors': room.get('chat_colors', {}),
            'roles': room.get('roles', [])
        }
        # also include lightweight game-state pieces so player clients can render moderator dashboard
        data['phase'] = room.get('phase', 'lobby')
        data['night_step'] = room.get('night_step')
        data['last_night_events'] = room.get('last_night_events', {})
        data['last_night_killed'] = (room.get('last_night_events') or {}).get('killed', [])
        data['last_night_muted'] = (room.get('last_night_events') or {}).get('muted', None)
        # include a compact current_night_step description
        nstep = _current_night_step(room)
        if nstep and nstep.get('info'):
            data['current_night_step'] = {'index': nstep.get('index'), 'name': nstep.get('info').get('name'), 'actions': nstep.get('info').get('actions')}
        else:
            data['current_night_step'] = None
        # indicate whether the current night step already has an action recorded on the server
        try:
            if nstep and nstep.get('info'):
                step_actions = nstep.get('info', {}).get('actions', []) or []
                na = room.get('night_actions', {})
                data['current_night_step_completed'] = any(a in na for a in step_actions)
            else:
                data['current_night_step_completed'] = False
        except Exception:
            data['current_night_step_completed'] = False

        # indicate whether the current night step already has an action recorded on the server
        try:
            if nstep and nstep.get('info'):
                step_actions = nstep.get('info', {}).get('actions', []) or []
                na = room.get('night_actions', {})
                data['current_night_step_completed'] = any(a in na for a in step_actions)
            else:
                data['current_night_step_completed'] = False
        except Exception:
            data['current_night_step_completed'] = False

        # Determine the requesting player (prefer player_name cookie, fallback to device mapping)
        requester = request.cookies.get('player_name')
        if not requester:
            device_id = get_device_id()
            for p in room.get('players', []):
                if p.get('device_id') == device_id:
                    requester = p['name']
                    break

        # Provide visible roles tailored to the requesting player (e.g., mafia see other mafias and their roles)
        visible = []
        if data['game_started'] and requester and requester in room.get('assignments', {}):
            # ensure assignment_factions exists
            assignment_factions = room.get('assignment_factions', {})
            requester_faction = assignment_factions.get(requester) or get_faction_for_role(room['assignments'].get(requester))

            if requester_faction and requester_faction.lower() == 'mafia':
                # collect all players whose assigned faction is Mafia
                for player_name, assigned_role in room.get('assignments', {}).items():
                    pf = assignment_factions.get(player_name) or get_faction_for_role(assigned_role)
                    if pf and pf.lower() == 'mafia':
                        visible.append({
                            'name': player_name,
                            'role': assigned_role,
                            'faction': pf
                        })

        data['visible_roles'] = visible
    return jsonify(data)

@app.route('/api/rooms/<room_name>/roles', methods=['POST'])
def api_add_role(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    # only host may add roles
    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    role_name = request.form.get('role_name', '').strip()
    role_count = request.form.get('role_count', '1')
    role_faction = request.form.get('role_faction', '').strip()

    if not role_name:
        return jsonify({'error': 'Role name is required'}), 400

    try:
        count = int(role_count)
        if count < 1:
            return jsonify({'error': 'Role count must be at least 1'}), 400
    except ValueError:
        return jsonify({'error': 'Invalid role count'}), 400

    with lock:
        room['roles'].append({'name': role_name, 'count': count, 'faction': role_faction})

    return jsonify({'success': True})


## ----------------- Interactive game flow (night/day) -----------------

def _init_night_state(room):
    """Initialize per-night action containers."""
    room['phase'] = 'night'
    # night_step is an index into NIGHT_SEQUENCE (0-based)
    room['night_step'] = 0
    # night_actions will only include keys for actions that have been performed
    # (presence of a key indicates the corresponding role has acted this night).
    room['night_actions'] = {
        'mafia_final_chooser': None
    }
    # per-player private night reports (e.g., cop result)
    room['night_reports'] = {}
    # last night events to be revealed during day (killed list and muted)
    room['last_night_events'] = {'killed': [], 'muted': None}

    # Decide who may finalize the mafia kill this night (priority: godfather, then framer, else one random mafia)
    try:
        # find godfather alive
        godf = next((p for p, r in room.get('assignments', {}).items() if (r or '').lower().find('godfather') != -1 and p not in room.get('eliminated_players', [])), None)
        if godf:
            room['night_actions']['mafia_final_chooser'] = godf
        else:
            # framer if present will pick in its phase; but if no godfather, framer may be allowed to be finalizer — pick framer if alive
            framer = next((p for p, r in room.get('assignments', {}).items() if (r or '').lower().find('framer') != -1 and p not in room.get('eliminated_players', [])), None)
            if framer:
                room['night_actions']['mafia_final_chooser'] = framer
            else:
                # pick one alive mafia at random deterministically using player list order
                mafs = _alive_of_faction(room, 'mafia')
                if mafs:
                    # choose first alive mafia deterministically
                    room['night_actions']['mafia_final_chooser'] = sorted(mafs)[0]
                else:
                    room['night_actions']['mafia_final_chooser'] = None
    except Exception:
        room['night_actions']['mafia_final_chooser'] = None

    # After initializing, auto-advance through any steps that should be skipped
    # Cap iterations to avoid infinite loops in case of logic problems
    try:
        max_iters = len(NIGHT_SEQUENCE) + 2
        iters = 0
        while _should_auto_advance(room) and iters < max_iters:
            _advance_night_step(room)
            iters += 1
    except Exception:
        # On any unexpected error, leave the night_step as initialized (safe fallback)
        pass


# Define the sequential steps for the night. Each step lists allowed action types.
NIGHT_SEQUENCE = [
    {'name': 'mafia', 'actions': ['mafia_final']},
    {'name': 'framer', 'actions': ['framer_pick']},
    {'name': 'cop', 'actions': ['cop_check']},
    {'name': 'doctor', 'actions': ['doctor_save']},
    {'name': 'bodyguard', 'actions': ['bodyguard_save']},
    {'name': 'vigilante', 'actions': ['vigilante_kill']},
    {'name': 'sheriff', 'actions': ['sheriff_mute']},
]


def _current_night_step(room):
    idx = room.get('night_step', 0) or 0
    if idx < 0:
        idx = 0
    if idx >= len(NIGHT_SEQUENCE):
        return {'index': idx, 'info': None}
    return {'index': idx, 'info': NIGHT_SEQUENCE[idx]}


def _advance_night_step(room):
    # Move to next defined night step; if past last step, remain at last (host may call start-day)
    idx = room.get('night_step', 0) or 0
    if idx < len(NIGHT_SEQUENCE) - 1:
        room['night_step'] = idx + 1
        return True
    return False


def _alive_of_faction(room, faction_name):
    return [p for p in _alive_players(room) if (room.get('assignment_factions', {}).get(p) or get_faction_for_role(room.get('assignments', {}).get(p, '')) or '').lower() == faction_name.lower()]


def _any_alive_with_role_keyword(room, keyword):
    key = keyword.lower()
    for p, r in room.get('assignments', {}).items():
        if p in room.get('eliminated_players', []):
            continue
        if (r or '').lower().find(key) != -1:
            return True
    return False


def _should_auto_advance(room):
    """Decide whether to auto-advance to the next night step based on submitted actions and alive roles."""
    step = _current_night_step(room)
    info = step.get('info')
    if not info:
        return False
    name = info.get('name')
    actions = room.get('night_actions', {})

    # mafia step: advance if no mafia exist, mafia_final exists OR (no godfather alive and framer set)
    if name == 'mafia':
        # if there are no mafias alive, skip mafia step
        maf_alive = _alive_of_faction(room, 'mafia')
        if not maf_alive:
            return True
        # if mafia_final key present -> done (treat explicit "no kill" as an act)
        if 'mafia_final' in actions:
            return True
        # if godfather alive, wait for mafia_final
        godf = next((p for p, r in room.get('assignments', {}).items() if (r or '').lower().find('godfather') != -1 and p not in room.get('eliminated_players', [])), None)
        if godf:
            return False
        # no godfather alive: framer may choose or use suggestions
        if 'framer_pick' in actions:
            return True
        return False
        return False

    # framer step: advance when framer_pick present or no framer alive
    if name == 'framer':
        if 'framer_pick' in actions:
            return True
        if not _any_alive_with_role_keyword(room, 'framer'):
            return True
        return False

    # cop step
    if name == 'cop':
        if 'cop_check' in actions:
            return True
        # Sheriff is a separate role that mutes (does not perform cop checks). Only cop/detective roles count here.
        if not _any_alive_with_role_keyword(room, 'cop') and not _any_alive_with_role_keyword(room, 'detective'):
            return True
        return False

    # doctor step
    if name == 'doctor':
        # consider explicit doctor_save presence (including None) as acted so doctor isn't re-prompted when they choose "no save"
        if 'doctor_save' in actions:
            return True
        if not _any_alive_with_role_keyword(room, 'doctor') and not _any_alive_with_role_keyword(room, 'medic'):
            return True
        return False

    # bodyguard
    if name == 'bodyguard':
        # treat explicit choice (including None meaning "no protect") as acted
        if 'bodyguard_save' in actions:
            return True
        if not _any_alive_with_role_keyword(room, 'bodyguard') and not _any_alive_with_role_keyword(room, 'guard'):
            return True
        return False

    # vigilante
    if name == 'vigilante':
        if 'vigilante_kill' in actions:
            return True
        if not _any_alive_with_role_keyword(room, 'vigilante'):
            return True
        return False

    # sheriff
    if name == 'sheriff':
        if 'sheriff_mute' in actions:
            return True
        if not _any_alive_with_role_keyword(room, 'sheriff'):
            return True
        return False

    return False


def _auto_advance_until_valid(room):
    """Advance night_step while the current step should be auto-skipped.
    Bounded loop to avoid infinite advancement in case of logic errors.
    """
    try:
        max_iters = len(NIGHT_SEQUENCE) + 3
        iters = 0
        # keep advancing while current step indicates it should auto-advance
        while _should_auto_advance(room) and iters < max_iters:
            _advance_night_step(room)
            iters += 1
    except Exception:
        # silently ignore errors and leave room state as-is
        pass


def _resolve_night_actions(room):
    """Resolve night actions deterministically and update room state.
    Returns a dict with keys: 'killed' (list), 'muted' (player or None).
    Rules:
    - Only consider actions whose keys are present in room['night_actions'].
    - If an action key exists with value None, that means the role explicitly chose to do nothing.
    - Doctor save prevents death of the saved target.
    - Bodyguard protecting a target causes the bodyguard to die instead of the target (if bodyguard exists and alive).
    - Multiple kill attempts can target the same player; doctor can save to prevent death.
    - Only alive players may be targeted; invalid targets are ignored.
    """
    actions = room.get('night_actions', {}) or {}
    alive = set(_alive_players(room))

    # helper to normalize target presence and validity
    def valid_target(key):
        if key not in actions:
            return None
        t = actions.get(key)
        if not t:
            return None
        # only accept if currently alive
        return t if t in alive else None

    # Determine attempted kills
    attempts = []  # list of (source, target)
    # mafia kill: only if key present and target valid
    mafia_target = valid_target('mafia_final')
    if mafia_target:
        attempts.append(('mafia', mafia_target))

    vigilante_target = valid_target('vigilante_kill')
    if vigilante_target:
        attempts.append(('vigilante', vigilante_target))

    # Doctor save: may be present with None (explicit no-save) or a valid target
    doctor_save = None
    if 'doctor_save' in actions:
        ds = actions.get('doctor_save')
        if ds and ds in alive:
            doctor_save = ds
        else:
            doctor_save = None

    # Bodyguard protection (may be explicit None)
    bodyguard_save = None
    if 'bodyguard_save' in actions:
        bg = actions.get('bodyguard_save')
        if bg and bg in alive:
            bodyguard_save = bg
        else:
            bodyguard_save = None

    # find the bodyguard player's name (first alive with role name containing 'bodyguard' or 'guard')
    bodyguard_name = None
    for p, r in room.get('assignments', {}).items():
        if p in room.get('eliminated_players', []):
            continue
        if (r or '').lower().find('bodyguard') != -1 or (r or '').lower().find('guard') != -1:
            bodyguard_name = p
            break

    deaths = []
    for source, target in attempts:
        if not target:
            continue
        # doctor saves
        if doctor_save and target == doctor_save:
            continue
        # bodyguard protection
        if bodyguard_save and target == bodyguard_save and bodyguard_name and bodyguard_name not in room.get('eliminated_players', []):
            # bodyguard dies instead of target
            if bodyguard_name not in deaths:
                deaths.append(bodyguard_name)
            continue
        # otherwise target dies
        if target not in deaths:
            deaths.append(target)

    # Filter out already eliminated (safety)
    deaths = [d for d in deaths if d and d not in room.get('eliminated_players', [])]

    # Apply eliminations
    for d in deaths:
        room.setdefault('eliminated_players', []).append(d)

    # muted target if present
    muted = actions.get('sheriff_mute') if 'sheriff_mute' in actions else None

    # Persist night_reports were already handled by cop action; leave as-is
    room['last_night_events'] = {'killed': deaths, 'muted': muted}

    # check win condition and set phase accordingly will be done by caller
    return {'killed': deaths, 'muted': muted}


def _start_game(room):
    room['game_started'] = True
    room['eliminated_players'] = []
    room['phase'] = 'lobby'
    room['game_over'] = False
    room['winner'] = None


def _get_requesting_player(room):
    requester = request.cookies.get('player_name')
    if not requester:
        device_id = get_device_id()
        for p in room.get('players', []):
            if p.get('device_id') == device_id:
                requester = p['name']
                break
    return requester


def _role_of(room, player_name):
    return room.get('assignments', {}).get(player_name)


def _faction_of_role(room, role_name):
    # prefer assignment_factions if present
    if 'assignment_factions' in room:
        for p, r in room.get('assignments', {}).items():
            pass
    return get_faction_for_role(role_name)


def _alive_players(room):
    return [p['name'] for p in room.get('players', []) if p['name'] not in room.get('eliminated_players', [])]


def _count_alive_by_faction(room, faction_name):
    alive = _alive_players(room)
    c = 0
    for a in alive:
        f = room.get('assignment_factions', {}).get(a) or get_faction_for_role(room.get('assignments', {}).get(a))
        if f and f.lower() == faction_name.lower():
            c += 1
    return c


def _check_win_condition(room):
    # villagers win if no mafias left
    mafias = _count_alive_by_faction(room, 'mafia')
    villagers = len(_alive_players(room)) - mafias
    if mafias == 0:
        return 'villagers'
    # mafias win if mafias >= villagers
    if mafias >= max(1, villagers):
        return 'mafia'
    return None



@app.route('/api/rooms/<room_name>/lynch', methods=['POST'])
def api_lynch(room_name):
    """Host/moderator submits the lynch result at end of day. Accepts 'player_name' to kill and optional 'suicide_target'
    if the lynched player is a suicide bomber, the suicide_target (if provided) will also die.
    """
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    player_name = request.form.get('player_name', '').strip()
    suicide_target = request.form.get('suicide_target', '').strip() or None

    if not player_name:
        return jsonify({'error': 'player_name is required'}), 400

    with lock:
        if player_name in room.get('eliminated_players', []):
            return jsonify({'error': 'Player already eliminated'}), 400

        # ensure player exists
        if not any(p['name'] == player_name for p in room.get('players', [])):
            return jsonify({'error': 'Player not found in room'}), 404

        # eliminate the lynched player
        room.setdefault('eliminated_players', []).append(player_name)

        # handle suicide bomber
        role = room.get('assignments', {}).get(player_name, '') or ''
        if role.lower().find('suicide') != -1 or role.lower().find('bomber') != -1:
            if suicide_target and suicide_target not in room.get('eliminated_players', []):
                # ensure target exists and is alive
                if any(p['name'] == suicide_target for p in room.get('players', [])):
                    room.setdefault('eliminated_players', []).append(suicide_target)

        # record daytime event
        room['last_day_events'] = {'lynched': player_name, 'suicide_killed': suicide_target}

        # check win condition
        winner = _check_win_condition(room)
        if winner:
            room['game_over'] = True
            room['winner'] = winner
            room['phase'] = 'finished'

    return jsonify({'success': True, 'lynched': player_name, 'suicide_killed': suicide_target, 'winner': room.get('winner')})


@app.route('/api/rooms/<room_name>/start-game', methods=['POST'])
def api_start_game(room_name):
    """Host starts the game: mark game started and move to first night."""
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    with lock:
        # require assignments to exist
        if not room.get('assignments'):
            return jsonify({'error': 'Roles not assigned'}), 400
        # Mark game as started and immediately enter the first night
        _start_game(room)
        # Initialize night state so Start Game behaves as before and enters night phase
        _init_night_state(room)

    return jsonify({'success': True, 'phase': room.get('phase')})


@app.route('/api/rooms/<room_name>/start-night', methods=['POST'])
def api_start_night(room_name):
    """Host triggers transition to night: clear previous night state and start new night."""
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    with lock:
        if room.get('game_over'):
            return jsonify({'error': 'Game already over'}), 400
        _init_night_state(room)

    return jsonify({'success': True, 'phase': 'night'})


@app.route('/api/rooms/<room_name>/advance-night-step', methods=['POST'])
def api_advance_night_step(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    with lock:
        if room.get('phase') != 'night':
            return jsonify({'error': 'Not in night phase'}), 400

        # ensure night_step is set to a valid step (skip steps for roles that don't exist)
        _auto_advance_until_valid(room)
        advanced = _advance_night_step(room)
        return jsonify({'success': True, 'advanced': advanced, 'night_step': room.get('night_step')})


@app.route('/api/rooms/<room_name>/start-day', methods=['POST'])
def api_start_day(room_name):
    """Host resolves night actions and moves to day; reveals killed players and muted player."""
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    with lock:
        if room.get('phase') != 'night':
            return jsonify({'error': 'Not in night phase'}), 400

        # Resolve night actions via helper
        actions = room.get('night_actions', {})
        framer_pick = actions.get('framer_pick')

        resolved = _resolve_night_actions(room)
        deaths = resolved.get('killed', [])
        muted = resolved.get('muted')

        # generate private reports (cop) — if cop action was taken it should already have been persisted in api_night_action,
        # but ensure cop result exists if cop_check key present
        room['night_reports'] = room.get('night_reports', {})
        cop_target = actions.get('cop_check') if 'cop_check' in actions else None
        if cop_target:
            role = room.get('assignments', {}).get(cop_target)
            revealed = ''
            if role and role.lower().find('godfather') != -1:
                revealed = 'Villager'
            elif framer_pick and cop_target == framer_pick:
                revealed = 'Mafia'
            else:
                revealed = room.get('assignment_factions', {}).get(cop_target) or get_faction_for_role(role) or 'Unknown'

            cop_players = [p for p, r in room.get('assignments', {}).items() if (r or '').lower().find('cop') != -1 or (r or '').lower().find('sheriff') != -1]
            for cp in cop_players:
                room.setdefault('night_reports', {})[cp] = {'checked': cop_target, 'result': revealed}

        # check for win condition
        winner = _check_win_condition(room)
        if winner:
            room['game_over'] = True
            room['winner'] = winner
            room['phase'] = 'finished'
        else:
            room['phase'] = 'day'

    return jsonify({'success': True, 'killed': deaths, 'muted': actions.get('sheriff_mute'), 'phase': room.get('phase'), 'winner': room.get('winner')})


@app.route('/api/rooms/<room_name>/action', methods=['POST'])
def api_night_action(room_name):
    """Submit a night action for the requesting player. Actions vary by role:
    action_type: mafia_final|framer_pick|doctor_save|cop_check|vigilante_kill|bodyguard_save|sheriff_mute
    target: player name or empty for none
    """
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    with lock:
        if room.get('phase') != 'night':
            return jsonify({'error': 'Not in night phase'}), 400

        requester = _get_requesting_player(room)
        if not requester:
            return jsonify({'error': 'Unauthorized - must be a player in the room'}), 403
        if requester in room.get('eliminated_players', []):
            return jsonify({'error': 'Eliminated players cannot act'}), 400

        role = room.get('assignments', {}).get(requester, '')
        action_type = request.form.get('action_type', '').strip()
        target = request.form.get('target', '').strip() or None

        actions = room.setdefault('night_actions', {})

        # Enforce sequential night step: only allow actions that belong to the current night step
        step = _current_night_step(room)
        info = step.get('info')
        if info:
            allowed = info.get('actions', [])
            # allow the designated mafia_final_chooser to submit mafia_final even if the current
            # step isn't the mafia step (e.g., chooser is a Framer who acts in the framer step)
            chooser = room.get('night_actions', {}).get('mafia_final_chooser')
            if action_type not in allowed:
                if not (action_type == 'mafia_final' and chooser and requester == chooser):
                    return jsonify({'error': f'Action not allowed at this night step ({info.get("name")})'}), 400

        # Validate target must be alive unless action allows otherwise
        if target and target not in _alive_players(room):
            return jsonify({'error': 'Target not found or not alive'}), 400

        # Role-based permission checks
        lowrole = (role or '').lower()
        if action_type == 'mafia_final':
            # only the designated mafia_final_chooser may finalize
            chooser = room.get('night_actions', {}).get('mafia_final_chooser')
            if chooser and requester != chooser:
                return jsonify({'error': 'Only the designated mafia chooser may make the final mafia kill choice'}), 403
            # If no chooser set, only allow if requester is mafia
            if not chooser:
                if (room.get('assignment_factions', {}).get(requester) or get_faction_for_role(role) or '').lower() != 'mafia':
                    return jsonify({'error': 'Only mafias may select the final kill'}), 403
            # record the choice explicitly (key presence means acted; value may be None for no kill)
            actions['mafia_final'] = target
            if _should_auto_advance(room):
                _advance_night_step(room)
            return jsonify({'success': True})

        if action_type == 'framer_pick':
            if lowrole.find('framer') == -1:
                return jsonify({'error': 'Only Framer may perform this action'}), 403
            actions['framer_pick'] = target
            # If no godfather, framer becomes mafia_final chooser
            godf = next((p for p, r in room.get('assignments', {}).items() if (r or '').lower().find('godfather') != -1 and p not in room.get('eliminated_players', [])), None)
            if not godf:
                # If there is no godfather alive, the framer may act as the mafia final chooser.
                # Do NOT record the mafia_final kill here (framer's chosen target is only for framing).
                # Instead, mark the framer as the mafia_final_chooser so they (the framer) may submit
                # the actual mafia_final action during their step (or immediately if client allows).
                room.setdefault('night_actions', {})['mafia_final_chooser'] = requester
            if _should_auto_advance(room):
                _advance_night_step(room)
            return jsonify({'success': True})

        if action_type == 'doctor_save':
            if lowrole.find('doctor') == -1 and lowrole.find('medic') == -1:
                return jsonify({'error': 'Only Doctor/Medic may perform this action'}), 403
            # allow explicit None to represent choosing not to save anyone
            actions['doctor_save'] = target
            if _should_auto_advance(room):
                _advance_night_step(room)
            return jsonify({'success': True})

        if action_type == 'cop_check':
            # Only Cop or Detective may perform investigative checks; Sheriff does NOT reveal roles (it mutes instead).
            if lowrole.find('cop') == -1 and lowrole.find('detective') == -1:
                return jsonify({'error': 'Only Cop/Sheriff/Detective may perform this action'}), 403
            actions['cop_check'] = target
            if _should_auto_advance(room):
                _advance_night_step(room)

            # Build immediate cop result according to same rules used on start-day
            role = room.get('assignments', {}).get(target)
            framer_pick = room.get('night_actions', {}).get('framer_pick')
            revealed = ''
            if role and role.lower().find('godfather') != -1:
                revealed = 'Villager'
            elif framer_pick and target == framer_pick:
                revealed = 'Mafia'
            else:
                revealed = room.get('assignment_factions', {}).get(target) or get_faction_for_role(role) or 'Unknown'

            # attach to night_reports for persistence
            cop_players = [p for p, r in room.get('assignments', {}).items() if (r or '').lower().find('cop') != -1 or (r or '').lower().find('sheriff') != -1]
            for cp in cop_players:
                room.setdefault('night_reports', {})[cp] = {'checked': target, 'result': revealed}

            return jsonify({'success': True, 'cop_result': {'checked': target, 'result': revealed}})

        if action_type == 'vigilante_kill':
            if lowrole.find('vigilante') == -1:
                return jsonify({'error': 'Only Vigilante may perform this action'}), 403
            actions['vigilante_kill'] = target
            if _should_auto_advance(room):
                _advance_night_step(room)
            return jsonify({'success': True})

        if action_type == 'bodyguard_save':
            if lowrole.find('bodyguard') == -1 and lowrole.find('guard') == -1:
                return jsonify({'error': 'Only Bodyguard may perform this action'}), 403
            # allow empty target meaning choose not to protect
            actions['bodyguard_save'] = target
            if _should_auto_advance(room):
                _advance_night_step(room)
            return jsonify({'success': True})

        if action_type == 'sheriff_mute':
            # Only Sheriff may perform mute actions at this step
            if lowrole.find('sheriff') == -1:
                return jsonify({'error': 'Only Sheriff may perform this action'}), 403
            # presence of key indicates action taken; value may be None for explicit no-mute
            actions['sheriff_mute'] = target
            if _should_auto_advance(room):
                _advance_night_step(room)
            return jsonify({'success': True})

        return jsonify({'error': 'Unknown action or not permitted for your role'}), 400

        # unreachable



@app.route('/api/rooms/<room_name>/game-state', methods=['GET'])
def api_game_state(room_name):
    """Return a tailored view of the current game state for clients.
    Includes phase, last night events (for day), visible roles, night reports for the requester, alive players, and assignments only when appropriate.
    """
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    with lock:
        # ensure clients see a valid night step by auto-advancing past absent-role steps
        if room.get('phase') == 'night':
            _auto_advance_until_valid(room)
        data = {
            'phase': room.get('phase', 'lobby'),
            'night_step': room.get('night_step'),
            'last_night_events': room.get('last_night_events', {}),
            # convenience top-level fields for clients that want flat access
            'last_night_killed': (room.get('last_night_events') or {}).get('killed', []),
            'last_night_muted': (room.get('last_night_events') or {}).get('muted', None),
            'alive_players': _alive_players(room),
            'game_started': room.get('game_started', False),
            'game_over': room.get('game_over', False),
            'winner': room.get('winner')
        }

        # include human-friendly current night step info
        nstep = _current_night_step(room)
        if nstep and nstep.get('info'):
            data['current_night_step'] = {'index': nstep.get('index'), 'name': nstep.get('info').get('name'), 'actions': nstep.get('info').get('actions')}
        else:
            data['current_night_step'] = None

        requester = _get_requesting_player(room)
        # include visible role info same as api_players
        visible = []
        if room.get('game_started') and requester and requester in room.get('assignments', {}):
            assignment_factions = room.get('assignment_factions', {})
            requester_faction = assignment_factions.get(requester) or get_faction_for_role(room['assignments'].get(requester))
            if requester_faction and requester_faction.lower() == 'mafia':
                for player_name, assigned_role in room.get('assignments', {}).items():
                    pf = room.get('assignment_factions', {}).get(player_name) or get_faction_for_role(assigned_role)
                    if pf and pf.lower() == 'mafia':
                        visible.append({'name': player_name, 'role': assigned_role, 'faction': pf})
        data['visible_roles'] = visible

        # include night_reports for the requester if present
        if requester and room.get('night_reports') and requester in room.get('night_reports'):
            data['night_report'] = room['night_reports'][requester]

        # If requester is mafia, include mafia_final and who may finalize (private to mafias)
        try:
            requester_faction = room.get('assignment_factions', {}).get(requester) or get_faction_for_role(room.get('assignments', {}).get(requester, ''))
            if requester and requester_faction and requester_faction.lower() == 'mafia':
                na = room.get('night_actions', {})
                data['mafia_final'] = na.get('mafia_final')
                data['mafia_final_chooser'] = na.get('mafia_final_chooser')
            else:
                data['mafia_final'] = None
                data['mafia_final_chooser'] = None
        except Exception:
            data['mafia_final'] = None
            data['mafia_final_chooser'] = None

    return jsonify(data)



@app.route('/api/factions', methods=['GET'])
def api_factions():
    return jsonify({'factions': factions_map})

@app.route('/api/rooms/<room_name>/roles/<int:index>', methods=['DELETE'])
def api_remove_role(room_name, index):
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    with lock:
        if 0 <= index < len(room['roles']):
            room['roles'].pop(index)
            return jsonify({'success': True})

    return jsonify({'error': 'Invalid role index'}), 400

@app.route('/api/rooms/<room_name>/assign', methods=['POST'])
def api_assign_roles(room_name):
    import random
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    with lock:
        total_roles = sum(r['count'] for r in room['roles'])
        if total_roles != len(room['players']):
            return jsonify({'error': f'Total roles ({total_roles}) must equal number of players ({len(room["players"])})'}), 400

        role_list = []
        for role in room['roles']:
            role_list.extend([role['name']] * role['count'])

        random.shuffle(role_list)
        player_names = [p['name'] for p in room['players']]

        room['assignments'].clear()
        for i, player_name in enumerate(player_names):
            room['assignments'][player_name] = role_list[i]

        # populate assignment_factions mapping per player
        room['assignment_factions'] = {}
        # build a quick role->faction map from room['roles'] if present
        role_to_faction = {r['name']: r.get('faction', '') for r in room.get('roles', [])}
        for player_name, role_assigned in room['assignments'].items():
            faction = role_to_faction.get(role_assigned) or get_faction_for_role(role_assigned) or ''
            room['assignment_factions'][player_name] = faction

        room['game_started'] = True

    return jsonify({'success': True})

@app.route('/api/rooms/<room_name>/reset', methods=['POST'])
def api_reset(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    with lock:
        room['players'].clear()
        room['roles'].clear()
        room['assignments'].clear()
        room['assignment_factions'] = {}
        room['game_started'] = False
        room['player_password'] = None
        room['eliminated_players'] = []  # Add this line

    return jsonify({'success': True})


@app.route('/api/rooms/<room_name>/restart', methods=['POST'])
def api_restart(room_name):
    """Restart the game but keep players and roles. Clears assignments and eliminated players and marks game not started.
    Only host may perform this action.
    """
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    with lock:
        # Keep players and roles intact; clear assignments and per-game ephemeral state but keep players and roles
        # Capture eliminated players so we can notify them (spectators) before clearing the list
        eliminated_before = list(room.get('eliminated_players', []))
        room['assignments'].clear()
        room['eliminated_players'] = []
        room['assignment_factions'] = {}
        room['game_started'] = False
        # reset phase and night-related state
        room['phase'] = 'lobby'
        room['game_over'] = False
        room['winner'] = None
        # remove/clear night-specific containers so a fresh night can be started cleanly
        room.pop('night_actions', None)
        room.pop('night_reports', None)
        room.pop('last_night_events', None)
        room.pop('last_day_events', None)
        room.pop('night_step', None)

        # If there were eliminated spectators, push a server 'kick' chat message for each so
        # their waiting-room page can detect it and redirect them back to the lobby/home page.
        if eliminated_before:
            # ensure chat containers exist
            room.setdefault('chat', [])
            if 'chat_next_id' not in room:
                room['chat_next_id'] = 1
            if 'chat_colors' not in room:
                room['chat_colors'] = {}
            # ensure a color for server/system messages
            if 'Server' not in room['chat_colors']:
                room['chat_colors']['Server'] = 'hsl(210,20%,70%)'

            for p in eliminated_before:
                mid = room.get('chat_next_id', 1)
                room['chat_next_id'] = mid + 1
                msg = {
                    'id': mid,
                    'sender': 'Server',
                    'text': f'Returning eliminated players to lobby: {p}',
                    'ts': int(time.time()),
                    'client_id': None,
                    'color': room['chat_colors'].get('Server'),
                    # extra metadata that client-side SSE handlers look for
                    'type': 'kick',
                    'target': p
                }
                room['chat'].append(msg)
            # trim chat history
            if len(room['chat']) > 1000:
                room['chat'] = room['chat'][-1000:]

    return jsonify({'success': True})

@app.route('/api/rooms/<room_name>/reset-roles', methods=['POST'])
def api_reset_roles(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    with lock:
        room['roles'].clear()
        room['assignments'].clear()
        room['game_started'] = False

    return jsonify({'success': True})

# Update the leave function to handle room switching:
@app.route('/leave', methods=['POST'])
def leave():
    player_name = request.form.get('player_name')
    room_name = request.form.get('room_name') or request.cookies.get('room_name')
    player_ip = get_device_id()

    if player_name and room_name:
        with lock:
            room = rooms.get(room_name)
            if room:
                # Remove player only if device ID matches
                room['players'][:] = [p for p in room['players'] if not (p['name'] == player_name and p.get('device_id') == player_ip)]
                room['assignments'].pop(player_name, None)
                # Remove from eliminated players if present
                if 'eliminated_players' in room and player_name in room['eliminated_players']:
                    room['eliminated_players'].remove(player_name)

    response = make_response(redirect(url_for('home')))
    response.set_cookie('player_name', '', expires=0)
    response.set_cookie('room_name', '', expires=0)
    return response

@app.route("/healthz")
def health():
    return "ok", 200

@app.route('/api/rooms/<room_name>/debug', methods=['GET'])
def api_debug(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    with lock:
        data = {
            'players': room['players'],
            'roles': room['roles'],
            'assignments': room['assignments'],
            'game_started': room['game_started'],
            'password_set': room.get('player_password') is not None,
            'role_descriptions_loaded': len(roles_data),
            'eliminated_players': room.get('eliminated_players', [])  # Add this line
        }
    return jsonify(data)


@app.route('/api/rooms/<room_name>/chat', methods=['GET', 'POST'])
def api_room_chat(room_name):
    """Simple in-memory chat for spectators in a room.
    GET returns recent messages. POST accepts 'message' and adds it with the sender name determined from device cookie.
    """
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    # Ensure chat list exists
    with lock:
        if 'chat' not in room:
            room['chat'] = []

    if request.method == 'GET':
        # return last 200 messages
        with lock:
            msgs = room.get('chat', [])[-200:]
        return jsonify({'messages': msgs})

    # POST: add message
    # Identify sender primarily by player_name cookie (if present and valid), otherwise fall back to device mapping
    sender = request.cookies.get('player_name')
    with lock:
        if sender and any(p['name'] == sender for p in room.get('players', [])):
            pass
        else:
            # fallback: device id mapping
            device_id = get_device_id()
            sender = None
            for p in room.get('players', []):
                if p.get('device_id') == device_id:
                    sender = p['name']
                    break

    # If still no sender, allow the host (authenticated via host_token cookie) to post as 'Moderator'
    if not sender:
        host_token = request.cookies.get('host_token')
        host_room = request.cookies.get('host_room')
        if host_token and host_room == room_name and host_token == room.get('host_token'):
            sender = 'Moderator'

    if not sender:
        return jsonify({'error': 'Unauthorized - must be a player in the room or the host to post chat'}), 403

    text = request.form.get('message', '').strip()
    if not text:
        return jsonify({'error': 'Message required'}), 400

    # sanitize length
    if len(text) > 800:
        text = text[:800]

    import time
    # Accept optional client_id for deduping optimistic messages from clients
    client_id = request.form.get('client_id')

    with lock:
        # assign unique server id for the message
        mid = room.get('chat_next_id', 1)
        room['chat_next_id'] = mid + 1

        # assign or ensure a color exists for this sender
        if 'chat_colors' not in room:
            room['chat_colors'] = {}
        if sender not in room['chat_colors']:
            # Prefer to pop a hue from the room-specific shuffled high-contrast palette
            hue = None
            if room.get('chat_palette') and len(room.get('chat_palette')):
                hue = room['chat_palette'].pop(0)
            # If palette exhausted or missing, fall back to deterministic hue
            if hue is None:
                h = 0
                for ch in sender:
                    h = (h * 31 + ord(ch)) % 360
                hue = h
            room['chat_colors'][sender] = f'hsl({hue},85%,45%)'

        msg = {'id': mid, 'sender': sender, 'text': text, 'ts': int(time.time()), 'client_id': client_id, 'color': room['chat_colors'][sender]}
        room.setdefault('chat', []).append(msg)
        # cap chat history
        if len(room['chat']) > 1000:
            room['chat'] = room['chat'][-1000:]

    print(f"[CHAT] room={room_name} sender={sender} id={msg.get('id')} text={text}")
    return jsonify({'success': True, 'message': msg})


@app.route('/api/rooms/<room_name>/chat/stream')
def api_room_chat_stream(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    def event_stream():
        import time, json
        last_index = 0
        with lock:
            msgs = room.get('chat', [])
            # send full backlog on connect (bounded)
            backlog = msgs[-200:]
        if backlog:
            yield 'data: ' + json.dumps({'messages': backlog}) + '\n\n'
            last_index = len(msgs)
        else:
            last_index = len(msgs)

        # keep connection open, push new messages as they arrive
        while True:
            with lock:
                msgs = room.get('chat', [])
                if len(msgs) > last_index:
                    for m in msgs[last_index:]:
                        yield 'data: ' + json.dumps({'message': m}) + '\n\n'
                    last_index = len(msgs)
            # heartbeat to keep the connection alive
            yield ': heartbeat\n\n'
            time.sleep(0.5)

    return Response(event_stream(), mimetype='text/event-stream')

# Add endpoint to reload role descriptions
@app.route("/api/reload-descriptions", methods=["POST"])
def api_reload_descriptions():
    load_roles_data()
    return jsonify({"success": True, "descriptions_loaded": len(roles_data)})

# Add endpoint to kill a player
@app.route('/api/rooms/<room_name>/kill-player', methods=['POST'])
def api_kill_player(room_name):
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    # Only host may kill players
    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    player_name = request.form.get('player_name', '').strip()
    
    if not player_name:
        return jsonify({'error': 'Player name is required'}), 400

    with lock:
        # Check if game has started
        if not room.get('game_started', False):
            return jsonify({'error': 'Game has not started yet'}), 400
        
        # Check if player exists in the room
        player_exists = any(p['name'] == player_name for p in room['players'])
        if not player_exists:
            return jsonify({'error': 'Player not found in room'}), 404
        
        # Initialize eliminated_players list if it doesn't exist
        if 'eliminated_players' not in room:
            room['eliminated_players'] = []
        
        # Check if player is already eliminated
        if player_name in room['eliminated_players']:
            return jsonify({'error': 'Player is already eliminated'}), 400
        
        # Add player to eliminated list
        room['eliminated_players'].append(player_name)

        # check win condition after host elimination and set finished state if applicable
        try:
            winner = _check_win_condition(room)
            if winner:
                room['game_over'] = True
                room['winner'] = winner
                room['phase'] = 'finished'
        except Exception:
            # non-fatal if win check fails
            pass

    return jsonify({'success': True, 'message': f'{player_name} has been eliminated'})


@app.route('/api/rooms/<room_name>/kick-player', methods=['POST'])
def api_kick_player(room_name):
    """Host-only: remove a player from the room so they must rejoin.
    This is intended for lobby management (kicking a misbehaving player)."""
    room = get_room_or_404(room_name)
    if not room:
        return jsonify({'error': 'Room not found or expired'}), 404

    # Only host may kick players
    host_token = request.cookies.get('host_token')
    host_room = request.cookies.get('host_room')
    if not host_token or host_room != room_name or host_token != room.get('host_token'):
        return jsonify({'error': 'Unauthorized'}), 403

    player_name = request.form.get('player_name', '').strip()
    if not player_name:
        return jsonify({'error': 'Player name is required'}), 400

    with lock:
        # ensure players list exists
        if 'players' not in room:
            room['players'] = []

        # find and remove the player entry(s)
        before = len(room['players'])
        room['players'][:] = [p for p in room['players'] if p['name'] != player_name]
        after = len(room['players'])

        if before == after:
            return jsonify({'error': 'Player not found in room'}), 404

        # Remove assignments, eliminated status and any per-player state
        room['assignments'].pop(player_name, None)
        if 'eliminated_players' in room and player_name in room['eliminated_players']:
            room['eliminated_players'].remove(player_name)
        # Optionally free up chat color mapping for that player so a new player can get it
        if 'chat_colors' in room and player_name in room['chat_colors']:
            room['chat_colors'].pop(player_name, None)

        # Notify via chat stream so connected clients can react (e.g., kicked client clears cookies)
        try:
            import time
            if 'chat' not in room:
                room['chat'] = []
            mid = room.get('chat_next_id', 1)
            room['chat_next_id'] = mid + 1
            kick_msg = {
                'id': mid,
                'sender': 'SYSTEM',
                'text': f'Player {player_name} was kicked by host',
                'ts': int(time.time()),
                'type': 'kick',
                'target': player_name,
                'color': 'hsl(0,0%,50%)'
            }
            room.setdefault('chat', []).append(kick_msg)
            if len(room['chat']) > 1000:
                room['chat'] = room['chat'][-1000:]
        except Exception:
            # non-fatal if notification fails
            pass
    print(f"[KICK] room={room_name} kicked={player_name}")
    return jsonify({'success': True, 'message': f'{player_name} has been kicked from the room'})

@app.route('/static/<filename>')
def static_files(filename):
    return send_from_directory('static', filename)


@app.route('/role_descriptions.json', methods=['GET'])
def serve_role_descriptions():
    # For frontend compatibility return a mapping of roleName -> description
    flat = {}
    for name, info in roles_data.items():
        if isinstance(info, dict):
            flat[name] = info.get('description', '')
        else:
            # fallback: if roles_data stored as description string
            flat[name] = str(info)
    return jsonify(flat)


@app.route('/watch/<room_name>', methods=['GET'])
def watch_room(room_name):
    """Render the eliminated/waiting view directly for the current player (based on their player_name cookie).
    This avoids extra redirects and ensures they land in the waiting room with chat immediately.
    """
    room = get_room_or_404(room_name)
    if not room:
        return 'Room not found or expired', 404

    player_ip = get_device_id()
    player_name = request.cookies.get('player_name')
    if not player_name:
        # Not a logged-in player on this device — redirect to join page
        return redirect(url_for('join_page', room_name=room_name))

    # Only allow eliminated players to view the waiting room. If this player is not eliminated,
    # redirect them to the main home page (which will show their role if assigned).
    with lock:
        eliminated = room.get('eliminated_players', [])
    if player_name not in eliminated:
        # Redirect to home — home() will examine cookies and render role or thanks appropriately
        return redirect(url_for('home'))

    return make_response_with_device_cookie('eliminated.html', name=player_name, room_name=room_name, player_ip=player_ip)
# ----------------- Startup helpers -----------------
def find_free_port(preferred=5051):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("", preferred))
            return preferred
        except OSError:
            s.bind(("", 0))
            return s.getsockname()[1]

if __name__ == "__main__":
    # If running under the test harness, don't start the dev server here.
    # Tests should set PYTEST_RUNNING=1 in the environment to indicate this.
    if os.environ.get('PYTEST_RUNNING'):
        print("Detected PYTEST_RUNNING environment; skipping app.run() to allow test import")
    else:
        port = int(os.environ.get("PORT", 5051))
        print(f"Starting Mafia server on port {port}")
        app.run(host="0.0.0.0", port=port, debug=False)  # debug=False for production
