# Flashing profiles from JSON: possible, deferred

`prolo-ring` can read a ring's gesture profile but cannot write one. Flash profiles with Prolo Studio: **Profile Library → Import** the JSON, then **Flash**. This is a deliberate choice, not a protocol gap.

## What it would take

The write path is fully described in [protocol.md section 7](protocol.md#7-flash-write-path-describe-only-do-not-implement):

1. Push the profile-owned flag groups (modes, gesture groups, Modstrip long hold) with `SET_FLAG_GROUP`, preserving the device-wide bits. `prolo-ring` already does this read-modify-write safely for the edge-scroll bits.
2. Encode the Studio JSON export into the binary profile: a 4-byte header, then one entry per gesture with key, consumer, delay, mouse, and snap steps. This means mapping Studio's key-sequence strings to HID usages, its media names to the firmware consumer bitmask, its mouse labels to press/release step pairs, text input to per-character key steps, and enforcing the 16-step and 200-byte entry limits.
3. Send `FLASH_PROFILE_BEGIN` (size and CRC32), `FLASH_PROFILE_DATA` in 17-byte chunks, then `FLASH_PROFILE_COMMIT`.
4. Wait for the ring to reboot, reconnect, and read the profile back to compare against what was sent.

The decoder in `src/prolo_ring/profile.py` is the inverse of step 2, so an encoder could be tested by round-tripping every profile Studio has flashed.

## Why we deferred it

- **A wrong blob is accepted, not rejected.** The ring's CRC check guards transport corruption only. An encoding bug, such as a wrong modifier bit, a swapped consumer code, or a 4-byte mouse body where the firmware expects 5, flashes a profile that does the wrong thing on every host until it is reflashed.
- **Flashing replaces everything at once and reboots the ring.** There is no partial update and no read-before-write diff in the protocol, and the flag-group writes happen even if the flash later fails.
- **The encoder is Studio's most version-specific code.** Its tables and step costs change with Studio and firmware releases. Studio already ships a tested encoder for the current firmware.
- **It is rare.** A profile changes a few times a year. Importing a JSON file into Studio and clicking Flash costs less than maintaining a second encoder.

Revisit this if Studio stops supporting a platform you need, or if profile changes become frequent enough that the manual Import → Flash step hurts. Gate any implementation behind readback verification against profiles Studio has flashed, and keep it out of the default allowlist until it has been tested on a real ring.
