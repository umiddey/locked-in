# Plan: Architectural Refactoring (UI & Daemon)

**Implementation Status: PENDING**

## Context & Thought Process
The current implementation of Focus Warden uses "God Objects" and manual string manipulation for UI rendering. While efficient for initial prototyping, it has become brittle and hard to maintain. Small changes often lead to `NameError` or broken HTML tags. The Daemon is also doing too much in its main loop, making it susceptible to hangs if a single service (like a network call or heavy DB query) stalls.

This plan aims to professionalize the codebase by introducing separation of concerns.

---

## Phase 1: UI Extraction (Templating)
**Goal**: Move all HTML out of Python f-strings and into Jinja2 templates.

### 1.1 Infrastructure
- Add `jinja2` to `pyproject.toml`.
- Create `src/focus_warden/templates/` directory.
- Implement a `TemplateRenderer` helper class to manage the Jinja environment.

### 1.2 Base & Components
- Create `base.html` for common CSS/JS and layout.
- Create `components/` for fragments (hero, actions, schedule).
- **Justification**: This allows us to use Jinja's `{% include %}` and `{% extend %}` to eliminate duplicated CSS/HTML boilerplate across different pages.

### 1.3 Logic Migration
- Refactor `web_frontend.py` methods to return data dictionaries instead of HTML strings.
- Update endpoints to call `render_template(name, **data)`.
- **Justification**: Separation of UI and Logic. Testing becomes easier as we can assert on the data payload rather than parsing HTML strings.

---

## Phase 2: Daemon Decoupling
**Goal**: Break the monolithic `Daemon._tick` loop into specialized background services.

### 2.1 Service Abstraction
- Create an `AbstractService` base class with `start()`, `stop()`, and `poll()` methods.
- **Justification**: Provides a consistent interface for the Daemon to manage various sub-systems.

### 2.2 Independent Services
- Move **Idle Detection** to `IdleService`.
- Move **Microphone Polling** to `ActivityService`.
- Move **Database/Store** interaction to a dedicated thread or async wrapper.
- **Justification**: If the Microphone detector hangs on a slow `pactl` command, the `IdleDetector` (which is critical for pauses) should keep running.

### 2.3 Event-Driven Orchestration
- Implement a thread-safe `EventQueue`.
- Services push events (e.g., `USER_IDLE`, `MIC_ACTIVE`) to the queue.
- The `Daemon` main loop simply consumes the queue and updates the `StateMachine`.
- **Justification**: This removes blocking logic from the main state transitions, making the "Warden" much more responsive and harder to crash.

---

## Phase 3: Validation
- **Unit Tests**: Verify template rendering with mock data.
- **Integration Tests**: Ensure service events correctly trigger State Machine transitions.
- **Performance**: Measure CPU impact of decoupled threads vs. the current single-loop approach.

---

## REFERENCES
- Critique from May 10, 2026 regarding "God Objects" and "HTML Shoveling".
