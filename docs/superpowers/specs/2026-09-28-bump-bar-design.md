# Bump bar control — design

**Date:** 2026-09-28 · **Target version:** v1.9.0 · **Status:** draft for review

## Intent

Matt has a **TG3 KBA-M4220A** 10-key bump bar (a kitchen "bump" keypad) plugged
into dad. He wants its ten buttons to drive check-out and a few desktop
controls, and a **separate page** in the check-out UI that shows the key map
and lets him remap each button from a fixed list of actions.

**Success:**
1. A press drives check-out or the desktop within a blink, and **never types a
   letter** into the focused window.
2. Holding the grey key turns the other nine into a second set of controls.
3. A new page, `#/bumpbar`, draws the pad with its current map. Picking a new
   action there takes effect on the next press, with no restart.
4. Unplugging and re-plugging the bar, or restarting any check-out service,
   needs no manual step.

**Decided (with Matt, 2026-09-28):** the default map and the grey-key layer
below. The remap page is its own screen, not a panel on the main board, and it
is written in check-out's existing visual language.

## Bench facts (dad, 2026-09-28)

| | |
|---|---|
| USB ID | `0f39:0101` — `TG3 Electronics M4220`; the HID chip reports "Heng Yu Technology" |
| Keyboard node | `/dev/input/by-id/usb-Heng_Yu_Technology_M4220-event-kbd` (`root:input 0660`) |
| Second node | `…-event-if01`, named "M4220 System Control"; advertises `KEY_POWER`, `KEY_SLEEP`, `KEY_WAKEUP` |
| Keys (Matt's reading) | column 1 top→bottom `a b c d e`, column 2 `f g h i j`. **To confirm by capture.** |
| LED | green idle, red while a key is down |
| Bottom switch | **unknown**; left toward the RJ45 port, the position that works |

The TG3 programming sheet (below) documents a **manager mode**: hold the keys
with *internal* numbers 2 and 9 for ~4 s and the LED turns amber; the next key
then changes firmware options (key table, buzzer, baud rate). It does not
describe the bottom switch. Source: "TG3 Bump Bar Programming Instructions"
(posmarket PDF, 2026-09-28).

## Architecture

A fourth user service, **`checkout-bumpbar`**, reads the bar and acts. It never
touches `state.json` or `status.json` directly: check-out actions go through the
web API, like the UI's own buttons. That keeps check-out's rule of **one writer
per file**.

```
bump bar ──evdev (grabbed)──> checkout-bumpbar ──HTTP──> web /api/* ──> state.json ──> daemon
                                    │   │
                                    │   └──> system actions (wpctl, playerctl, grim, hyprlock…)
bumpbar.json (web WRITES) ──────────┘   reads the map, mtime-gated
bumpbar-status.json <── bumpbar WRITES; web reads it for the page
```

Same ownership pattern as the daemon: the web writes the **map**, the service
writes its **status**. Neither file has two writers.

### Units

- **`checkout/bumpbar_actions.py`** — the action catalogue: id, label, group
  (`checkout` | `system`), one-line hint, `repeat` flag, and how to run it.
  The **only** list of actions; the UI reads it from the API.
- **`checkout/bumpbar_map.py`** — button ids, the default map, load/validate/save
  of `bumpbar.json`, the key-code → button table. Pure, no I/O besides the file.
- **`checkout/bumpbar.py`** — the service: find the device, grab both nodes, read
  events, apply the layer, run actions, write `bumpbar-status.json`, reconnect.
- **`web/app.py`** — three routes (below).
- **UI** — `BumpBarPage.svelte` plus small pieces; a hash route in `App.svelte`.

### Buttons

Ten ids named after their legends, in grid order:

| col 1 | col 2 |
|---|---|
| `decrease` (a) | `increase` (f) |
| `previous` (b) | `next` (g) |
| `print` (c) | `shift` (h, grey) |
| `rotate` (d) | `toggle` (i) |
| `recall` (e) | `serve` (j) |

`shift` is fixed as the layer key and cannot be remapped (v1). Its tap alone
does nothing.

### Default map

| Button | Tap | With SHIFT held |
|---|---|---|
| DECREASE | brightness down | volume down |
| INCREASE | brightness up | volume up |
| PREVIOUS | previous mode | previous track |
| NEXT | next mode | next track |
| PRINT | screenshot → clipboard | — |
| ROTATE PAGES | next saved message | switch audio output |
| TOGGLE SCREENS | blank / unblank | mic mute |
| RECALL | replay latest news alert | lock screen |
| SERVE | open last headline | play / pause |

### Action catalogue (v1)

**check-out** (all through the local web API):

| id | does |
|---|---|
| `brightness_down` / `brightness_up` | step `brightness` 0–3, stops at the ends |
| `mode_prev` / `mode_next` | cycle `clock → message → spectrum → dynamic` (the UI's visible modes) |
| `blank_toggle` | flip `blank` |
| `message_next` | recall the next library message, wrapping |
| `show_news` | `POST /api/command {action: show_news}` |
| `open_headline` | `xdg-open` the `news_shown.link` from `/api/status` (http(s) only, already enforced) |
| `none` | nothing |

**system** (fixed commands, matching dad's existing Hyprland binds):

| id | command |
|---|---|
| `volume_down` / `volume_up` | `wpctl set-volume [-l 1] @DEFAULT_AUDIO_SINK@ 5%-/+` (repeats while held) |
| `mic_mute` | `wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle` |
| `media_prev` / `media_next` / `media_play_pause` | `playerctl previous/next/play-pause` |
| `screenshot` | `grim -o <focused monitor>` piped to `wl-copy`, then `notify-send` |
| `lock` | `hyprlock` |
| `audio_output_next` | set the next `Audio/Sink` (from `wpctl status`) as default, `notify-send` its name |

**The page can only pick from this list.** It can never store a free-form
command: the web UI is reachable by any local process, and a stored shell line
would let anything that can reach port 8000 run programs as Matt.

Only `volume_*` and `brightness_*` act on auto-repeat (key held); every other
action fires once per press.

## Service behaviour

- **Device:** opens both `by-id` nodes and **grabs** each (`EVIOCGRAB`: exclusive
  ownership, so no event reaches Hyprland). Uses `python-evdev`.
- **Missing device:** status `disconnected`; retries every 2 s. A read error
  (unplug) closes, marks disconnected and returns to retrying.
- **Map reload:** `os.stat` on `bumpbar.json` before each press is handled;
  re-parse only when the mtime changed. A bad file keeps the last good map and
  sets `status.error`.
- **Layer:** `shift` down → next presses use the SHIFT column; release → back.
- **API down:** a check-out action logs, sets `status.error`, and drops the press
  (no queue — a stale brightness step later is worse than none).
- **System action failure:** logged, `status.error`, never crashes the loop.
  Commands run with a 5 s timeout and no shell.
- **System Control node:** grabbed and ignored, so a firmware Power/Sleep code
  cannot reach logind.
- **Manager-mode combo:** a normal press of those keys fires their actions once.
  That is accepted: holding two keys for 4 s is not an accident.
- **Status file** (`bumpbar-status.json`, throttled to changes + a 2 s heartbeat):
  `connected`, `device`, `layer`, `last_press {button, action, at}`, `error`,
  `updated_at`.

## Web API

| route | does |
|---|---|
| `GET /api/bumpbar` | `{map, defaults, actions, buttons, status, alive}`; `alive` = status younger than 5 s |
| `PUT /api/bumpbar/map` | validate against catalogue + button ids, atomic write, return the map |
| `POST /api/bumpbar/map/reset` | write the default map |

Validation rejects unknown action ids and remapping `shift` (400).

## UI — the Bump Bar page

- **Routing:** hash routes, no router dependency. `#/` is the board as today;
  `#/bumpbar` is the new page. The masthead gains a two-item nav
  (`board · bump bar`) on both pages. Nothing is added to the board itself.
- **Layout** (same shell, masthead, panel and `.seg` / `.ctl-row` patterns):

```
┌ check-out ─────────────────────── board · [bump bar] ┐
│ ┌ PAD ───────────────────────┐ ┌ ● KEY ────────────┐ │
│ │ [DECREASE ][INCREASE  ]    │ │ INCREASE          │ │
│ │  bright −    bright +      │ │ Tap    [bright + ▾]│ │
│ │  vol −       vol +         │ │ Shift  [vol +    ▾]│ │
│ │ [PREVIOUS ][NEXT      ]    │ │ hint: one line    │ │
│ │ [PRINT    ][ SHIFT    ]    │ └───────────────────┘ │
│ │ [ROTATE   ][TOGGLE    ]    │ ┌ ● DEVICE ─ [reset]┐ │
│ │ [RECALL   ][SERVE     ]    │ │ connected · grabbed│ │
│ │  LED ●                     │ │ last: NEXT → mode+ │ │
│ └────────────────────────────┘ └───────────────────┘ │
└───────────────────────────────────────────────────────┘
```

- **Pad:** a drawing of the real bar: brushed-steel plate, keys in their real
  colours (red, green, light grey, blue, dark grey), legends in the key face,
  the tap action and the SHIFT action in small phosphor text under each legend.
  Click a key to select it. The key from `last_press` flashes for ~400 ms and
  the drawn LED goes red, so a press on the real bar shows on screen.
- **Key panel:** the selected key; two selects (Tap, With SHIFT) grouped
  `check-out` / `system`, each option showing the catalogue label; the hint
  line under them. A change saves immediately.
- **Device panel:** connected / disconnected, service alive, the last press,
  any error, and **Reset to defaults**.
- Polls `/api/bumpbar` at the board's 500 ms rate, only while the page is open.

## Deploy

- `deploy/systemd/checkout-bumpbar.service` (same template shape, no ordering to
  the other units) and `install.sh` / `uninstall.sh` include it.
- **The chezmoi source gets the unit too** (repo rule), enabled on dad only:
  work has no bump bar.
- **Access:** `deploy/udev/70-checkout-bumpbar.rules` matches `0f39:0101` and
  tags both nodes `uaccess`, which gives the logged-in user access to *that*
  device only. One `sudo` copy into `/etc/udev/rules.d/`. Not the `input`
  group: that would let any of Matt's programs read every keyboard.
- `python-evdev` joins `requirements.txt`.
- Env overrides: `CHECKOUT_BUMPBAR_PATH` (the map), `CHECKOUT_BUMPBAR_STATUS_PATH`,
  `CHECKOUT_BUMPBAR_DEVICE` (the kbd node), `CHECKOUT_API` (default
  `http://127.0.0.1:8000`).

## Testing

- **Python:** map load/validate/defaults/migration of a bad file; key-code →
  button table; layer logic on a fake event stream; each check-out action
  against a fake API client (brightness clamps, mode wraps, message wraps);
  system actions build the right argv (no execution); reconnect on a vanishing
  device; web routes (400 on bad action, `shift` locked, reset).
- **UI (vitest):** hash route choice; option grouping; last-press flash timing.
- `tests/test_deploy.py` covers the new unit and the udev rule file.
- **Bench on dad:** capture real key codes, confirm the grab stops typing, walk
  every default action, unplug/replug, and flip the bottom switch while watching
  `/proc/bus/input/devices` to learn what it does.

## Docs

- `CLAUDE.md`: a short "Bump bar (v1.9.0)" section + the new files and env vars.
- `docs/hardware.md`: the bar's bench facts, key codes, switch.
- **mathom:** a device note on the M4220 (IDs, two interfaces, manager mode,
  switch), and a runbook "USB keypad as a macro pad on dad" (udev `uaccess`
  rule + grab, why not `input` group, why not Hyprland binds), linked from
  `conventions/before-you-build.md`. Written after the bench, not before.

## Out of scope (v1)

Remapping `shift`; hold/long-press actions; free-form commands; a bump bar on
work; the bar's buzzer or firmware settings.
