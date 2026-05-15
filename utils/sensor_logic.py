from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from typing import Optional, List
import re
import statistics
import os

# ── NO top-level import from utils.shared_state ───────────────────────────
FROZEN_SECONDS = 5.0   # seconds without a value change → "frozen"


# ── SENSOR ────────────────────────────────────────────────────────────────

@dataclass
class PressureSensor:
    tag:      str
    name:     str   = ""
    min_val:  float = 0.0
    max_val:  float = 100.0
    disabled: bool  = False  # Added to track exclusion from calculations

    _value:       Optional[float]    = field(default=None, init=False, repr=False)
    _ts:          Optional[datetime] = field(default=None, init=False, repr=False)
    _last_change: Optional[datetime] = field(default=None, init=False, repr=False)

    def read(self) -> Optional[float]:
        """Pull latest value from shared OPC deque (lazy import)."""
        from utils.shared_state import tag_data, state_lock

        with state_lock:
            dq: deque = tag_data.get(self.tag, deque())
            if dq:
                ts, val = dq[-1]
                if val != self._value:
                    self._last_change = ts
                self._ts    = ts
                self._value = val
        return self._value

    def activate(self):
        """Register tag with the shared OPC subscription set (lazy import)."""
        from utils.shared_state import active_tags, state_lock

        with state_lock:
            active_tags.add(self.tag)

    @property
    def value(self) -> Optional[float]:
        return self._value

    @property
    def pct(self) -> float:
        if self._value is None:
            return 0.0
        span = self.max_val - self.min_val or 1.0
        return max(0.0, min(100.0, (self._value - self.min_val) / span * 100))
    
    @property
    def is_out_of_range(self) -> bool:
        """True when value is outside [min_val, max_val]."""
        if self._value is None:
            return False
        return self._value < self.min_val or self._value > self.max_val
    
    @property
    def is_frozen(self) -> bool:
        """True when value hasn't changed for FROZEN_SECONDS — stuck transmitter."""
        if self._value is None:
            return False
        ref = self._last_change or self._ts
        if ref is None:
            return False
        return (datetime.now() - ref).total_seconds() >= FROZEN_SECONDS

@dataclass
class Thermocouple:
    tag:      str
    name:     str   = ""
    min_val:  float = 0.0
    max_val:  float = 100.0
    disabled: bool  = False  # Added to track exclusion from calculations

    _value:       Optional[float]    = field(default=None, init=False, repr=False)
    _ts:          Optional[datetime] = field(default=None, init=False, repr=False)
    _last_change: Optional[datetime] = field(default=None, init=False, repr=False)

    def read(self) -> Optional[float]:
        """Pull latest value from shared OPC deque (lazy import)."""
        from utils.shared_state import tag_data, state_lock

        with state_lock:
            dq: deque = tag_data.get(self.tag, deque())
            if dq:
                ts, val = dq[-1]
                if val != self._value:
                    self._last_change = ts
                self._ts    = ts
                self._value = val
        return self._value

    def activate(self):
        """Register tag with the shared OPC subscription set (lazy import)."""
        from utils.shared_state import active_tags, state_lock

        with state_lock:
            active_tags.add(self.tag)

    @property
    def value(self) -> Optional[float]:
        return self._value

    @property
    def pct(self) -> float:
        if self._value is None:
            return 0.0
        span = self.max_val - self.min_val or 1.0
        return max(0.0, min(100.0, (self._value - self.min_val) / span * 100))
    
    @property
    def is_out_of_range(self) -> bool:
        """True when value is outside [min_val, max_val]."""
        if self._value is None:
            return False
        return self._value < self.min_val or self._value > self.max_val
    
    @property
    def is_frozen(self) -> bool:
        """True when value hasn't changed for FROZEN_SECONDS — stuck transmitter."""
        if self._value is None:
            return False
        ref = self._last_change or self._ts
        if ref is None:
            return False
        return (datetime.now() - ref).total_seconds() >= FROZEN_SECONDS


# ── GROUP ─────────────────────────────────────────────────────────────────

@dataclass
class PressureGroup:
    id:        int
    name:      str
    tolerance: float                = 5.0
    ah:        Optional[float]      = None   # Alarm High (Optional)
    ahh:       Optional[float]      = None   # Alarm High High (Optional)
    sensors:   List[PressureSensor] = field(default_factory=list)

    def read_all(self):
        for s in self.sensors:
            s.read()

    def activate_all(self):
        for s in self.sensors:
            s.activate()

    def _live_vals(self) -> List[float]:
        """Returns values for sensors that are not None and not disabled."""
        return [s.value for s in self.sensors if s.value is not None and not s.disabled]

    def _average(self) -> Optional[float]:
        """Calculates the median of enabled sensors."""
        vals = self._live_vals()
        return statistics.median(vals) if vals else None

    def sensor_status(self, sensor: PressureSensor) -> str:
        """
        Updated Priority Order:
        1. disabled     - user excluded sensor
        2. nodata       - no value
        3. out_of_range - outside [min, max]
        4. frozen       - value unchanged
        5. alarmHHigh   - value > ahh
        6. alarmHigh    - value > ah
        7. deviation    - deviation from median > tolerance
        8. ok           - deviation <= tolerance
        """
        if sensor.disabled:
            return "disabled"
        if sensor.value is None:
            return "nodata"
        if sensor.is_out_of_range:
            return "out_of_range"
        if sensor.is_frozen:
            return "frozen"
        
        if self.ahh is not None and sensor.value > self.ahh:
            return "alarmHHigh"
        if self.ah is not None and sensor.value > self.ah:
            return "alarmHigh"
        
        avg = self._average()
        if avg is None:
            return "nodata"
            
        # Deviation check: removed 0.5* tolerance 'warn' logic
        dev = abs(sensor.value - avg)
        if dev > self.tolerance:
            return "deviation"
        return "ok"

    @property
    def status(self) -> str:
        statuses = [self.sensor_status(s) for s in self.sensors]
        if "alarmHHigh"    in statuses: return "alarmHHigh"
        if "alarmHigh"     in statuses: return "alarmHigh"
        if "deviation"     in statuses: return "deviation"
        if "out_of_range"  in statuses: return "out_of_range"
        if "frozen"        in statuses: return "frozen"
        if all(st in ["nodata", "disabled"] for st in statuses): return "nodata"
        return "ok"

    @property
    def summary(self) -> str:
        vals = self._live_vals()
        if not vals:
            return "No data"
        
        med    = self._average()
        spread = max(vals) - min(vals)
        frozen = sum(1 for s in self.sensors if s.is_frozen and not s.disabled)
        
        # Warning flag if spread > tolerance or if any sensor exceeds AH (if set)
        has_high_alarm = (self.ah is not None and any(v > self.ah for v in vals))
        flag = " ⚠" if (spread > self.tolerance or has_high_alarm) else ""
        frz  = f"  ❄{frozen}" if frozen else ""
        
        return f"med={med:.3f}  Δ={spread:.3f}  tol=±{self.tolerance}{flag}{frz}"

    def average_sensor(self) -> Optional[PressureSensor]:
        avg = self._average()
        if avg is None or not self.sensors:
            return None
        s0           = self.sensors[0]
        proxy        = PressureSensor(tag="AVG", name="Median",
                                      min_val=s0.min_val, max_val=s0.max_val)
        proxy._value = avg
        return proxy

@dataclass
class TCGroup:
    id:        int
    name:      str
    tolerance: float                = 5.0
    ah:        Optional[float]      = None
    ahh:       Optional[float]      = None
    sensors:   List[Thermocouple]   = field(default_factory=list)

    def read_all(self):
        for s in self.sensors:
            s.read()

    def activate_all(self):
        for s in self.sensors:
            s.activate()

    def _live_vals(self) -> List[float]:
        """Returns values for sensors that are not None and not disabled."""
        return [s.value for s in self.sensors if s.value is not None and not s.disabled]

    def _average(self) -> Optional[float]:
        """Calculates the median of enabled sensors."""
        vals = self._live_vals()
        return statistics.median(vals) if vals else None

    def sensor_status(self, sensor: Thermocouple) -> str:
        if sensor.disabled:
            return "disabled"
        if sensor.value is None:
            return "nodata"
        if sensor.is_out_of_range:
            return "out_of_range"
        if sensor.is_frozen:
            return "frozen"
        
        if self.ahh is not None and sensor.value > self.ahh:
            return "alarmHHigh"
        if self.ah is not None and sensor.value > self.ah:
            return "alarmHigh"
        
        avg = self._average()
        if avg is None:
            return "nodata"
            
        dev = abs(sensor.value - avg)
        if dev > self.tolerance:
            return "deviation"
        if dev > self.tolerance * 0.5:
            return "warn"
        return "ok"

    @property
    def status(self) -> str:
        statuses = [self.sensor_status(s) for s in self.sensors]
        if "alarmHHigh"    in statuses: return "alarmHHigh"
        if "alarmHigh"     in statuses: return "alarmHigh"
        if "deviation"         in statuses: return "deviation"
        if "out_of_range"  in statuses: return "out_of_range"
        if "frozen"        in statuses: return "frozen"
        if "warn"          in statuses: return "warn"
        if all(st in ["nodata", "disabled"] for st in statuses): return "nodata"
        return "ok"

    @property
    def summary(self) -> str:
        vals = self._live_vals()
        if not vals:
            return "No data"
        
        med    = self._average()
        spread = max(vals) - min(vals)
        frozen = sum(1 for s in self.sensors if s.is_frozen and not s.disabled)
        
        has_high_alarm = (self.ah is not None and any(v > self.ah for v in vals))
        flag = " ⚠" if (spread > self.tolerance or has_high_alarm) else ""
        frz  = f"  ❄{frozen}" if frozen else ""
        
        return f"med={med:.3f}  Δ={spread:.3f}  tol=±{self.tolerance}{flag}{frz}"

    def average_sensor(self) -> Optional[Thermocouple]:
        avg = self._average()
        if avg is None or not self.sensors:
            return None
        s0           = self.sensors[0]
        proxy        = Thermocouple(tag="AVG", name="Median",
                                      min_val=s0.min_val, max_val=s0.max_val)
        proxy._value = avg
        return proxy

# ── CONFIG PARSER ─────────────────────────────────────────────────────────

def parse_pressure_config(path: str) -> List[PressureGroup]:
    if not os.path.exists(path):
        return []

    groups: List[PressureGroup] = []
    with open(path, encoding="utf-8") as f:
        text = f.read().replace("\r\n", "\n").replace("\r", "\n")

    blocks = re.split(r'\bGROUP\b', text, flags=re.IGNORECASE)

    for block in blocks[1:]:
        m = re.search(r'\{(.*?)\}', block, re.DOTALL)
        if not m:
            continue
        body = m.group(1)

        def get_val(key: str, default: Optional[str] = None, _body: str = body) -> Optional[str]:
            # Capture non-whitespace content. If line is 'key =', it returns None.
            km = re.search(rf'^\s*{key}\s*=\s*(.*?)\s*$', _body,
                           re.MULTILINE | re.IGNORECASE)
            if km:
                val = km.group(1).strip()
                return val if val else None
            return default

        try:
            gid       = int(get_val("id",         "0"))
            gname     = get_val("name",            f"Group {gid}")
            tolerance = float(get_val("tolerance", "5"))
            
            # Read AH/AHH. Convert to float only if string exists.
            ah_str    = get_val("ah")
            ah        = float(ah_str) if ah_str else None
            ahh_str   = get_val("ahh")
            ahh       = float(ahh_str) if ahh_str else None
            
        except ValueError:
            continue

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

        mem_match = re.search(r'members\s*=\s*\(([^)]*)\)', body, re.IGNORECASE)
        tags = []
        if mem_match:
            tags = [t.strip() for t in mem_match.group(1).split(",") if t.strip()]

        sensors = [
            PressureSensor(tag=t, name=t, min_val=min_val, max_val=max_val)
            for t in tags
        ]
        groups.append(PressureGroup(id=gid, name=gname, tolerance=tolerance, 
                                    ah=ah, ahh=ahh, sensors=sensors))

    return sorted(groups, key=lambda g: g.id)



def parse_tc_config(path: str) -> List[TCGroup]:
    if not os.path.exists(path):
        return []

    groups: List[TCGroup] = []
    with open(path, encoding="utf-8") as f:
        text = f.read().replace("\r\n", "\n").replace("\r", "\n")

    blocks = re.split(r'\bGROUP\b', text, flags=re.IGNORECASE)

    for block in blocks[1:]:
        m = re.search(r'\{(.*?)\}', block, re.DOTALL)
        if not m:
            continue
        body = m.group(1)

        def get_val(key: str, default: Optional[str] = None, _body: str = body) -> Optional[str]:
            km = re.search(rf'^\s*{key}\s*=\s*(.*?)\s*$', _body,
                           re.MULTILINE | re.IGNORECASE)
            if km:
                val = km.group(1).strip()
                return val if val else None
            return default

        try:
            gid       = int(get_val("id",         "0"))
            gname     = get_val("name",            f"Group {gid}")
            tolerance = float(get_val("tolerance", "5"))
            
            ah_str    = get_val("ah")
            ah        = float(ah_str) if ah_str else None
            ahh_str   = get_val("ahh")
            ahh       = float(ahh_str) if ahh_str else None
            
        except ValueError:
            continue

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

        mem_match = re.search(r'members\s*=\s*\(([^)]*)\)', body, re.IGNORECASE)
        tags = []
        if mem_match:
            tags = [t.strip() for t in mem_match.group(1).split(",") if t.strip()]

        sensors = [
            Thermocouple(tag=t, name=t, min_val=min_val, max_val=max_val)
            for t in tags
        ]
        groups.append(TCGroup(id=gid, name=gname, tolerance=tolerance, 
                              ah=ah, ahh=ahh, sensors=sensors))

    return sorted(groups, key=lambda g: g.id)