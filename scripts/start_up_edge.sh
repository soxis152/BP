#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 && -z "${FOUR_MQTT_HOST:-}" ]]; then
    echo "Usage: $0 <central_mqtt_host>"
    echo "Or set FOUR_MQTT_HOST in the environment."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export FOUR_NODE_ROLE="${FOUR_NODE_ROLE:-edge}"
export FOUR_ENABLED_SENSORS="${FOUR_ENABLED_SENSORS:-radar_2,ble_2}"
export FOUR_INGEST_ENABLE_DB="${FOUR_INGEST_ENABLE_DB:-0}"
export FOUR_MQTT_HOST="${FOUR_MQTT_HOST:-$1}"
export FOUR_API_HOST="${FOUR_API_HOST:-127.0.0.1}"
export FOUR_API_PORT="${FOUR_API_PORT:-8000}"

cd "${PROJECT_DIR}"
python main.py
