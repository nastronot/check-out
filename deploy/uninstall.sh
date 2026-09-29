#!/usr/bin/env bash
#
# uninstall.sh — remove the check-out systemd USER services.
#
set -euo pipefail

UNIT_DST="${HOME}/.config/systemd/user"
SERVICES=(checkout-daemon checkout-audioviz checkout-web checkout-bumpbar)

echo "Removing check-out user services from ${UNIT_DST}"

if command -v systemctl >/dev/null 2>&1; then
	# disable --now stops + removes the enable symlinks. One unit per call: a unit
	# that was never installed (checkout-bumpbar on a machine with no bar) makes
	# systemctl refuse the whole list.
	for svc in "${SERVICES[@]}"; do
		systemctl --user disable --now "${svc}" 2>/dev/null || true
	done
fi

for svc in "${SERVICES[@]}"; do
	dst="${UNIT_DST}/${svc}.service"
	if [ -f "${dst}" ]; then
		rm -f "${dst}"
		echo "removed ${dst}"
	fi
done

if command -v systemctl >/dev/null 2>&1; then
	systemctl --user daemon-reload
fi

echo "Done. check-out user services removed."
