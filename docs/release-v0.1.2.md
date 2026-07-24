# icon-themer v0.1.2

Packaged-state bugfix release.

## Download

- Download `IconThemer-v0.1.2-windows-x64.zip`
- Extract the zip
- Run `IconThemer.exe`

## Changes

- Store state, settings, generated icons, and caches in `%LOCALAPPDATA%\IconThemer` so source and packaged runs share the same desktop state.
- Migrate legacy state, cache, and archive data from the source or executable directory on first run.
- Fix blank cards for name-hidden shortcuts in packaged builds by preserving their original-name mapping and original-icon cache.
- Keep PyInstaller work files in `build\release` so release builds do not remove unrelated or in-use build directories.

## Notes

- Windows 10 / 11 only.
- The app requests administrator permission because it edits desktop shortcuts, folder icons, icon cache state, and the shortcut-arrow overlay.
- Restore is supported from inside the app: icons, names, and shortcut arrows can be restored.
- Image generation still requires your own OpenAI-compatible image API settings.

## SHA256

`2E478B2E24F1EC60E24F2E8E91D74F31790404391B6466C3558DE2D0D1F3E332`
