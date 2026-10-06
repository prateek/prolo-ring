# Agent notes

- Run `make check` (ruff format and lint, pyright, pytest) before handing off. Tests use `tests/fake_ring.py`; no hardware is needed.
- `docs/protocol.md` is the single source for byte layouts. Change it in the same commit as any encoder or decoder change, and mark facts confirmed on a real ring as **[verified]**.
- The opcode allowlist in `src/prolo_ring/protocol.py` is a safety boundary. Add an opcode only with a protocol.md entry, a fake-ring case, and a test; never add profile flash, license, factory, restore, or OTA opcodes (see `docs/flashing.md`).
- Keep `skills/prolo-ring/SKILL.md` in step with the command surface.
