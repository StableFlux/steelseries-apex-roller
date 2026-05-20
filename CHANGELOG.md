# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-05-20

### Added
- Tray menu **Check for Updates** — opens the Releases page in your default
  browser so you can see whether a newer build is available.
- GitHub Actions workflow that builds `apex-roller.exe` and attaches the
  release zip whenever a `v*` tag is pushed.
- `CHANGELOG.md`, `SECURITY.md`, issue templates, and discoverability
  metadata (topics, description, badges).

## [0.1.0] - 2026-05-20

### Added
- Initial release.
- `WH_KEYBOARD_LL` low-level keyboard hook that intercepts the volume roller
  and media-play key events the SteelSeries software synthesizes from the
  Apex Pro Gen 3, before they reach Windows. Hardware media keys on any
  other keyboard you plug in are unaffected.
- Sonar REST client: reads/writes per-channel volume in both Classic and
  Streamer modes, treating the monitoring and streaming sliders as
  independent in Streamer mode.
- GameSense client driving the keyboard's OLED with the active channel
  label and a level bar.
- Live Sonar GG UI sync via `wss://127.0.0.1:6327/eventing` — sliders in
  the GG window move in real time as the roller turns.
- System tray UI: Pause, Include Master channel, Include Streaming sliders,
  Run at Startup, Open Logs, About, Quit.
- Persistent user config at `%LocalAppData%\ApexRoller\config.json`.
- Rotating file logs at `%LocalAppData%\ApexRoller\logs\apex-roller.log`.
- Single-file PyInstaller `.exe` (~14 MB), no Python required by end users.

### Known limitations
- Live UI sync isn't wired for Classic mode. Audio + OLED still work, but
  the GG sliders only redraw next time you click into the panel.
- No code signing yet — first run may show a Windows SmartScreen warning.

[Unreleased]: https://github.com/StableFlux/steelseries-apex-roller/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/StableFlux/steelseries-apex-roller/releases/tag/v0.1.1
[0.1.0]: https://github.com/StableFlux/steelseries-apex-roller/releases/tag/v0.1.0
