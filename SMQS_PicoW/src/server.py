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
from flask import Flask, request, jsonify, render_template
import time

app = Flask(__name__)
latest_data = {}

@app.route("/data", methods=["POST"])
def receive_data():
    global latest_data

    if not request.is_json:
        return jsonify({"error": "JSON required"}), 400

    data = request.get_json()

    # Basic validation
    required = ["moisture", "soil_temp", "humidity", "ph", "gas_ppm", "gas_rate", "activity"]
    for key in required:
        if key not in data:
            return jsonify({"error": f"Missing {key}"}), 400

    data["last_update"] = time.strftime("%H:%M:%S")
    latest_data = data

    print("\n=== DATA RECEIVED ===")
    print(latest_data)

    return jsonify({"status": "ok"})


@app.route("/api")
def api():
    return jsonify(latest_data)


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
