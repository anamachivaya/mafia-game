
import os
import json
from flask import Flask, request, jsonify, redirect, url_for, render_template, make_response, session
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
role_descriptions = {}  # Store role descriptions from JSON
lock = Lock()

# Room lifetime (seconds) - Extended to 1 hour
ROOM_TTL = int(os.environ.get('ROOM_TTL_SECONDS', 60 * 60))  # default 1 hour (3600 seconds)

# Cookie lifetime - Set to match room lifetime for consistency
COOKIE_TTL = ROOM_TTL  # 1 hour

# Load role descriptions from JSON file
def load_role_descriptions():
    global role_descriptions
    try:
        with open('role_descriptions.json', 'r', encoding='utf-8') as f:
            role_descriptions = json.load(f)
        print(f"Loaded {len(role_descriptions)} role descriptions")
    except FileNotFoundError:
        print("Warning: role_descriptions.json not found. Role descriptions will be empty.")
        role_descriptions = {}
    except json.JSONDecodeError as e:
        print(f"Error parsing role_descriptions.json: {e}")
        role_descriptions = {}

# Get role description (case insensitive)
def get_role_description(role_name):
    if not role_name:
        return "No role assigned yet."
    
    # Try exact match first
    if role_name in role_descriptions:
        return role_descriptions[role_name]
    
    # Try case insensitive match
    role_name_lower = role_name.lower()
    for key, description in role_descriptions.items():
        if key.lower() == role_name_lower:
            return description
    
    # Default description if role not found
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
load_role_descriptions()

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
                        return make_response_with_device_cookie('role.html', name=player_name, role=role, description=description, room_name=room_name, player_ip=player_ip)  # Added room_name here
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
    return (time.time() - room.get('created_at', 0)) > ROOM_TTL


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
        rooms[room_name] = {
            'host_password': host_password,
            'player_password': None,
            'host_token': host_token,
            'created_at': time.time(),
            'players': [],
            'roles': [],
            'assignments': {},
            'game_started': False,
            'eliminated_players': []  # Add this line
        }

    # Set host cookie to allow host access (1 hour)
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
        data = {
            'players': [p['name'] for p in room['players']],
            'count': len(room['players']),
            'password_set': room.get('player_password') is not None,
            'game_started': room.get('game_started', False),
            'assignments': room['assignments'] if room.get('game_started') else {},
            'eliminated_players': room.get('eliminated_players', [])  # Add this line
        }
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

    if not role_name:
        return jsonify({'error': 'Role name is required'}), 400

    try:
        count = int(role_count)
        if count < 1:
            return jsonify({'error': 'Role count must be at least 1'}), 400
    except ValueError:
        return jsonify({'error': 'Invalid role count'}), 400

    with lock:
        room['roles'].append({'name': role_name, 'count': count})

    return jsonify({'success': True})

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
        # Keep players and roles intact; clear assignments and eliminated players and mark not started
        room['assignments'].clear()
        room['eliminated_players'] = []
        room['game_started'] = False

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
            'role_descriptions_loaded': len(role_descriptions),
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

    if not sender:
        return jsonify({'error': 'Unauthorized - must be a player in the room to post chat'}), 403

    text = request.form.get('message', '').strip()
    if not text:
        return jsonify({'error': 'Message required'}), 400

    # sanitize length
    if len(text) > 800:
        text = text[:800]

    import time
    msg = {'sender': sender, 'text': text, 'ts': int(time.time())}
    with lock:
        room.setdefault('chat', []).append(msg)
        # cap chat history
        if len(room['chat']) > 1000:
            room['chat'] = room['chat'][-1000:]

    print(f"[CHAT] room={room_name} sender={sender} text={text}")
    return jsonify({'success': True, 'message': msg})

# Add endpoint to reload role descriptions
@app.route("/api/reload-descriptions", methods=["POST"])
def api_reload_descriptions():
    load_role_descriptions()
    return jsonify({"success": True, "descriptions_loaded": len(role_descriptions)})

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

    return jsonify({'success': True, 'message': f'{player_name} has been eliminated'})

@app.route('/static/<filename>')
def static_files(filename):
    return send_from_directory('static', filename)


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
    port = int(os.environ.get("PORT", 5051))
    print(f"Starting Mafia server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)  # debug=False for production
