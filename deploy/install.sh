#!/usr/bin/env bash
#
# install.sh — install check-out as systemd USER services.
#
# Installs checkout-daemon, checkout-audioviz, and checkout-web as ~/.config
# user units that start on login, plus checkout-bumpbar with --bumpbar (only a
# machine with a TG3 bump bar; once installed, later runs keep it). USER (not system) services so they inherit
# the logged-in user's PipeWire session — required for spectrum monitor capture.
# We deliberately do NOT enable lingering (see the note at the end).
#
set -euo pipefail

# --- arguments ---------------------------------------------------------------
DISPLAY_KIND=""
DISPLAY_PORT=""
BUMPBAR=0
while [ $# -gt 0 ]; do
	case "$1" in
	--display) DISPLAY_KIND="${2:-}"; shift 2 ;;
	--port) DISPLAY_PORT="${2:-}"; shift 2 ;;
	--bumpbar) BUMPBAR=1; shift ;;
	*) echo "usage: install.sh [--display ibm|hp] [--port /dev/serial/by-id/...] [--bumpbar]" >&2; exit 2 ;;
	esac
done
case "${DISPLAY_KIND}" in
"" | ibm | hp) ;;
*) echo "ERROR: --display must be ibm or hp, got '${DISPLAY_KIND}'" >&2; exit 2 ;;
esac

# --- resolve paths -----------------------------------------------------------
# Repo root = the parent of this script's directory (deploy/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
UNIT_SRC="${SCRIPT_DIR}/systemd"
UNIT_DST="${HOME}/.config/systemd/user"

SERVICES=(checkout-daemon checkout-audioviz checkout-web)
# Bump bar: opt-in (only a machine with a bar). Kept on re-runs once installed.
if [ "${BUMPBAR}" = 1 ] || [ -f "${UNIT_DST}/checkout-bumpbar.service" ]; then
	SERVICES+=(checkout-bumpbar)
fi

echo "check-out service installer"
echo "  repo root : ${REPO_ROOT}"
echo "  units ->  : ${UNIT_DST}"
echo

# --- sanity checks -----------------------------------------------------------
if [ ! -x "${REPO_ROOT}/.venv/bin/python" ]; then
	echo "ERROR: ${REPO_ROOT}/.venv/bin/python not found." >&2
	echo "       Create the virtualenv first, e.g.:" >&2
	echo "         python -m venv .venv && .venv/bin/pip install -r requirements.txt -r web/requirements.txt -r requirements-audio.txt" >&2
	exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
	echo "ERROR: systemctl not found — this installer needs systemd." >&2
	exit 1
fi

# --- build the UI so uvicorn serves a current ui/dist ------------------------
if [ -d "${REPO_ROOT}/ui/dist" ]; then
	echo "ui/dist present — leaving it as is (run 'cd ui && npm run build' to refresh)."
elif command -v npm >/dev/null 2>&1; then
	echo "ui/dist missing — building the UI..."
	( cd "${REPO_ROOT}/ui" && npm install && npm run build )
else
	echo "WARNING: ui/dist is missing and npm is unavailable — the web service will" >&2
	echo "         start but serve no UI until you build it (cd ui && npm run build)." >&2
fi

# --- write the unit files with the repo path substituted ---------------------
mkdir -p "${UNIT_DST}"
for svc in "${SERVICES[@]}"; do
	src="${UNIT_SRC}/${svc}.service"
	dst="${UNIT_DST}/${svc}.service"
	if [ ! -f "${src}" ]; then
		echo "ERROR: missing unit template ${src}" >&2
		exit 1
	fi
	sed "s|__CHECKOUT_REPO__|${REPO_ROOT}|g" "${src}" >"${dst}"
	echo "installed ${dst}"
done

# --- per-machine display choice ----------------------------------------------
ENV_FILE="${HOME}/.config/checkout/env"
if [ -n "${DISPLAY_KIND}" ]; then
	if [ -z "${DISPLAY_PORT}" ]; then
		shopt -s nullglob
		ports=(/dev/serial/by-id/*)
		shopt -u nullglob
		if [ "${#ports[@]}" -ne 1 ]; then
			echo "ERROR: --port not given and ${#ports[@]} serial devices found:" >&2
			printf '  %s\n' "${ports[@]}" >&2
			echo "       re-run with --port <one of the above>" >&2
			exit 1
		fi
		DISPLAY_PORT="${ports[0]}"
	fi
	mkdir -p "$(dirname "${ENV_FILE}")"
	printf 'CHECKOUT_DISPLAY=%s\nCHECKOUT_PORT=%s\n' "${DISPLAY_KIND}" "${DISPLAY_PORT}" >"${ENV_FILE}"
	echo "display: ${DISPLAY_KIND} on ${DISPLAY_PORT} (${ENV_FILE})"
elif [ -f "${ENV_FILE}" ]; then
	echo "display: keeping ${ENV_FILE} (no --display given):"
	sed 's/^/  /' "${ENV_FILE}"
else
	echo "display: defaults (ibm, /dev/ttyUSB0) — no --display given"
fi
SERIAL_PORT="${DISPLAY_PORT:-$(sed -n 's/^CHECKOUT_PORT=//p' "${ENV_FILE}" 2>/dev/null || true)}"
SERIAL_PORT="${SERIAL_PORT:-/dev/ttyUSB0}"

# --- bump bar: its Python dependency BEFORE the unit starts ----------------
# (a started unit without evdev would crash-loop into systemd's start limit)
if [[ " ${SERVICES[*]} " == *" checkout-bumpbar "* ]] &&
	! "${REPO_ROOT}/.venv/bin/python" -c 'import evdev' 2>/dev/null; then
	echo "bump bar: installing evdev into the venv..."
	"${REPO_ROOT}/.venv/bin/pip" install -q -r "${REPO_ROOT}/requirements-bumpbar.txt"
fi

# --- enable + start ----------------------------------------------------------
echo
systemctl --user daemon-reload
systemctl --user enable --now "${SERVICES[@]}"
# enable --now leaves a running unit alone; restart so new code and a new
# --display/--port apply now, not at the next login.
systemctl --user restart "${SERVICES[@]}"

echo
systemctl --user --no-pager status "${SERVICES[@]}" || true

# --- bump bar: the one-time udev rule (needs sudo, so it is printed) ---------
if [[ " ${SERVICES[*]} " == *" checkout-bumpbar "* ]] &&
	[ ! -f /etc/udev/rules.d/70-checkout-bumpbar.rules ]; then
	echo
	echo "bump bar: one sudo step gives you access to the bar (and only the bar):"
	echo "  sudo install -m 644 ${REPO_ROOT}/deploy/udev/70-checkout-bumpbar.rules /etc/udev/rules.d/"
	echo "  sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=input"
fi

# --- serial port: the daemon needs the port's group (uucp on Arch) ----------
# `id -nG USER` reads the group database, so it sees a group added this session.
# The running services don't: they keep the groups of the user manager, which
# started at login — so the ACL line lets the daemon in now, before a re-login.
if [ -e "${SERIAL_PORT}" ]; then
	port_group="$(stat -L -c %G "${SERIAL_PORT}")"
	if ! id -nG "${USER}" | tr ' ' '\n' | grep -qx "${port_group}"; then
		echo
		echo "serial: you are not in '${port_group}', which owns ${SERIAL_PORT}. One sudo step:"
		echo "  sudo usermod -aG ${port_group} ${USER} && sudo setfacl -m u:${USER}:rw $(readlink -f "${SERIAL_PORT}")"
		echo "  (the group applies after a full logout; the ACL lets the daemon in now)"
	fi
fi

cat <<EOF

check-out is installed and running as user services.

  Web UI : http://127.0.0.1:8000
  Logs   : journalctl --user -u checkout-daemon -f
           journalctl --user -u checkout-audioviz -f
           journalctl --user -u checkout-web -f
  Stop   : systemctl --user stop ${SERVICES[*]}
  Status : systemctl --user status checkout-daemon

NOTE: lingering is intentionally NOT enabled. These run as user services that
start when you log in and stop when your session ends — by design. Spectrum
audio capture taps the user's PipeWire monitor, which only exists inside an
active login session; a headless/lingering setup would have no audio session
and break monitor capture. To remove the services, run deploy/uninstall.sh.
EOF
