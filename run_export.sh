#!/bin/zsh
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
LOG_FILE="${SCRIPT_DIR}/export.log"

echo "=== [$(date '+%Y-%m-%d %H:%M:%S %Z')] Starting Garmin body composition export ===" >> "${LOG_FILE}"

# If triggered immediately upon waking from sleep, wait up to 30s for Wi-Fi/DNS
ONLINE=0
for i in {1..6}; do
    if /usr/bin/curl -sI --max-time 5 "https://connect.garmin.com" >/dev/null 2>&1; then
        ONLINE=1
        break
    fi
    sleep 5
done

if [ ${ONLINE} -eq 0 ]; then
    echo "Warning: Network unreachable after 30s; attempting export anyway..." >> "${LOG_FILE}"
fi

EXIT_CODE=0
"${PYTHON_BIN}" "${SCRIPT_DIR}/export_body_composition.py" --skip-local --no-clipboard --notify >> "${LOG_FILE}" 2>&1 || EXIT_CODE=$?

echo "=== [$(date '+%Y-%m-%d %H:%M:%S %Z')] Finished (exit=${EXIT_CODE}) ===" >> "${LOG_FILE}"
echo "" >> "${LOG_FILE}"
exit ${EXIT_CODE}
