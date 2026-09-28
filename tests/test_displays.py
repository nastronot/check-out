import pytest

from checkout import config, displays
from checkout.driver import VFDDriver
from checkout.driver_epson import EpsonDriver


def test_registry():
    assert displays.DRIVERS == {"ibm": VFDDriver, "hp": EpsonDriver}


@pytest.mark.parametrize("name", ["hp", "HP", " hp "])
def test_names_are_normalized(name):
    assert displays.driver_class(name) is EpsonDriver


def test_unknown_display_names_valid_values():
    with pytest.raises(ValueError, match="hpp.*hp.*ibm|hpp.*ibm.*hp"):
        displays.driver_class("hpp")


def test_default_comes_from_config(monkeypatch):
    monkeypatch.setattr(config, "DISPLAY", "hp")
    assert isinstance(displays.make_driver(dry_run=True), EpsonDriver)
    monkeypatch.setattr(config, "DISPLAY", "ibm")
    assert isinstance(displays.make_driver(dry_run=True), VFDDriver)


def test_unknown_configured_display_is_named(monkeypatch):
    monkeypatch.setattr(config, "DISPLAY", "nope")
    with pytest.raises(ValueError, match="'nope'"):
        displays.driver_class()
