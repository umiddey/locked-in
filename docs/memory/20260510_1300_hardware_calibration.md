# 20260510_1300_hardware_calibration
**Task**: Hardware Auto-Calibration for IRQ thresholds
**Status**: PENDING
## WHAT
- Implement measurement logic for background noise vs active usage. ❌
- Add calibration UI to Web Dashboard and CLI. ❌
- Save custom thresholds to `config.toml`. ❌
## HOW
- record `/proc/interrupts` deltas during idle and active phases.
- Calculate `Soft` and `Hard` thresholds automatically based on hardware performance.
## WHY
- Hardcoded thresholds are brittle and vary between different keyboards and mice.
- Provides a "plug and play" experience for new users and different machines.
## FILES MODIFIED
- `docs/plans/improvements/20260510_hardware_calibration.md` (Plan)
## NEXT SESSION
- Implement `IdleDetector.start_calibration()` backend logic.
## REFERENCES
- Critique on "Brittle Thresholds" (May 10, 2026).
