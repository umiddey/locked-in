# Plan: Hardware Auto-Calibration

**Implementation Status: PENDING**

## Context & Thought Process
Currently, Focus Warden uses hardcoded interrupt thresholds (e.g., 3 for keyboard, 10 for USB) to distinguish between noise and user activity. This is brittle because different hardware (mechanical keyboards, high-DPI mice, different USB hubs) produces vastly different interrupt rates.

"Auto-Calibration" allows the app to learn the specific "fingerprint" of the user's hardware, ensuring perfect accuracy without manual config editing.

---

## Phase 1: Calibration Logic
**Goal**: Implement the math and measurement logic in `IdleDetector`.

### 1.1 Measurement Mode
- Add a `start_calibration()` method to `IdleDetector`.
- It will run in two stages (5 seconds each):
    - **Stage A (Idle)**: User stays still. Record `max_delta` across all monitored IRQs. This is the "Noise Floor".
    - **Stage B (Active)**: User types and moves mouse. Record `avg_delta` across same IRQs. This is the "Signal Strength".

### 1.2 Threshold Calculation
- **Soft Threshold**: `Noise Floor + 1`. This catches even the smallest intentional movement above background jitter.
- **Hard Threshold**: `(Signal Strength * 0.5)`. This ensures "Intentional" activity is significantly higher than a random blip but still easy to hit during normal work.

---

## Phase 2: User Interface
**Goal**: Expose the calibration process to the user.

### 2.1 Web Dashboard Integration
- Add a "Calibrate Hardware" button in Settings.
- Implement a simple countdown UI:
    - "Don't touch anything... [5, 4, 3...]"
    - "Now type and move mouse rapidly! [5, 4, 3...]"
- Show the results: "New thresholds detected: Keyboard (2), USB (15). [Apply]"

### 2.2 CLI Integration
- `focus-warden calibrate` command for headless or terminal-focused users.

---

## Phase 3: Persistence
- Save the calculated thresholds to `config.toml` under a new `[hardware]` or `[auto_pause.thresholds]` section.
- Update `IdleDetector` to prioritize these saved values over its internal defaults.

---

## Phase 4: Cross-Platform Considerations (Future)
As we look toward **Windows** and **macOS**, the calibration logic will adapt:

- **Windows**: Use `GetLastInputInfo` (Win32). Calibration might focus on filtering out background processes that fake input.
- **macOS**: Use `CGEventSourceSecondsSinceLastEventType`. Calibration would be less about noise (since macOS handles the low-level stuff) and more about "Intensity" preferences.
- **Universal Strategy**: Maintain the "Warden" philosophy—OS-native, low-level, and impossible to ignore.

---

## REFERENCES
- User request for "genius" calibration and cross-platform support (May 10, 2026).
