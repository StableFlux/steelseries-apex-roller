# Apex Roller

[![Latest release](https://img.shields.io/github/v/release/StableFlux/steelseries-apex-roller?label=release&color=blue)](https://github.com/StableFlux/steelseries-apex-roller/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/StableFlux/steelseries-apex-roller/total?color=brightgreen)](https://github.com/StableFlux/steelseries-apex-roller/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4)](#requirements)
[![Build](https://github.com/StableFlux/steelseries-apex-roller/actions/workflows/release.yml/badge.svg)](https://github.com/StableFlux/steelseries-apex-roller/actions/workflows/release.yml)

Remap the SteelSeries Apex Pro Gen 3 volume roller and media button to control
SteelSeries Sonar channels instead of Windows master volume — with live UI
sync, OLED feedback, and no driver hacks.

<!--
Screenshot placeholder: add an image at docs/screenshot.png showing the
keyboard OLED + the Sonar GG window with the matching slider, and replace
this comment with:

![Apex Roller in action](docs/screenshot.png)
-->


## What it does

When SteelSeries GG with Sonar is running, the Apex Pro's roller and media
button normally just move the Windows master volume slider. That collides
with Sonar's virtual-audio setup: you wanted per-channel control, you got
master.

This app sits between the keyboard and Windows:

- **Media button** cycles through Sonar's channels. By default
  (Streamer mode): **Game → Chat → Media → Aux**, monitoring sliders only.
  Two tray toggles extend this:
  - *Include Master channel* — adds Master to the cycle.
  - *Include Streaming sliders* — gives every channel two positions
    (monitoring first, then streaming), so you can dial in the broadcast
    feed independently of what you hear locally.
  Both off by default; choices persist across launches.
- **Roller up/down** adjusts the active channel's volume.
- **OLED** on the keyboard shows the active channel and current level.
- **Sonar GG UI sliders move live**, in real time, exactly as if you were
  dragging them with the mouse.
- The original Windows-master behaviour is preserved on any *other*
  keyboard you plug in — we only intercept events the SteelSeries software
  synthesizes from the Apex Pro itself (LLKHF_INJECTED).

Audio engine, OLED, and the Sonar GG visual sliders all stay in sync.

## Requirements

- Windows 10/11
- SteelSeries Apex Pro Gen 3 (or any Apex Pro variant with the OLED + roller)
- [SteelSeries GG](https://steelseries.com/gg) installed, with **Sonar enabled**
- Sonar in **Streamer mode** for full feature coverage (Classic mode currently
  drives audio + OLED but not live-UI redraw — see Known limitations)

## Install

1. Grab `apex-roller.zip` from the
   [Releases](https://github.com/StableFlux/steelseries-apex-roller/releases) page.
2. Extract anywhere (e.g. `Documents\ApexRoller\`).
3. Double-click `apex-roller.exe`. An "AR" icon appears in the system tray.
4. Right-click the tray icon → **Run at Startup** to launch it automatically
   on Windows login.

That's it. No admin, no driver install, no service registration. Logs and
config live in `%LocalAppData%\ApexRoller\`.

## Tray menu

- **Pause** — temporarily passes roller/media events through to Windows
  (master volume + media play/pause behave normally).
- **Include Master channel** — adds Sonar's Master entry to the cycle.
  Off by default.
- **Include Streaming sliders** — each channel becomes two cycle positions
  (monitoring, then streaming). Off by default.
- **Run at Startup** — toggles a shortcut in your per-user Startup folder.
- **Check for Updates** — opens the Releases page so you can grab a newer
  build if there is one.
- **Open Logs Folder** — Explorer to `%LocalAppData%\ApexRoller\logs\`.
- **Quit** — exit; OLED returns to its default content.

Settings are saved to `%LocalAppData%\ApexRoller\config.json`.

## How it works (briefly)

Three local APIs do the heavy lifting:

1. **A `WH_KEYBOARD_LL` hook** intercepts the volume/media VK events that
   SteelSeries GG synthesizes from the Apex Pro roller, before they reach
   Windows. We swallow them so master volume stays put.
2. **The Sonar REST API** at `http://127.0.0.1:50166/volumeSettings/...`
   (discovered via `coreProps.json` → GG `/subApps`) applies the new value
   to the audio engine.
3. **GG core's `/eventing` WebSocket** at `wss://127.0.0.1:6327/eventing`
   gets an `EVENT_SUB_APP_ACTIONS_DATA_CHANGED` event for the matching
   action name (`MONITOR_GAME_VOLUME`, etc.). Sonar's internal action
   handler picks it up and broadcasts `SONAR_EVENT_VOLUME_DATA` over its
   own `/sock` channel, which is what the GG UI listens to — so the
   slider repaints live.

The OLED display uses the SteelSeries
[GameSense SDK](https://github.com/SteelSeries/gamesense-sdk) at
`http://127.0.0.1:50063` with a `screened` device handler.

## Known limitations

- **Classic-mode live UI sync is not wired.** In Classic mode, Sonar's
  internal `VolumeActionProvider` only exposes the mic-mute action as a
  typed action; the other classic-mode volumes don't have an
  `EVENT_SUB_APP_ACTIONS_DATA_CHANGED` action name we can target. Audio
  and OLED still work in Classic mode — only the GG UI sliders won't
  update live. Run Sonar in Streamer mode for the full experience.
- **No auto-update yet.** Check Releases for new versions manually.
- **Sonar API is community-documented, not officially supported by
  SteelSeries.** It could change in a future GG release. The app re-reads
  `coreProps.json` and re-discovers endpoints on each connection error,
  but a major schema change would still break us.

## Build from source

```powershell
git clone https://github.com/StableFlux/steelseries-apex-roller.git
cd steelseries-apex-roller
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Dev run (console mode, shows logs)
python -m apex_roller --no-tray

# Tray run
python -m apex_roller --tray

# Build the redistributable .exe
python build.py
# -> dist\apex-roller.exe
```

The `probes/` directory contains the small validation scripts used while
building each layer — useful for debugging.

## Community

- **Questions / usage help** → [Discussions](https://github.com/StableFlux/steelseries-apex-roller/discussions)
- **Bugs** → [open an issue](https://github.com/StableFlux/steelseries-apex-roller/issues/new/choose)
- **Security reports** → see [SECURITY.md](SECURITY.md)
- **Changes per release** → [CHANGELOG.md](CHANGELOG.md)

## License

[MIT](LICENSE) © StableFlux
