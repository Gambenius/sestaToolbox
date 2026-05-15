import dash
from utils.monitor_template import SensorMonitor
from utils.sensor_logic import parse_tc_config

dash.register_page(
    __name__,
    path="/thermo",
    name="TC Monitor",
    title="TC Monitor"
)

_monitor = SensorMonitor(
    page_id     = "tc",
    title       = "TC MONITOR",
    config_path = "utils/lists/tc_groups.txt",
    parse_fn    = parse_tc_config,
)

layout = _monitor.get_layout()
_monitor.register_callbacks()