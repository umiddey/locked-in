# 20260512_1345_configurable_irq_exclusion
**Task**: Make IRQ exclusions configurable to handle noisy hardware (e.g., USB sticks)
**Status**: COMPLETE
## WHAT
- Made IRQ exclusion configurable via `config.toml` and Web UI ✓
- Removed hardcoded IRQ 12 exclusion to support standard mice ✓
- Added IRQ 49 to exclusion list to fix idle detection during USB transfers ✓
- Updated Calibration UI to show individual IRQs and suggest exclusions ✓
## HOW
- Modified `src/locked_in/idle_detector.py` to accept `exclude_irqs` in `__init__`.
- Updated `src/locked_in/config.py` with `exclude_irqs` field in `AutoPauseConfig`.
- Wired `exclude_irqs` from config into `Daemon` and `WebFrontend`.
- Added "Exclude IRQs" text field to `settings.html`.
- Refactored `calibrate.html` to display per-IRQ noise/signal and allow toggling "Ignore" state.
## WHY
- Real-world testing revealed that a USB stick (IRQ 49) was drowning out the idle signal with high interrupt deltas.
- Previous hardcoded exclusion of IRQ 12 was preventing actual mice/touchpads from resetting the idle timer.
- Making this configurable allows the app to be hardware-aware and user-friendly for future "product" releases (including Windows/Cross-platform).
## FILES MODIFIED
- src/locked_in/idle_detector.py
- src/locked_in/config.py
- src/locked_in/daemon.py
- src/locked_in/web_frontend.py
- src/locked_in/templates/settings.html
- src/locked_in/templates/components/calibrate.html
- config.toml
## NEXT SESSION
- Monitor if other IRQs need exclusion on different hardware.
## REFERENCES
- User reported idle detection failure during USB file transfer.
