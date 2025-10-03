
import os
import json
from flask import Flask, request, jsonify, redirect, url_for, render_template, make_response, session
from threading import Lock

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')

# In-memory store (resets when the server restarts)
players = []  # List of {"name": "player_name", "session_id": "session_id"}
roles = []    # List of {"name": "role_name", "count": number}
assignments = {}  # Dictionary mapping player names to roles
game_started = False
game_password = None  # Store the game password
role_descriptions = {}  # Store role descriptions from JSON
lock = Lock()

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
    
    # Check if player already has a role assigned
    player_name = request.cookies.get("player_name")
    if player_name and player_name in assignments:
        role = assignments[player_name]
        description = get_role_description(role)
        return render_template("role.html", name=player_name, role=role, description=description)
    
    return render_template("join.html", error=error)

@app.route("/join", methods=["POST"])
def join():
    name = request.form.get("name", "").strip()
    password = request.form.get("password", "").strip()
    
    if not name:
        return redirect(url_for("home", error="Name is required"))
    
    with lock:
        # Check if game has a password set
        if game_password is not None:
            if not password:
                return redirect(url_for("home", error="Password is required"))
            if password != game_password:
                return redirect(url_for("home", error="Incorrect password"))
        
        # Check if name is already taken
        existing_names = [p["name"] for p in players]
        if name in existing_names:
            return redirect(url_for("home", error="Name already taken"))
        
        # Add player
        session_id = request.cookies.get("session_id", os.urandom(16).hex())
        players.append({"name": name, "session_id": session_id})
    
    response = make_response(render_template("thanks.html", name=name))
    response.set_cookie("player_name", name, max_age=3600)
    response.set_cookie("session_id", session_id, max_age=3600)
    return response

@app.route("/host", methods=["GET"])
def host():
    return render_template("host.html")

@app.route("/api/set-password", methods=["POST"])
def api_set_password():
    password = request.form.get("password", "").strip()
    
    with lock:
        global game_password
        if password:
            game_password = password
        else:
            game_password = None
    
    return jsonify({"success": True, "password_set": game_password is not None})

@app.route("/api/players", methods=["GET"])
def api_players():
    with lock:
        data = {
            "players": [p["name"] for p in players],
            "count": len(players),
            "password_set": game_password is not None,
            "game_started": game_started,
            "assignments": assignments if game_started else {}
        }
    return jsonify(data)

@app.route("/api/roles", methods=["POST"])
def api_add_role():
    role_name = request.form.get("role_name", "").strip()
    role_count = request.form.get("role_count", "1")
    
    if not role_name:
        return jsonify({"error": "Role name is required"}), 400
    
    try:
        count = int(role_count)
        if count < 1:
            return jsonify({"error": "Role count must be at least 1"}), 400
    except ValueError:
        return jsonify({"error": "Invalid role count"}), 400
    
    with lock:
        roles.append({"name": role_name, "count": count})
    
    return jsonify({"success": True})

@app.route("/api/roles/<int:index>", methods=["DELETE"])
def api_remove_role(index):
    with lock:
        if 0 <= index < len(roles):
            roles.pop(index)
            return jsonify({"success": True})
    
    return jsonify({"error": "Invalid role index"}), 400

@app.route("/api/assign", methods=["POST"])
def api_assign_roles():
    import random
    
    with lock:
        global game_started
        
        # Calculate total roles needed
        total_roles = sum(role["count"] for role in roles)
        if total_roles != len(players):
            return jsonify({"error": f"Total roles ({total_roles}) must equal number of players ({len(players)})"}), 400
        
        # Create role list
        role_list = []
        for role in roles:
            role_list.extend([role["name"]] * role["count"])
        
        # Shuffle and assign
        random.shuffle(role_list)
        player_names = [p["name"] for p in players]
        
        assignments.clear()
        for i, player_name in enumerate(player_names):
            assignments[player_name] = role_list[i]
        
        game_started = True
    
    return jsonify({"success": True})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    with lock:
        global game_started, game_password
        players.clear()
        roles.clear()
        assignments.clear()
        game_started = False
        game_password = None
    
    return jsonify({"success": True})

@app.route("/api/reset-roles", methods=["POST"])
def api_reset_roles():
    with lock:
        global game_started
        roles.clear()
        assignments.clear()
        game_started = False
    
    return jsonify({"success": True})

@app.route("/leave", methods=["POST"])
def leave():
    player_name = request.form.get("player_name")
    
    if player_name:
        with lock:
            # Remove from players list
            players[:] = [p for p in players if p["name"] != player_name]
            # Remove from assignments if present
            assignments.pop(player_name, None)
    
    response = make_response(redirect(url_for("home")))
    response.set_cookie("player_name", "", expires=0)
    response.set_cookie("session_id", "", expires=0)
    return response

@app.route("/healthz")
def health():
    return "ok", 200

@app.route("/api/debug", methods=["GET"])
def api_debug():
    with lock:
        data = {
            "players": players,
            "roles": roles,
            "assignments": assignments,
            "game_started": game_started,
            "password_set": game_password is not None,
            "role_descriptions_loaded": len(role_descriptions)
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
