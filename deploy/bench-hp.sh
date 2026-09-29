#!/usr/bin/env bash
#
# bench-hp.sh — run a TEMPORARY HP LD220 instance next to the installed one.
#
# Daemon + audioviz + web UI on port 8001, with their own state files under
# bench-hp/. Never touches the installed units. Ctrl-C stops all three.
#   deploy/bench-hp.sh [/dev/serial/by-id/<HP port>]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PY="${REPO_ROOT}/.venv/bin/python"

port="${1:-}"
if [ -z "${port}" ]; then
	# The HP's USB vendor ID is 03f0.
	for dev in /dev/serial/by-id/*; do
		[ -e "${dev}" ] || continue
		if udevadm info -q property -n "${dev}" | grep -qx 'ID_VENDOR_ID=03f0'; then
			port="${dev}"
			break
		fi
	done
fi
if [ -z "${port}" ]; then
	echo "ERROR: no HP display (USB vendor 03f0) under /dev/serial/by-id; pass its path." >&2
	exit 1
fi

# An installed daemon on the default /dev/ttyUSB0 could open the HP after the
# ttyUSB numbers swap. Require it to be pinned to a by-id path first.
if systemctl --user is-active --quiet checkout-daemon 2>/dev/null &&
	! grep -q '^CHECKOUT_PORT=/dev/serial/by-id/' "${HOME}/.config/checkout/env" 2>/dev/null; then
	echo "ERROR: the installed checkout-daemon is not pinned to a /dev/serial/by-id port." >&2
	echo "       Pin it first: deploy/install.sh --display ibm --port /dev/serial/by-id/<its adapter>" >&2
	exit 1
fi

BENCH="${REPO_ROOT}/bench-hp"
mkdir -p "${BENCH}"
export CHECKOUT_DISPLAY=hp
export CHECKOUT_PORT="${port}"
export CHECKOUT_STATE_PATH="${BENCH}/state.json"
export CHECKOUT_STATUS_PATH="${BENCH}/status.json"
export CHECKOUT_LIBRARY_PATH="${BENCH}/library.json"
export CHECKOUT_DEVICES_PATH="${BENCH}/devices.json"
# Its own bump bar files: the :8001 UI must not show (or remap) the IBM's bar.
export CHECKOUT_BUMPBAR_PATH="${BENCH}/bumpbar.json"
export CHECKOUT_BUMPBAR_STATUS_PATH="${BENCH}/bumpbar-status.json"
export CHECKOUT_SPECTRUM_SOCK="${XDG_RUNTIME_DIR:-/tmp}/checkout-spectrum-hp.sock"

cd "${REPO_ROOT}"
pids=()
cleanup() {
	kill "${pids[@]}" 2>/dev/null || true
	wait || true
}
trap cleanup EXIT INT TERM

"${PY}" -m checkout.daemon &
pids+=($!)
"${PY}" -m checkout.audioviz &
pids+=($!)
"${PY}" -m uvicorn web.app:app --host 127.0.0.1 --port 8001 --no-access-log &
pids+=($!)

echo "HP bench instance on ${port}: http://127.0.0.1:8001  (Ctrl-C stops it)"
wait
