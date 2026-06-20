"""check-out web control surface (FastAPI).

This package NEVER opens the serial port. It only reads/writes the JSON files the
daemon already uses (``state.json`` / ``status.json``) and serves the built
Svelte UI. The daemon remains the sole owner of ``/dev/ttyUSB0``.
"""
