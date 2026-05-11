# Plan: Non-Negotiable Tasks + Brutality System

## Context

User wants two features for Locked-In:
1. **Non-negotiable tasks** — tasks that force media playback (podcast, YouTube) during lock-in. Can't be skipped/closed.
2. **Brutality system** — a multi-dimensional knob that cranks up enforcement across ALL existing settings. Not just 3 fixed presets — individual settings are tunable per level.

Brutality is a **scaler on every enforcement dimension**:
- Pauses per hour (e.g., 3/hr normal → 1/hr hard → 0 on NN tasks in brutal)
- Grace period (5min → 2.5min → 0)
- Give-up difficulty (3 clicks → type phrase → impossible)
- Blocker window (optional → forced → uncloseable)
- Auto-chain skip (allowed → warned → forced)
- Stretch lockout enforcement
- Non-negotiable task enforcement (skip/pause/close media)

The 3 presets (Normal / Hard / Brutal) are sensible defaults. Each knob can ALSO be manually overridden in config for power users.

Both features are **future improvements**, not immediate execution.

---

## Phase 1: Foundation (DB + Config)

### 1A. Config — brutality system

**File: `src/locked_in/config.py`**

Add a new `[brutality]` config section with per-knob overrides. Each knob has a value per level. If user sets an explicit value in config, it overrides the preset.

```python
@dataclass
class BrutalityConfig:
    level: str = "normal"  # "normal" | "hard" | "brutal"

    # Per-knob overrides (None = use preset default for current level)
    max_pauses_per_hour: int | None = None      # normal: ∞, hard: 3, brutal: 0 (on NN tasks)
    grace_seconds_override: int | None = None    # normal: 300, hard: 150, brutal: 0
    give_up_mode: str | None = None              # normal: "cooldown_3", hard: "phrase", brutal: "disabled"
    blocker_window_force: bool | None = None     # normal: false, hard: true, brutal: true
    force_auto_chain: bool | None = None         # normal: false, hard: false, brutal: true
    nn_enforce_media: bool | None = None         # normal: false, hard: true, brutal: true
    nn_block_pause: bool | None = None           # normal: false, hard: false, brutal: true
```

Add to `ENV_FIELD_MAP`:
```python
"brutality": {
    "level": ("BRUTALITY_LEVEL",),
    "max_pauses_per_hour": ("BRUTALITY_MAX_PAUSES_PER_HOUR",),
    # ... etc
}
```

Add to `config.example.toml`:
```toml
[brutality]
# Preset: "normal" (chill), "hard" (phrase give-up, fewer breaks), "brutal" (no escape)
level = "normal"

# Override individual knobs (uncomment to override preset):
# max_pauses_per_hour = 3
# give_up_mode = "phrase"
# grace_seconds_override = 0
```

### 1B. DB — non-negotiable fields on `plan_tasks`

**File: `src/locked_in/simple_store.py`**

Via existing `_ensure_columns`:
```python
self._ensure_column("plan_tasks", "is_non_negotiable", "INTEGER NOT NULL DEFAULT 0")
self._ensure_column("plan_tasks", "media_url", "TEXT")
self._ensure_column("plan_tasks", "media_type", "TEXT")  # "youtube" | "podcast" | "web" | NULL
```

Extend `PlanTask`:
```python
@dataclass
class PlanTask:
    # ... existing fields ...
    is_non_negotiable: bool = False
    media_url: str | None = None
    media_type: str | None = None
```

Extend `EditableTaskDraft` and `TaskDraft` similarly.

Update `get_plan()`, `save_plan_rows()`, `update_task()` queries to include the 3 new columns.

---

## Phase 2: Brutality Policy Module

**New file: `src/locked_in/brutality.py`**

```python
class BrutalityPolicy:
    """Centralizes all brutality-dependent decisions.

    Each knob has:
    1. A preset default per level (normal/hard/brutal)
    2. An optional user override from config
    User override always wins.
    """

    # Preset defaults per level
    PRESETS = {
        "normal": {
            "max_pauses_per_hour": None,       # unlimited
            "grace_seconds": 300,
            "give_up_mode": "cooldown_3",      # 3 attempts with cooldown
            "blocker_window_force": False,
            "force_auto_chain": False,
            "nn_enforce_media": False,
            "nn_block_pause": False,
        },
        "hard": {
            "max_pauses_per_hour": 3,
            "grace_seconds": 150,
            "give_up_mode": "phrase",          # must type phrase
            "blocker_window_force": True,
            "force_auto_chain": False,
            "nn_enforce_media": True,
            "nn_block_pause": False,
        },
        "brutal": {
            "max_pauses_per_hour": 0,          # 0 on NN tasks = no pause
            "grace_seconds": 0,
            "give_up_mode": "disabled",        # impossible
            "blocker_window_force": True,
            "force_auto_chain": True,
            "nn_enforce_media": True,
            "nn_block_pause": True,
        },
    }

    def __init__(self, config: BrutalityConfig):
        self.level = config.level
        preset = self.PRESETS.get(config.level, self.PRESETS["normal"])
        # User overrides beat presets
        self.max_pauses_per_hour = config.max_pauses_per_hour or preset["max_pauses_per_hour"]
        self.grace_seconds = config.grace_seconds_override or preset["grace_seconds"]
        self.give_up_mode = config.give_up_mode or preset["give_up_mode"]
        self.blocker_window_force = config.blocker_window_force if config.blocker_window_force is not None else preset["blocker_window_force"]
        # ... etc for each knob

    # Decision methods
    def can_give_up(self) -> bool
    def requires_phrase(self) -> bool
    def can_pause(self, is_non_negotiable: bool, pauses_this_hour: int) -> bool
    def effective_grace_seconds(self) -> int
    def should_force_blocker(self) -> bool
    def should_force_auto_chain(self) -> bool
```

Pure logic, no side effects. Each knob is independently overridable. Easy to unit test.

---

## Phase 3: Media Enforcer

**New file: `src/locked_in/media_enforcer.py`**

```python
class MediaEnforcer:
    def start_media(self, url: str, media_type: str | None)
    def stop_media(self)
    @property
    def is_active(self) -> bool
```

Strategy: `webbrowser.open(url)` — simplest, works on Linux/Wayland. Enforcement comes from brutality level (can't give up, can't pause), not from trapping media in a window. Embedding players (Qt WebEngine, YouTube iframe) is fragile and adds heavy deps.

---

## Phase 4: Daemon Wiring

**File: `src/locked_in/daemon.py`**

### 4A. Instantiate policy + enforcer in `__init__`
```python
self._brutality = BrutalityPolicy(config.brutality)
self._media_enforcer = MediaEnforcer()
self._pauses_this_hour = 0
self._hour_marker = datetime.now()  # for tracking pauses-per-hour
```

### 4B. Give-up changes (`_on_give_up` ~line 486)
- Check `self._brutality.can_give_up()` — reject if disabled
- Check `self._brutality.requires_phrase()` — require phrase verification

### 4C. Pause changes — **multi-dimensional**
- Before pausing, check BOTH:
  1. `self._brutality.can_pause(is_non_negotiable, pauses_this_hour)` — NN + brutal = blocked
  2. Pauses-per-hour limit: increment `_pauses_this_hour`, reset counter when hour rolls over

### 4D. Grace period (`_start_session`)
- Use `self._brutality.effective_grace_seconds()` instead of raw config value

### 4E. Blocker window (`_activate_item`)
- Use `self._brutality.should_force_blocker()` to override config

### 4F. Auto-chain
- If `self._brutality.should_force_auto_chain()`, auto-continue to next task without asking

### 4G. Media playback (`_on_confirmed`)
- If current task is NN with media_url, call `self._media_enforcer.start_media(url, type)`

### 4H. Media cleanup
- In `_on_item_finished` and `_do_give_up`: `self._media_enforcer.stop_media()`

### 4I. Status response
- Include `brutality_level`, `media_active`, `pauses_this_hour`, `max_pauses_per_hour` in `_build_status()`

---

## Phase 5: Web UI Changes

### 5A. Settings page — brutality section with preset + knobs
**File: `src/locked_in/templates/settings.html`**

Add "Brutality" section with:
- Preset selector: Normal / Hard / Brutal (sets all knobs to preset defaults)
- Individual knob overrides (collapsible/advanced): max pauses/hr, grace seconds, give-up mode, etc.
- When preset changes, JS updates knob fields to preset defaults. User can then tweak individually.

**File: `src/locked_in/web_frontend.py`** — handle saving all brutality fields to config.toml `[brutality]` section.

### 5B. Planner task row — non-negotiable fields
**File: `src/locked_in/web_frontend.py`**

Extend `_render_task_row` with:
- Checkbox: "Non-negotiable"
- Text input: "Media URL"
- Select: media type (YouTube / Podcast / Web)

Parse in `_task_rows_from_form` → `EditableTaskDraft` with new fields.

### 5C. Schedule list — NN badge
Show red "NON-NEGOTIABLE" tag on tasks that are marked NN.

### 5D. Hero — media link + brutality badge
- When running a NN task with media: show "Now Playing" link
- Show brutality level badge (amber=hard, red=brutal) in banner

### 5E. Actions — conditional show/hide based on policy
- Hide "Pause" when: NN task + `nn_block_pause` is true, OR `max_pauses_per_hour` reached
- Hide "Give Up" when: `give_up_mode` is "disabled"
- Pause button shows remaining pauses count when limited (e.g., "Pause (1/3 left)")
- Hard mode give-up: modal/inline asking for the phrase

### 5F. Hard mode give-up phrase verification
New POST handler `/give-up/verify` — compares typed phrase to config value, then sends `give_up` command with `phrase_verified: true`.

---

## Phase 6: Blocker Window (PyQt6)

**File: `src/locked_in/ui.py`**

- In brutal mode: hide the "Give Up" button entirely
- In hard mode: replace "Give Up" button with phrase input field

---

## Key Design Decisions

| Decision | Why |
|----------|-----|
| Browser-based media, not embedded | Qt WebEngine is ~200MB, fragile on Wayland. Enforcement via brutality, not window trapping |
| `BrutalityPolicy` as separate module | Keeps branching out of daemon's complex logic. Testable in isolation |
| Multi-knob config, not just 3 presets | User wants fine-grained control. Presets are sensible defaults, not cages |
| `_ensure_columns` for migration | Existing pattern, no migration scripts needed |
| Default `"normal"` with all `None` overrides | Full backward compatibility — existing configs behave identically |
| `BrutalityConfig` as separate section, not crammed into `WardenConfig` | Keeps config clean. Brutality is a cross-cutting concern touching scheduler, warden, UI |

---

## Files Modified (summary)

| File | Change |
|------|--------|
| `config.py` | Add `BrutalityConfig` dataclass with level + all knobs, add to `Config` |
| `config.example.toml` | Add `[brutality]` section with level preset + optional overrides |
| `simple_store.py` | 3 new columns, extend PlanTask/TaskDraft/EditableTaskDraft, update queries |
| `brutality.py` (NEW) | BrutalityPolicy class |
| `media_enforcer.py` (NEW) | MediaEnforcer class |
| `daemon.py` | Wire brutality policy + media enforcer, modify give-up/pause/activate/grace/auto-chain + pauses-per-hour tracking |
| `web_frontend.py` | Settings saving, task row NN fields, schedule badges, hero media, phrase verify, action hiding |
| `templates/settings.html` | Brutality section with preset selector + individual knob overrides |
| `templates/components/hero.html` | Media link |
| `templates/components/schedule.html` | NN badge |
| `templates/components/actions.html` | Conditional show/hide based on policy (pause count, give-up mode) |
| `templates/components/banner.html` | Brutality badge |
| `ui.py` | Brutality-aware blocker window |

---

## Verification

1. **Config**: Start daemon with `brutality.level = "normal"` + no overrides — verify identical behavior to current
2. **Config**: Set `brutality.level = "hard"` — verify preset kicks in (phrase give-up, forced blocker, 3 pauses/hr)
3. **Config**: Set `brutality.level = "normal"` but override `max_pauses_per_hour = 2` — verify only that knob changes
4. **DB**: Add task with `is_non_negotiable=1, media_url="...", media_type="youtube"` — verify persists and loads
5. **Normal mode**: Give up after 3 attempts (same as now)
6. **Hard mode**: Give-up requires typing phrase; blocker window forced on; max 3 pauses/hr
7. **Brutal mode**: No give-up; NN tasks can't be paused; grace=0; auto-chain forced
8. **Pauses-per-hour**: In hard mode, after 3 pauses in one hour, pause button disappears. Resets next hour.
9. **Media**: Start a NN task → browser opens the URL; finish task → media tracked
10. **Settings**: Change brutality preset via web UI → all knob fields update to preset defaults → save → daemon respects after restart
