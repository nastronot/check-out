"""Lightweight checks for the systemd user-service deploy assets.

These are config files, not app code — so the bar is "well-formed and internally
consistent", not behavioral: every unit has the required sections/keys, the repo
placeholder is uniform, and the shell scripts pass `bash -n` (and shellcheck when
it's available).
"""

import configparser
import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(REPO_ROOT, "deploy")
SYSTEMD = os.path.join(DEPLOY, "systemd")

SERVICES = ["checkout-daemon", "checkout-audioviz", "checkout-web", "checkout-bumpbar"]
PLACEHOLDER = "__CHECKOUT_REPO__"
SCRIPTS = ["install.sh", "uninstall.sh", "bench-hp.sh"]


def _unit_path(name):
    return os.path.join(SYSTEMD, f"{name}.service")


@pytest.mark.parametrize("svc", SERVICES)
def test_unit_file_exists(svc):
    assert os.path.isfile(_unit_path(svc)), f"missing unit {svc}.service"


@pytest.mark.parametrize("svc", SERVICES)
def test_unit_is_well_formed_ini(svc):
    # systemd units are INI-like; configparser parses them (allow_no_value for
    # bare keys, though we don't use any here).
    parser = configparser.ConfigParser(strict=True)
    with open(_unit_path(svc), encoding="utf-8") as fh:
        parser.read_file(fh)
    for section in ("Unit", "Service", "Install"):
        assert parser.has_section(section), f"{svc}: missing [{section}]"
    assert parser.get("Service", "ExecStart")
    assert parser.get("Service", "WorkingDirectory") == PLACEHOLDER
    assert parser.get("Service", "Restart") == "on-failure"
    assert parser.get("Install", "WantedBy") == "default.target"


@pytest.mark.parametrize("svc", SERVICES)
def test_execstart_uses_venv_and_placeholder(svc):
    parser = configparser.ConfigParser()
    with open(_unit_path(svc), encoding="utf-8") as fh:
        parser.read_file(fh)
    exec_start = parser.get("Service", "ExecStart")
    assert exec_start.startswith(f"{PLACEHOLDER}/.venv/bin/")
    # The repo path must only ever appear via the placeholder (no leaked
    # personal absolute paths or hostnames committed).
    with open(_unit_path(svc), encoding="utf-8") as fh:
        body = fh.read()
    assert "/home/" not in body


@pytest.mark.parametrize("svc", SERVICES)
def test_no_ordering_between_units(svc):
    # Guard against reintroducing the boot-time ordering cycle (v1.3.1): the three
    # units must carry NO ordering/dependency directive referencing another
    # checkout-* unit or default.target. They self-coordinate at runtime (socket +
    # state.json), so any After=/Before=/Wants=/Requires= among them is both
    # unnecessary and — with the [Install] WantedBy=default.target — cycle-forming.
    forbidden_keys = ("after", "before", "wants", "requires", "requisite", "bindsto")
    forbidden_targets = ("checkout-daemon", "checkout-audioviz", "checkout-web",
                         "checkout-bumpbar", "default.target")
    with open(_unit_path(svc), encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().lower() in forbidden_keys:
                assert not any(t in value for t in forbidden_targets), (
                    f"{svc}: '{line}' reintroduces an ordering cycle "
                    "(units must be order-independent)"
                )


def test_module_invocation_per_service():
    expected = {
        "checkout-daemon": "-m checkout.daemon",
        "checkout-audioviz": "-m checkout.audioviz",
        "checkout-web": "uvicorn web.app:app",
        "checkout-bumpbar": "-m checkout.bumpbar",
    }
    for svc, needle in expected.items():
        with open(_unit_path(svc), encoding="utf-8") as fh:
            assert needle in fh.read(), f"{svc}: expected {needle!r} in ExecStart"


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_exists_and_executable(script):
    path = os.path.join(DEPLOY, script)
    assert os.path.isfile(path), f"missing {script}"
    assert os.access(path, os.X_OK), f"{script} is not executable"


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_bash_syntax(script):
    path = os.path.join(DEPLOY, script)
    result = subprocess.run(
        ["bash", "-n", path], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"{script}: bash -n failed: {result.stderr}"


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_shellcheck_clean(script):
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck not installed")
    path = os.path.join(DEPLOY, script)
    result = subprocess.run(
        ["shellcheck", path], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"{script}: shellcheck: {result.stdout}"


def test_install_substitutes_placeholder():
    # The installer must replace every placeholder occurrence (sed), never leave
    # one behind in the written unit.
    with open(os.path.join(DEPLOY, "install.sh"), encoding="utf-8") as fh:
        body = fh.read()
    assert f"s|{PLACEHOLDER}|" in body, "install.sh must sed the repo placeholder"
    assert "systemctl --user enable --now" in body
    # Lingering must NOT be enabled (start-on-login by design).
    assert "enable-linger" not in body


def test_daemon_unit_reads_optional_env_file():
    with open(_unit_path("checkout-daemon"), encoding="utf-8") as fh:
        assert "EnvironmentFile=-%h/.config/checkout/env" in fh.read()


def test_install_writes_display_env_file():
    with open(os.path.join(DEPLOY, "install.sh"), encoding="utf-8") as fh:
        body = fh.read()
    assert "--display" in body and "--port" in body
    assert ".config/checkout/env" in body
    assert "CHECKOUT_DISPLAY=" in body and "CHECKOUT_PORT=" in body


def test_install_rejects_a_bad_display_before_systemd():
    result = subprocess.run(
        ["bash", os.path.join(DEPLOY, "install.sh"), "--display", "hpp"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "HOME": "/nonexistent-home"},
    )
    assert result.returncode == 2
    assert "ibm" in result.stderr and "hp" in result.stderr


def test_bench_hp_isolates_its_files_and_port():
    with open(os.path.join(DEPLOY, "bench-hp.sh"), encoding="utf-8") as fh:
        body = fh.read()
    assert "CHECKOUT_DISPLAY=hp" in body
    assert "--port 8001" in body
    for key in ("STATE_PATH", "STATUS_PATH", "LIBRARY_PATH", "DEVICES_PATH", "SPECTRUM_SOCK"):
        assert f"CHECKOUT_{key}=" in body
    for verb in ("start", "stop", "restart", "enable", "disable"):
        assert f"systemctl --user {verb}" not in body  # never touches the installed units


def test_install_restarts_running_services():
    # enable --now does not restart a running unit, so a new --display/--port or
    # new code would not apply until the next login.
    with open(os.path.join(DEPLOY, "install.sh"), encoding="utf-8") as fh:
        assert 'systemctl --user restart "${SERVICES[@]}"' in fh.read()


def test_install_checks_the_serial_port_group():
    # work was never added to uucp, so its daemon could not open the HP.
    with open(os.path.join(DEPLOY, "install.sh"), encoding="utf-8") as fh:
        body = fh.read()
    assert "stat -L -c %G" in body
    assert "sudo usermod -aG" in body and "sudo setfacl" in body


def test_bench_hp_refuses_an_unpinned_installed_daemon():
    with open(os.path.join(DEPLOY, "bench-hp.sh"), encoding="utf-8") as fh:
        body = fh.read()
    assert "is-active --quiet checkout-daemon" in body
    assert "CHECKOUT_PORT=/dev/serial/by-id/" in body


# --- bump bar (v1.9.0): opt-in, one device only ---------------------------
UDEV_RULE = os.path.join(DEPLOY, "udev", "70-checkout-bumpbar.rules")


def test_udev_rule_matches_only_the_bar_and_uses_uaccess():
    with open(UDEV_RULE, encoding="utf-8") as fh:
        text = fh.read()
    rules = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    assert len(rules) == 1
    assert 'ATTRS{idVendor}=="0f39"' in rules[0]
    assert 'ATTRS{idProduct}=="0101"' in rules[0]
    assert 'TAG+="uaccess"' in rules[0]
    # A per-device ACL for the seat user, never a group/mode that opens every keyboard.
    assert "MODE" not in rules[0] and "GROUP" not in rules[0]


def test_install_makes_bumpbar_opt_in():
    with open(os.path.join(DEPLOY, "install.sh"), encoding="utf-8") as fh:
        body = fh.read()
    assert "--bumpbar" in body
    # The default set stays the three core units; the bar is added only on request.
    assert "SERVICES=(checkout-daemon checkout-audioviz checkout-web)" in body
    assert "SERVICES+=(checkout-bumpbar)" in body


def test_uninstall_removes_bumpbar():
    with open(os.path.join(DEPLOY, "uninstall.sh"), encoding="utf-8") as fh:
        assert "checkout-bumpbar" in fh.read()


def test_bench_hp_isolates_bumpbar_files():
    with open(os.path.join(DEPLOY, "bench-hp.sh"), encoding="utf-8") as fh:
        body = fh.read()
    assert 'CHECKOUT_BUMPBAR_PATH="${BENCH}/bumpbar.json"' in body
    assert 'CHECKOUT_BUMPBAR_STATUS_PATH="${BENCH}/bumpbar-status.json"' in body
