# Runbook: "The Shit is Perfect" (Professional Release)

This document tracks the high-level transition from a developer prototype to a SOTA (State-of-the-Art) consumer application.

---

## 1. Engine & Architecture (Stability)
- [ ] **Complete Service Decoupling**: Move `Database`, `NotionClient`, and `NotificationSystem` into their own isolated service threads.
- [ ] **Robust Error Recovery**: If the web server or a sub-service crashes, the `Daemon` should detect it and restart the specific thread without losing the active focus timer.
- [ ] **State Persistence**: Ensure the state machine saves its current state to disk on every transition so a power outage doesn't "reset" a focus session.

## 2. UI & Frontend (Maintainability)
- [ ] **100% Jinja2 Migration**: Zero HTML strings in Python.
- [ ] **Component Library**: All UI fragments (Hero, Schedule, Actions) should be pure reusable templates.
- [ ] **Security**: Add basic local authentication and CSRF protection to the web dashboard.
- [ ] **Theme Support**: Allow users to toggle between "Brutalist Black" and "High-Contrast" themes.

## 3. Hardware Intelligence (User Experience)
- [ ] **Auto-Calibration backend**: Finalize the 30-second measurement logic.
- [ ] **Calibration UI**: A polished, guided "wizard" experience in the dashboard.
- [ ] **Hardware profiles**: Allow users to save different thresholds for "Office Mouse" vs "Gaming Mouse."

## 4. The Professional Installer (Distribution)
Move away from the "anchored clone" model to standard Linux filesystem standards:

- **The Code**: Moved to `~/.local/lib/locked-in/`
- **The Binary**: Symlinked to `~/.local/bin/locked-in` (so it's just a command in the terminal).
- **The Config**: Moved to `~/.config/locked-in/config.toml`.
- **The Data**: Keep in `~/.local/share/locked-in/`.

**One-Shot Script Logic:**
1. Clone repo to temp dir.
2. Build/Compile everything.
3. Move files to the paths above.
4. Delete the temp clone.
5. `locked-in --version` should just work from any folder.

## 5. The "Arch Way" (Final Polish)
- [ ] **Create PKGBUILD**: A proper Arch package that can be submitted to the AUR.
- [ ] **Dependencies**: Explicit mapping of `qt6-base`, `libpulse`, `hyprlock`, etc.
- [ ] **Service Management**: Package includes the systemd units in `/usr/lib/systemd/user/`.

---

## RECOVERY / UNINSTALL
To completely remove a "Perfect" installation:
```bash
locked-in uninstall --purge
```
- This command should remove all binaries, service files, and config.
- It should offer to keep or delete the database (`~/.local/share/locked-in`).

---

## VERIFICATION OF PERFECTION
The app is perfect when:
1. A user can install it with one command on a fresh Arch machine.
2. The user never has to look at `/proc/interrupts` manually.
3. The dashboard is accessible and styled perfectly on mobile and desktop.
4. The "Warden" survives reboots and crashes without skipping a second of focus time.
