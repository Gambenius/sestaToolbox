from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from typing import Optional, List
import re
import os

from utils.shared_state import tag_data, active_tags, state_lock


# ── SENSOR ────────────────────────────────────────────────────────────────

@dataclass
class PressureSensor:
    tag:     str
    name:    str   = ""
    min_val: float = 0.0
    max_val: float = 100.0

    _value: Optional[float]   = field(default=None, init=False, repr=False)
    _ts:    Optional[datetime] = field(default=None, init=False, repr=False)

    def read(self) -> Optional[float]:
        """Pull latest value from shared OPC deque."""
        with state_lock:
            dq: deque = tag_data.get(self.tag, deque())
            if dq:
                self._ts, self._value = dq[-1]
        return self._value

    @property
    def value(self) -> Optional[float]:
        return self._value

    @property
    def pct(self) -> float:
        """Value as percentage of [min_val, max_val], clamped 0–100."""
        if self._value is None:
            return 0.0
        span = self.max_val - self.min_val or 1.0
        return max(0.0, min(100.0, (self._value - self.min_val) / span * 100))

    def activate(self):
        """Register tag with the shared OPC subscription set."""
        with state_lock:
            active_tags.add(self.tag)


# ── GROUP ─────────────────────────────────────────────────────────────────

@dataclass
class SensorGroup:
    id:        int
    name:      str
    tolerance: float                  = 5.0
    sensors:   List[PressureSensor]   = field(default_factory=list)

    def read_all(self):
        for s in self.sensors:
            s.read()

    def activate_all(self):
        for s in self.sensors:
            s.activate()

    # ── internal helpers ──────────────────────────────────────────────────

    def _live_vals(self) -> List[float]:
        return [s.value for s in self.sensors if s.value is not None]

    def _average(self) -> Optional[float]:
        vals = self._live_vals()
        return sum(vals) / len(vals) if vals else None

    # ── per-sensor status (tolerance-based) ───────────────────────────────

    def sensor_status(self, sensor: PressureSensor) -> str:
        """
        ok      — deviation from group average ≤ tolerance
        warn    — deviation > tolerance * 0.5  (half-tolerance zone)
        alarm   — deviation > tolerance
        nodata  — no value yet
        """
        if sensor.value is None:
            return "nodata"
        avg = self._average()
        if avg is None:
            return "nodata"
        dev = abs(sensor.value - avg)
        if dev > self.tolerance:
            return "alarm"
        if dev > self.tolerance * 0.5:
            return "warn"
        return "ok"

    # ── group-level status ────────────────────────────────────────────────

    @property
    def status(self) -> str:
        statuses = [self.sensor_status(s) for s in self.sensors]
        if "alarm"  in statuses: return "alarm"
        if "warn"   in statuses: return "warn"
        if all(st == "nodata" for st in statuses): return "nodata"
        return "ok"

    # ── summary line ──────────────────────────────────────────────────────

    @property
    def summary(self) -> str:
        vals = self._live_vals()
        if not vals:
            return "No data"
        avg    = sum(vals) / len(vals)
        spread = max(vals) - min(vals)
        flag   = " ⚠" if spread > self.tolerance else ""
        return f"μ={avg:.3f}  Δ={spread:.3f}  tol=±{self.tolerance}{flag}"

    # ── average as a synthetic PressureSensor ─────────────────────────────

    def average_sensor(self) -> Optional[PressureSensor]:
        """Returns a PressureSensor-like object representing the group average."""
        avg = self._average()
        if avg is None or not self.sensors:
            return None
        s0  = self.sensors[0]
        proxy       = PressureSensor(tag="AVG", name="Average",
                                     min_val=s0.min_val, max_val=s0.max_val)
        proxy._value = avg  # noqa: set private directly
        return proxy


# ── CONFIG PARSER ─────────────────────────────────────────────────────────

def parse_config(path: str) -> List[SensorGroup]:
    if not os.path.exists(path):
        return []

    groups: List[SensorGroup] = []
    with open(path, encoding="utf-8") as f:
        # Normalize line endings so \r doesn't corrupt float parsing
        text = f.read().replace("\r\n", "\n").replace("\r", "\n")

    blocks = re.split(r'\bGROUP\b', text, flags=re.IGNORECASE)

    for block in blocks[1:]:
        m = re.search(r'\{(.*?)\}', block, re.DOTALL)
        if not m:
            continue
        body = m.group(1)

        # _body=body captures body by value, avoiding the closure-over-loop bug
        def get_val(key: str, default: str = "", _body: str = body) -> str:
            km = re.search(rf'^\s*{key}\s*=\s*(.+)$', _body,
                           re.MULTILINE | re.IGNORECASE)
            return km.group(1).strip() if km else default

        try:
            gid       = int(get_val("id",        "0"))
            gname     = get_val("name",           f"Group {gid}")
            tolerance = float(get_val("tolerance","5"))
        except ValueError:
            continue

        # Optional per-group limits = (min, max)
        lim_match = re.search(r'limits\s*=\s*\(([^)]*)\)', body, re.IGNORECASE)
        min_val, max_val = 0.0, 100.0
        if lim_match:
            parts = lim_match.group(1).split(",")
            if len(parts) == 2:
                try:
                    min_val = float(parts[0].strip())
                    max_val = float(parts[1].strip())
                except ValueError:
                    pass

        # members = (TAG1, TAG2, ...)
        mem_match = re.search(r'members\s*=\s*\(([^)]*)\)', body, re.IGNORECASE)
        tags = []
        if mem_match:
            tags = [t.strip() for t in mem_match.group(1).split(",") if t.strip()]

        sensors = [
            PressureSensor(tag=t, name=t, min_val=min_val, max_val=max_val)
            for t in tags
        ]
        groups.append(SensorGroup(id=gid, name=gname,
                                  tolerance=tolerance, sensors=sensors))

    return sorted(groups, key=lambda g: g.id)