#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export FOUR_NODE_ROLE="${FOUR_NODE_ROLE:-central}"
export FOUR_ENABLED_SENSORS="${FOUR_ENABLED_SENSORS:-radar_1,ble_1}"
export FOUR_INGEST_ENABLE_DB="${FOUR_INGEST_ENABLE_DB:-1}"
export FOUR_API_HOST="${FOUR_API_HOST:-0.0.0.0}"
export FOUR_API_PORT="${FOUR_API_PORT:-8000}"
export FOUR_MQTT_HOST="${FOUR_MQTT_HOST:-127.0.0.1}"
export FOUR_DB_HOST="${FOUR_DB_HOST:-127.0.0.1}"
export FOUR_DB_PORT="${FOUR_DB_PORT:-5432}"

cd "${PROJECT_DIR}"
python main.py
