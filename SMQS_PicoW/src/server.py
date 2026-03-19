"""
=============================================================
 SOIL MICROBIAL ACTIVITY MONITOR — Flask Backend Server
=============================================================
 Run:  pip install flask
       python server.py

 Endpoints:
   POST /data        ← Pico W sends sensor JSON here
   GET  /api         ← Returns latest sensor JSON
   GET  /            ← Serves the HTML dashboard
=============================================================
"""

from flask import Flask, request, jsonify, render_template_string
import time
import os

app = Flask(__name__)

# ─────────────────────────────────────────────
#  IN-MEMORY STORAGE  (last reading)
# ─────────────────────────────────────────────
latest_data = {
    "moisture"   : "--",
    "soil_temp"  : "--",
    "humidity"   : "--",
    "ph"         : "--",
    "gas_ppm"    : "--",
    "gas_rate"   : "--",
    "activity"   : "WAITING",
    "last_update": "No data yet"
}


# ─────────────────────────────────────────────
#  LOAD HTML FROM FILE (dashboard.html)
# ─────────────────────────────────────────────
def load_dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return f.read()
    return "<h1>dashboard.html not found. Place it next to server.py</h1>"


# ═════════════════════════════════════════════
#  ROUTES
# ═════════════════════════════════════════════

@app.route("/data", methods=["POST"])
def receive_data():
    """
    Pico W sends a JSON POST here every ~12 seconds.
    Example body:
    {
      "moisture": 55.3,
      "soil_temp": 22.1,
      "humidity": 68.0,
      "ph": 6.8,
      "gas_ppm": 850,
      "gas_rate": 0.34,
      "activity": "HIGH"
    }
    """
    global latest_data

    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json()

    # Validate that expected keys exist
    required_keys = ["moisture", "soil_temp", "humidity", "ph", "activity"]
    for key in required_keys:
        if key not in data:
            return jsonify({"error": f"Missing key: {key}"}), 400

    # Store received data and timestamp
    latest_data = {
        "moisture"   : data.get("moisture",  "--"),
        "soil_temp"  : data.get("soil_temp", "--"),
        "humidity"   : data.get("humidity",  "--"),
        "ph"         : data.get("ph",        "--"),
        "gas_ppm"    : data.get("gas_ppm",   "--"),
        "gas_rate"   : data.get("gas_rate",  "--"),
        "activity"   : data.get("activity",  "UNKNOWN"),
        "last_update": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    }

    print(f"[{latest_data['last_update']}] Received: {latest_data}")
    return jsonify({"status": "ok"}), 200


@app.route("/api", methods=["GET"])
def api_data():
    """Returns the latest sensor readings as JSON."""
    return jsonify(latest_data)


@app.route("/", methods=["GET"])
def dashboard():
    """Serves the HTML dashboard page."""
    html = load_dashboard()
    return html, 200, {"Content-Type": "text/html"}


# ─────────────────────────────────────────────
#  START SERVER
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print(" Soil Monitor Server — Starting on port 5000")
    print(" Open http://localhost:5000 in your browser")
    print("=" * 50)
    # host="0.0.0.0" makes it reachable from Pico W on same network
    app.run(host="0.0.0.0", port=5000, debug=False)
