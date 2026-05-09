from __future__ import annotations

import logging
from datetime import datetime

from .models import State

log = logging.getLogger(__name__)

TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.AWAITING_TASK_START, State.FINISHED},
    State.AWAITING_TASK_START: {
        State.TASK_ACTIVE,
        State.AWAITING_BREAK_START,
        State.PAUSED,
        State.GIVEN_UP,
        State.FINISHED,
    },
    State.TASK_ACTIVE: {State.AWAITING_TASK_START, State.AWAITING_BREAK_START, State.PAUSED, State.GIVEN_UP, State.FINISHED},
    State.AWAITING_BREAK_START: {State.BREAK_ACTIVE, State.PAUSED, State.GIVEN_UP, State.FINISHED},
    State.BREAK_ACTIVE: {State.AWAITING_TASK_START, State.PAUSED, State.GIVEN_UP, State.FINISHED},
    State.PAUSED: {State.AWAITING_TASK_START, State.TASK_ACTIVE, State.AWAITING_BREAK_START, State.BREAK_ACTIVE, State.GIVEN_UP},
    State.GIVEN_UP: set(),
    State.FINISHED: set(),
}


class StateMachine:
    def __init__(self):
        self.state = State.IDLE
        self._previous_state: State | None = None
        self._paused_at: datetime | None = None

    def transition(self, target: State) -> bool:
        if target == self.state:
            return True
        allowed = TRANSITIONS.get(self.state, set())
        if target not in allowed:
            log.warning("Invalid transition: %s -> %s", self.state.value, target.value)
            return False
        log.info("State: %s -> %s", self.state.value, target.value)
        if target == State.PAUSED:
            self._previous_state = self.state
            self._paused_at = datetime.now()
        self.state = target
        return True

    @property
    def pause_duration_seconds(self) -> float:
        if self._paused_at is None:
            return 0.0
        return (datetime.now() - self._paused_at).total_seconds()

    def resume(self) -> State | None:
        if self.state != State.PAUSED or self._previous_state is None:
            return None
        previous = self._previous_state
        self._previous_state = None
        self._paused_at = None
        self.state = previous
        log.info("Resumed to %s", previous.value)
        return previous

    @property
    def previous_state(self) -> State | None:
        return self._previous_state
