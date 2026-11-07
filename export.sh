#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Resolve Python binary: env override -> local .venv -> sibling python-garminconnect venv -> system python3
if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
        PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
    elif [ -x "${SCRIPT_DIR}/../python-garminconnect/.venv/bin/python" ]; then
        PYTHON_BIN="${SCRIPT_DIR}/../python-garminconnect/.venv/bin/python"
    elif [ -x "${HOME}/Development/python-garminconnect/.venv/bin/python" ]; then
        PYTHON_BIN="${HOME}/Development/python-garminconnect/.venv/bin/python"
    else
        PYTHON_BIN="$(command -v python3)"
    fi
fi

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/export_body_composition.py" --skip-local "$@"
