# Naming convention: 20260511_1930_manual_threshold_override
**Task**: Add manual threshold input to calibration UI + fix calibrate/apply always failing in web-only mode
**Status**: COMPLETE
## WHAT
- Added "Manual Override" grid with 4 number inputs (soft/hard × keyboard/USB) in calibrate.html ✓
- Added "Apply Manual" button + JS that POSTs to /calibrate/apply ✓
- Fixed /calibrate/apply to always return success after saving; systemctl restart is best-effort ✓
## HOW
- Inputs pre-filled from current config values (same as the read-only display above)
- JS reads all 4 inputs, builds soft/hard dicts, POSTs to /calibrate/apply
- Status text shows "Saving…" → "Saved ✓" or error; reloads after 800ms on success
- Web idle watcher reads config on every 1s tick so new thresholds take effect immediately without restart
## WHY
- Hardware learn calibration is a 60-second process and doesn't always produce useful thresholds
- User may know from experience what values work
- /calibrate/apply was returning "error" always in web-only mode because systemctl restart fails when daemon isn't running — but thresholds were actually saved correctly; fixed to always succeed
## FILES MODIFIED
- `src/locked_in/templates/components/calibrate.html`: added manual override section + JS
- `src/locked_in/web_frontend.py`: fixed /calibrate/apply to not fail when daemon is offline
## NEXT SESSION
- None
## REFERENCES
- Verification: `source .venv/bin/activate && python -c "from src.locked_in.web_frontend import LockedInWebFrontend; print('OK')"`
