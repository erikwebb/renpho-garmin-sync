#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve Python binary: env override -> local .venv -> sibling python-garminconnect venv -> system python3
if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
        PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
    elif [ -x "${REPO_ROOT}/../python-garminconnect/.venv/bin/python" ]; then
        PYTHON_BIN="${REPO_ROOT}/../python-garminconnect/.venv/bin/python"
    elif [ -x "${HOME}/Development/python-garminconnect/.venv/bin/python" ]; then
        PYTHON_BIN="${HOME}/Development/python-garminconnect/.venv/bin/python"
    else
        PYTHON_BIN="$(command -v python3)"
    fi
fi

exec "${PYTHON_BIN}" "${REPO_ROOT}/export_body_composition.py" --skip-local "$@"
