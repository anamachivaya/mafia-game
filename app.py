# app.py
from flask import Flask, request, jsonify, redirect, url_for, render_template, make_response
from threading import Lock
import os
import socket

app = Flask(__name__)

# In-memory store (resets when the server restarts)
attendees = []
lock = Lock()

# ----------------- Routes -----------------
@app.route("/", methods=["GET"])
def home():
    error = request.args.get("error", "")
    return render_template("join.html", error=error)

@app.route("/join", methods=["POST"])
def join():
    name = (request.form.get("name") or "").strip()
    if not name:
        return redirect(url_for("home", error="Please enter a name."))

    # Normalize whitespace and limit length
    name = " ".join(name.split())[:50]

    # Log joins to the console for debugging
    print(f"[JOIN] Received name: {name}", flush=True)

    with lock:
        # Avoid duplicates (case-insensitive)
        if name.lower() not in (n.lower() for n in attendees):
            attendees.append(name)

    return render_template("thanks.html", name=name)

@app.route("/host", methods=["GET"])
def host():
    return make_response(render_template("host.html"))

@app.route("/api/names", methods=["GET"])
def api_names():
    with lock:
        data = {"count": len(attendees), "names": list(attendees)}
    return jsonify(data)

@app.route("/healthz")
def health():
    return "ok", 200

# ----------------- Startup helpers -----------------
def find_free_port(preferred=5050):
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
    port = int(os.environ.get("PORT", "0")) or find_free_port(5050)
    print(f"Starting server on http://localhost:{port}  (join page)")
    print(f"Host dashboard: http://localhost:{port}/host")
    app.run(host="0.0.0.0", port=port, debug=True)