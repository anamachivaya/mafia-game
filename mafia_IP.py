
from flask import Flask, request, jsonify, redirect, url_for, render_template, make_response
from threading import Lock
import os
import socket
import random

app = Flask(__name__)

# In-memory store (resets when the server restarts)
players = []  # List of player names
roles = []    # List of {"name": "role_name", "count": number}
assignments = {}  # Dictionary mapping player names to roles
game_started = False
lock = Lock()

# ----------------- Routes -----------------
@app.route("/", methods=["GET"])
def home():
    error = request.args.get("error", "")
    with lock:
        if game_started and request.remote_addr in [p.get('ip') for p in players]:
            # Player already joined and game started, show their role
            player_name = next((p['name'] for p in players if p.get('ip') == request.remote_addr), None)
            if player_name and player_name in assignments:
                return render_template("role.html", name=player_name, role=assignments[player_name])
    return render_template("join.html", error=error)

@app.route("/join", methods=["POST"])
def join():
    name = (request.form.get("name") or "").strip()
    if not name:
        return redirect(url_for("home", error="Please enter a name."))

    # Normalize whitespace and limit length
    name = " ".join(name.split())[:50]

    with lock:
        if game_started:
            return redirect(url_for("home", error="Game has already started."))
        
        # Check if name already exists
        if any(p['name'].lower() == name.lower() for p in players):
            return redirect(url_for("home", error="Name already taken."))
        
        # Add player with IP for role assignment later
        players.append({"name": name, "ip": request.remote_addr})

    print(f"[JOIN] Player joined: {name}", flush=True)
    return render_template("thanks.html", name=name)

@app.route("/host", methods=["GET"])
def host():
    return render_template("host.html")

@app.route("/api/players", methods=["GET"])
def api_players():
    with lock:
        total_roles = sum(role['count'] for role in roles)
        data = {
            "players": [p['name'] for p in players],
            "count": len(players),
            "roles": roles,
            "total_roles": total_roles,
            "game_started": game_started,
            "can_start": len(players) == total_roles and total_roles > 0
        }
    return jsonify(data)

@app.route("/api/roles", methods=["POST"])
def api_add_role():
    data = request.get_json()
    role_name = data.get("name", "").strip()
    role_count = data.get("count", 0)
    
    if not role_name or role_count <= 0:
        return jsonify({"error": "Invalid role name or count"}), 400
    
    with lock:
        if game_started:
            return jsonify({"error": "Game already started"}), 400
        roles.append({"name": role_name, "count": role_count})
    
    return jsonify({"success": True})

@app.route("/api/roles/<int:index>", methods=["DELETE"])
def api_remove_role(index):
    with lock:
        if game_started:
            return jsonify({"error": "Game already started"}), 400
        if 0 <= index < len(roles):
            roles.pop(index)
            return jsonify({"success": True})
    return jsonify({"error": "Invalid role index"}), 400

@app.route("/api/assign", methods=["POST"])
def api_assign_roles():
    global game_started
    with lock:
        if game_started:
            return jsonify({"error": "Game already started"}), 400
        
        total_roles = sum(role['count'] for role in roles)
        if len(players) != total_roles:
            return jsonify({"error": f"Need exactly {total_roles} players, have {len(players)}"}), 400
        
        if total_roles == 0:
            return jsonify({"error": "No roles configured"}), 400
        
        # Create list of all roles
        all_roles = []
        for role in roles:
            all_roles.extend([role['name']] * role['count'])
        
        # Shuffle and assign
        random.shuffle(all_roles)
        player_names = [p['name'] for p in players]
        
        for i, player_name in enumerate(player_names):
            assignments[player_name] = all_roles[i]
        
        game_started = True
        
        print(f"[ASSIGN] Roles assigned: {assignments}", flush=True)
    
    return jsonify({"success": True})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    with lock:
        global game_started
        players.clear()
        roles.clear()
        assignments.clear()
        game_started = False
    
    print("[RESET] Game reset", flush=True)
    return jsonify({"success": True})

@app.route("/api/reset-roles", methods=["POST"])
def api_reset_roles():
    with lock:
        if game_started:
            return jsonify({"error": "Game already started"}), 400
        roles.clear()
    
    print("[RESET-ROLES] Roles cleared", flush=True)
    return jsonify({"success": True})

@app.route("/leave", methods=["POST"])
def leave():
    player_name = (request.form.get("player_name") or "").strip()
    
    with lock:
        if game_started:
            return redirect(url_for("home", error="Cannot leave after game has started."))
        
        if not player_name:
            return redirect(url_for("home", error="Invalid request."))
        
        # Find and remove the specific player by name
        original_count = len(players)
        players[:] = [p for p in players if p.get('name') != player_name]
        
        # Check if player was actually removed
        if len(players) == original_count:
            return redirect(url_for("home", error="Player not found."))
        
        # Also remove from assignments if they were assigned (shouldn't happen before game starts, but just in case)
        if player_name in assignments:
            del assignments[player_name]
    
    print(f"[LEAVE] Player left: {player_name}", flush=True)
    return redirect(url_for("home"))

@app.route("/healthz")
def health():
    return "ok", 200

@app.route("/api/debug", methods=["GET"])
def api_debug():
    with lock:
        return jsonify({
            "players": players,
            "roles": roles,
            "assignments": assignments,
            "game_started": game_started,
            "total_roles": sum(role['count'] for role in roles),
            "player_count": len(players)
        })

# ----------------- Startup helpers -----------------
def find_free_port(preferred=5051):
    """Try the preferred port; if taken, ask OS for a free one."""
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", preferred))
            return preferred
    except OSError:
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "0")) or find_free_port(5051)
    print(f"Starting Mafia server on http://localhost:{port}  (join page)")
    print(f"Host dashboard: http://localhost:{port}/host")
    app.run(host="0.0.0.0", port=port, debug=True)
