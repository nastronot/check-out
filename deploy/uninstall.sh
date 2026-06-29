#!/usr/bin/env bash
#
# uninstall.sh — remove the check-out systemd USER services.
#
set -euo pipefail

UNIT_DST="${HOME}/.config/systemd/user"
SERVICES=(checkout-daemon checkout-audioviz checkout-web)

echo "Removing check-out user services from ${UNIT_DST}"

if command -v systemctl >/dev/null 2>&1; then
	# disable --now stops + removes the enable symlinks; tolerate already-gone units.
	systemctl --user disable --now "${SERVICES[@]}" 2>/dev/null || true
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
