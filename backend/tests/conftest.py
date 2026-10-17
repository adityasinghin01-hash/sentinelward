"""Backend test imports and broker-free fixtures."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
from sw_common import validate


class FakeClock:
    def __init__(self):
        self.wall = 1792252800000
        self.tick = 100.0

    def ms(self):
        return self.wall

    def mono(self):
        return self.tick

    def advance(self, seconds):
        self.wall += int(seconds * 1000)
        self.tick += seconds


class FakeBus:
    def __init__(self):
        self.is_connected = True
        self.sent = []
        self.accept = True
        self.handlers = []
        self.closed = False

    def subscribe(self, patterns, handler):
        self.handlers.append(handler)

    def connect(self, wait_s=0):
        return self.is_connected

    def publish(self, message):
        assert validate(message) == []
        if self.accept:
            self.sent.append(copy.deepcopy(message))
        return self.accept

    def close(self):
        self.closed = True

    def stats(self):
        return {"invalid": 0}


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def bus():
    return FakeBus()
