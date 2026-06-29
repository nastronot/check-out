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

SERVICES = ["checkout-daemon", "checkout-audioviz", "checkout-web"]
PLACEHOLDER = "__CHECKOUT_REPO__"
SCRIPTS = ["install.sh", "uninstall.sh"]


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


def test_module_invocation_per_service():
    expected = {
        "checkout-daemon": "-m checkout.daemon",
        "checkout-audioviz": "-m checkout.audioviz",
        "checkout-web": "uvicorn web.app:app",
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
