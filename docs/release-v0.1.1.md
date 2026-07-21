# icon-themer v0.1.1

Bugfix and performance release.

## Download

- Download `IconThemer-v0.1.1-windows-x64.zip`
- Extract the zip
- Run `IconThemer.exe`

## Changes

- Fix Codex config fallback so image generation reads top-level `openai_base_url` when the active provider is `openai` (stops 401s against api.openai.com when using a relay key).
- Parallelize batch icon generation with up to 5 concurrent workers.
- Make archive index/slot reservation thread-safe for concurrent generation.

## Notes

- Windows 10 / 11 only.
- The app requests administrator permission because it edits desktop shortcuts, folder icons, icon cache state, and the shortcut-arrow overlay.
- Restore is supported from inside the app: icons, names, and shortcut arrows can be restored.
- Image generation still requires your own OpenAI-compatible image API settings.

## SHA256

`AB288CD78A9D4324B2540DAB66A406420EA9912B6A8E052C6B4C4769FD0E840E`
