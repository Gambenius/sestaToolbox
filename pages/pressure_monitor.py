import dash
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc
from datetime import datetime

from utils.pressure_logic import parse_config, SensorGroup, PressureSensor

dash.register_page(
    __name__,
    path="/pressure",
    name="Pressure Monitor",
    title="Pressure Monitor"
)

CONFIG_FILE = "utils/pressure_groups.txt"

_groups = parse_config(CONFIG_FILE)
for g in _groups:
    g.activate_all()

# ── STYLES ────────────────────────────────────────────────────────────────
STATUS_COLORS = {
    "ok":     "#2ecc71",
    "warn":   "#f39c12",
    "alarm":  "#e74c3c",
    "nodata": "#95a5a6",
}
STATUS_BG = {
    "ok":     "rgba(46,204,113,0.08)",
    "warn":   "rgba(243,156,18,0.10)",
    "alarm":  "rgba(231,76,60,0.12)",
    "nodata": "rgba(149,165,166,0.06)",
}
AVG_COLOR = "#4682B4"
AVG_BG    = "rgba(70,130,180,0.10)"


# ── UI COMPONENTS ─────────────────────────────────────────────────────────

def _bar_row(tag_label: str, pct: float, val_str: str,
             color: str, bg: str, bold: bool = False) -> html.Div:
    return html.Div([
        html.Div(tag_label, style={
            "width":        "120px",
            "flexShrink":   "0",
            "fontSize":     "11px",
            "fontFamily":   "monospace",
            "color":        color if bold else "#555",
            "fontWeight":   "700" if bold else "400",
            "paddingRight": "8px",
            "whiteSpace":   "nowrap",
            "overflow":     "hidden",
            "textOverflow": "ellipsis",
        }),
        html.Div(style={
            "flex":            "1",
            "height":          "18px",
            "backgroundColor": "#e9ecef",
            "borderRadius":    "2px",
            "overflow":        "hidden",
        }, children=[
            html.Div(style={
                "width":           f"{pct}%",
                "height":          "100%",
                "backgroundColor": color,
                "borderRadius":    "2px",
                "transition":      "width 0.4s ease",
            })
        ]),
        html.Div(val_str, style={
            "width":       "90px",
            "flexShrink":  "0",
            "textAlign":   "right",
            "fontSize":    "12px",
            "fontWeight":  "700" if bold else "600",
            "color":       color,
            "paddingLeft": "10px",
        }),
    ], style={
        "display":         "flex",
        "alignItems":      "center",
        "padding":         "4px 10px",
        "marginBottom":    "3px",
        "borderRadius":    "4px",
        "backgroundColor": bg,
        "borderLeft":      f"3px solid {color}",
    })


def sensor_bar(sensor: PressureSensor, group: SensorGroup) -> html.Div:
    status  = group.sensor_status(sensor)
    color   = STATUS_COLORS[status]
    bg      = STATUS_BG[status]
    val_str = f"{sensor.value:.3f}" if sensor.value is not None else "—"
    return _bar_row(sensor.tag, sensor.pct, val_str, color, bg)


def average_bar(group: SensorGroup) -> html.Div:
    proxy = group.average_sensor()
    if proxy is None:
        val_str, pct = "—", 0.0
    else:
        val_str = f"{proxy.value:.3f}"
        pct     = proxy.pct

    return html.Div([
        _bar_row("AVG", pct, val_str, AVG_COLOR, AVG_BG, bold=True),
    ], style={
        "marginBottom":  "6px",
        "paddingBottom": "6px",
        "borderBottom":  "1px solid #d0d8e0",
    })


def group_tab_content(group: SensorGroup) -> html.Div:
    color = STATUS_COLORS[group.status]
    return html.Div([
        html.Div([
            html.Span(group.name, style={
                "fontWeight": "700", "fontSize": "13px", "marginRight": "16px"
            }),
            html.Span(group.summary, style={
                "fontSize": "11px", "color": "#888", "fontFamily": "monospace"
            }),
        ], style={
            "padding":      "8px 12px",
            "marginBottom": "6px",
            "borderBottom": f"2px solid {color}",
        }),
        average_bar(group),
        html.Div([sensor_bar(s, group) for s in group.sensors]),
    ])


def build_tabs() -> dbc.Tabs:
    if not _groups:
        return html.Div("No groups loaded. Check utils/pressure_groups.txt",
                        className="text-muted p-4")
    return dbc.Tabs([
        dbc.Tab(group_tab_content(g), label=g.name, tab_id=f"tab-{g.id}")
        for g in _groups
    ], id="pm-tabs", active_tab=f"tab-{_groups[0].id}")


# ── LAYOUT ────────────────────────────────────────────────────────────────
layout = dbc.Container([
    dcc.Interval(id="pm-interval", interval=1000, n_intervals=0),
    dbc.Row([
        dbc.Col(html.H4("Pressure Monitor", className="text-primary mb-0"), width="auto"),
        dbc.Col([
            html.Small(id="pm-timestamp", className="text-muted me-3"),
            dbc.Button("↺ Reload Config", id="pm-reload-btn",
                       size="sm", color="secondary", outline=True),
            html.Span(id="pm-reload-msg", className="ms-2 small text-muted"),
        ], className="d-flex align-items-center", width="auto"),
    ], className="mb-3 mt-3 justify-content-between"),
    html.Div(id="pm-tabs-container", children=build_tabs()),
], fluid=True, style={"backgroundColor": "#f8f9fa", "minHeight": "100vh"})


# ── CALLBACKS ─────────────────────────────────────────────────────────────

@callback(
    Output("pm-tabs-container", "children"),
    Output("pm-timestamp",      "children"),
    Input("pm-interval",        "n_intervals"),
)
def cb_live_update(n):
    for group in _groups:
        group.read_all()
    return build_tabs(), f"Updated: {datetime.now().strftime('%H:%M:%S')}"


@callback(
    Output("pm-tabs-container", "children", allow_duplicate=True),
    Output("pm-reload-msg",     "children"),
    Input("pm-reload-btn",      "n_clicks"),
    prevent_initial_call=True,
)
def cb_reload(n):
    global _groups
    _groups = parse_config(CONFIG_FILE)
    for g in _groups:
        g.activate_all()
    return build_tabs(), f"Loaded {len(_groups)} groups at {datetime.now().strftime('%H:%M:%S')}"