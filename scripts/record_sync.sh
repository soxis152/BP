#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <label> <edge_host>"
    echo "Optional env:"
    echo "  EDGE_RUN_FILE=~/Four/Dronarena/.active_run_id"
    echo "  PYTHON_BIN=/full/path/to/python"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

LABEL="$1"
EDGE_HOST="$2"
EDGE_RUN_FILE="${EDGE_RUN_FILE:-~/Four/Dronarena/.active_run_id}"

resolve_python_bin() {
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        printf '%s\n' "${PYTHON_BIN}"
        return 0
    fi

    local candidate
    for candidate in \
        "${PROJECT_DIR}/../venv/bin/python" \
        "${PROJECT_DIR}/../.venv/bin/python" \
        "${PROJECT_DIR}/.venv/bin/python"
    do
        if [[ -x "${candidate}" ]]; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    done

    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi

    if command -v python >/dev/null 2>&1; then
        command -v python
        return 0
    fi

    echo "Python interpreter not found. Set PYTHON_BIN explicitly." >&2
    exit 1
}

PYTHON_CMD="$(resolve_python_bin)"

LABEL_QUOTED="$(printf '%q' "${LABEL}")"
EDGE_RUN_FILE_QUOTED="$(printf '%q' "${EDGE_RUN_FILE}")"

echo "Synchronizing edge run_id '${LABEL}' on ${EDGE_HOST}"

ssh "${EDGE_HOST}" "LABEL=${LABEL_QUOTED} EDGE_RUN_FILE=${EDGE_RUN_FILE_QUOTED} python3 - <<'PY'
from pathlib import Path
import os

path = Path(os.environ['EDGE_RUN_FILE']).expanduser()
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(os.environ['LABEL'] + '\n', encoding='utf-8')
print(f'Edge run_id synchronized to {path}')
PY"

cd "${PROJECT_DIR}"
exec "${PYTHON_CMD}" -m experiment_tools.record_experiment --label "${LABEL}"
