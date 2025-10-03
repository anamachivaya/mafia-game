
import os
import json
from flask import Flask, request, jsonify, redirect, url_for, render_template, make_response, session
from threading import Lock

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

# Room lifetime (seconds)
ROOM_TTL = int(os.environ.get('ROOM_TTL_SECONDS', 15 * 60))  # default 15 minutes

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

# Load descriptions on startup
load_role_descriptions()

# ----------------- Routes -----------------
@app.route("/", methods=["GET"])
def home():
    error = request.args.get("error", "")
    player_ip = request.remote_addr
    
    # Check if player has cookies for room and name
    player_name = request.cookies.get('player_name')
    room_name = request.cookies.get('room_name')
    
    if player_name and room_name:
        room = get_room_or_404(room_name)
        if room:
            # FIXED: Verify this IP is associated with this player in this room
            player_in_room = next((p for p in room['players'] if p.get('ip') == player_ip and p['name'] == player_name), None)
            if player_in_room:
                # IP matches the player - check if game started and role assigned
                if room.get('game_started') and player_name in room.get('assignments', {}):
                    role = room['assignments'][player_name]
                    description = get_role_description(role)
                    return render_template('role.html', name=player_name, role=role, description=description)
                else:
                    # Game not started yet or no role assigned, show thanks page
                    return render_template('thanks.html', name=player_name, room_name=room_name)
            else:
                # IP doesn't match or player not in room - clear invalid cookies
                response = make_response(render_template('home.html', error=error))
                response.set_cookie('player_name', '', expires=0)
                response.set_cookie('room_name', '', expires=0)
                return response

    # Default landing page
    return render_template('home.html', error=error)


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
            'game_started': False
        }

    # Set host cookie to allow host access (short lived)
    resp = make_response(redirect(url_for('host_dashboard', room_name=room_name)))
    resp.set_cookie('host_token', host_token, max_age=ROOM_TTL)
    resp.set_cookie('host_room', room_name, max_age=ROOM_TTL)
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
    resp.set_cookie('host_token', host_token, max_age=ROOM_TTL)
    resp.set_cookie('host_room', room_name, max_age=ROOM_TTL)
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
    
    player_ip = request.remote_addr
    
    with lock:
        # Check if this IP has already joined this room
        existing_player = next((p for p in room['players'] if p.get('ip') == player_ip), None)
        if existing_player:
            # IP already joined, redirect directly to thanks page
            resp = make_response(render_template('thanks.html', name=existing_player['name'], room_name=room_name))
            resp.set_cookie('player_name', existing_player['name'], max_age=ROOM_TTL)
            resp.set_cookie('room_name', room_name, max_age=ROOM_TTL)
            return resp
    
    # IP hasn't joined yet, show join form
    error = request.args.get('error', '')
    return render_template('join.html', room_name=room_name, error=error)


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
    player_ip = request.remote_addr
    
    if not name:
        return redirect(url_for('join_page', room_name=room_name, error='Name is required'))

    with lock:
        # Check player password if set
        if room.get('player_password'):
            if not password or password != room.get('player_password'):
                return redirect(url_for('join_page', room_name=room_name, error='Incorrect password'))

        # Check if this IP has already joined
        existing_player = next((p for p in room['players'] if p.get('ip') == player_ip), None)
        if existing_player:
            # IP already joined, redirect to thanks page with existing name
            resp = make_response(render_template('thanks.html', name=existing_player['name'], room_name=room_name))
            resp.set_cookie('player_name', existing_player['name'], max_age=ROOM_TTL)
            resp.set_cookie('room_name', room_name, max_age=ROOM_TTL)
            return resp

        # Check if name is already taken by a different IP
        existing_names = [p['name'] for p in room['players']]
        if name in existing_names:
            return redirect(url_for('join_page', room_name=room_name, error='Name already taken'))

        # Add new player with IP
        room['players'].append({'name': name, 'ip': player_ip})

    resp = make_response(render_template('thanks.html', name=name, room_name=room_name))
    resp.set_cookie('player_name', name, max_age=ROOM_TTL)
    resp.set_cookie('room_name', room_name, max_age=ROOM_TTL)
    return resp

@app.route("/", methods=["GET"])
def root_redirect():
    # redirect to home (index)
    return redirect(url_for('home'))



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
            'assignments': room['assignments'] if room.get('game_started') else {}
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

@app.route('/leave', methods=['POST'])
def leave():
    player_name = request.form.get('player_name')
    room_name = request.form.get('room_name') or request.cookies.get('room_name')
    player_ip = request.remote_addr

    if player_name and room_name:
        with lock:
            room = rooms.get(room_name)
            if room:
                # Remove player only if IP matches
                room['players'][:] = [p for p in room['players'] if not (p['name'] == player_name and p.get('ip') == player_ip)]
                room['assignments'].pop(player_name, None)

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
            'role_descriptions_loaded': len(role_descriptions)
        }
    return jsonify(data)

# Add endpoint to reload role descriptions
@app.route("/api/reload-descriptions", methods=["POST"])
def api_reload_descriptions():
    load_role_descriptions()
    return jsonify({"success": True, "descriptions_loaded": len(role_descriptions)})

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
