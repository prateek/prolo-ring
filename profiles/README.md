# Profiles

`factory-default.json` is Prolo Studio 1.0.7's read-only Factory Default profile, exported with **Profile Library → Export**. Import a copy into Studio to start a custom profile; Studio flashes it to the ring.

Studio key sequences name modifiers the way the ring sends them: `Ctrl` is HID Left Control and `Meta` (alias `Win`, `Cmd`) is HID Left GUI. On macOS that makes the factory two-finger tap (`Meta+D`) Cmd+D, and the pinch zooms (`Ctrl+=`, `Ctrl+-`) Control-based, so they don't zoom. A macOS profile should use `Meta+=` and `Meta+-` for zoom.

`_profileSettings` holds the mode and gesture-group toggles. Studio writes them to the ring's flag groups right before flashing; `prolo-ring profile read` reports the live values under `profile_settings`.
