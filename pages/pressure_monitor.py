import dash
from utils.monitor_template import SensorMonitor
from utils.sensor_logic import parse_pressure_config

dash.register_page(
    __name__,
    path="/pressure",
    name="Pressure Monitor",
    title="Pressure Monitor"
)

_monitor = SensorMonitor(
    page_id     = "pm",
    title       = "PRESSURE MONITOR",
    config_path = "utils/lists/pressure_groups.txt",
    parse_fn    = parse_pressure_config,
)

layout = _monitor.get_layout()
_monitor.register_callbacks()