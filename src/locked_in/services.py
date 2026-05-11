from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from queue import Queue

log = logging.getLogger(__name__)

class EventType(Enum):
    USER_ACTIVITY_SOFT = auto()
    USER_ACTIVITY_HARD = auto()
    MIC_ACTIVE = auto()
    MIC_SILENT = auto()
    TICK = auto()

@dataclass
class Event:
    type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict = field(default_factory=dict)

class BaseService(ABC, threading.Thread):
    def __init__(self, event_queue: Queue[Event]):
        super().__init__(daemon=True)
        self.event_queue = event_queue
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    @abstractmethod
    def run(self):
        pass

class TickService(BaseService):
    def run(self):
        log.info("TickService started")
        while not self._stop_event.is_set():
            self.event_queue.put(Event(EventType.TICK))
            self._stop_event.wait(1.0)

class IdleService(BaseService):
    def __init__(self, event_queue: Queue[Event], idle_detector):
        super().__init__(event_queue)
        self.detector = idle_detector

    def run(self):
        log.info("IdleService started")
        self.detector.start()
        
        last_soft = self.detector.seconds_since_any_activity()
        last_hard = self.detector.seconds_since_hard_activity()
        
        while not self._stop_event.is_set():
            time.sleep(0.5)
            curr_soft = self.detector.seconds_since_any_activity()
            curr_hard = self.detector.seconds_since_hard_activity()
            
            if curr_soft < last_soft:
                self.event_queue.put(Event(EventType.USER_ACTIVITY_SOFT))
            if curr_hard < last_hard:
                self.event_queue.put(Event(EventType.USER_ACTIVITY_HARD))
                
            last_soft = curr_soft
            last_hard = curr_hard
        
        self.detector.stop()

class MicService(BaseService):
    def __init__(self, event_queue: Queue[Event], mic_detector, poll_seconds: int):
        super().__init__(event_queue)
        self.detector = mic_detector
        self.poll_seconds = max(poll_seconds, 1)

    def run(self):
        log.info("MicService started")
        while not self._stop_event.is_set():
            snapshot = self.detector.snapshot()
            if snapshot.active:
                self.event_queue.put(Event(EventType.MIC_ACTIVE, data={"apps": snapshot.apps}))
            else:
                self.event_queue.put(Event(EventType.MIC_SILENT))
            
            self._stop_event.wait(self.poll_seconds)
