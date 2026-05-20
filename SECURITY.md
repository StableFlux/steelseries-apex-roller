# Security policy

## Reporting a vulnerability

If you find a security issue (anything that lets a remote attacker
manipulate audio settings, exfiltrate data, or run code without the
user's consent), please **don't** open a public issue.

Instead, use GitHub's
[private vulnerability reporting](https://github.com/StableFlux/steelseries-apex-roller/security/advisories/new)
form. I'll respond within a couple of weeks where possible.

## Scope

This is a hobby utility, distributed as an unsigned single-file PyInstaller
executable, talking only to local services (SteelSeries GG, Sonar,
GameSense — all on `127.0.0.1`). There is no remote network endpoint, no
account system, and no cloud backend.

Reasonable concerns include:
- The app accepting input from a non-local source (it shouldn't).
- Code paths that could escalate privileges (the app runs as the current
  user and never requests elevation).
- The PyInstaller bootloader pulling code from a writable location.

Out of scope:
- The fact that the binary is unsigned and triggers Windows SmartScreen on
  first run. This is a known limitation noted in the README.
- Issues in the SteelSeries software stack itself; please report those to
  SteelSeries.
