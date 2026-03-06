#!/usr/bin/env bash
# ================================================================
#  generate_mqtt_passwd.sh
#  Run this ONCE before `docker compose up` to create the
#  Mosquitto password file with hashed credentials.
#
#  Requires: docker (uses the mosquitto image to run mosquitto_passwd)
# ================================================================

set -euo pipefail

PASSWD_FILE="mosquitto/config/passwd"
mkdir -p mosquitto/config

echo "Generating Mosquitto password file at ${PASSWD_FILE} …"

# Create empty file (mosquitto_passwd needs it to exist for -b flag)
touch "${PASSWD_FILE}"

# Add users using docker to avoid requiring mosquitto_passwd locally
docker run --rm \
  -v "$(pwd)/mosquitto/config:/mosquitto/config" \
  eclipse-mosquitto:2.0.18 \
  sh -c "
    mosquitto_passwd -b /mosquitto/config/passwd iot_user        iot_password      &&
    mosquitto_passwd -b /mosquitto/config/passwd backend_service backend_password  &&
    mosquitto_passwd -b /mosquitto/config/passwd dashboard_user  dashboard_password
  "

echo "Done. Credentials:"
echo "  iot_user        / iot_password       (ESP8266 gateway)"
echo "  backend_service / backend_password   (Python backend)"
echo "  dashboard_user  / dashboard_password (read-only)"
echo ""
echo "IMPORTANT: Change these passwords before deploying to production!"
