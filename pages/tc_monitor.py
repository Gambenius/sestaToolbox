import dash
from dash import html, dcc, callback, Input, Output, State, ALL
import dash_bootstrap_components as dbc
from datetime import datetime

from utils.tc_logic import parse_config, TCGroup, Thermocouple

dash.register_page(
    __name__,
    path="/thermo",
    name="TC Monitor",
    title="TC Monitor"
)

CONFIG_FILE = "utils/lists/tc_groups.txt"

_groups = parse_config(CONFIG_FILE)
for g in _groups:
    g.activate_all()

# ── STYLES ────────────────────────────────────────────────────────────────
STATUS_COLORS = {
    "ok":       "#27ae60",
    "warn":     "#e67e22",
    "alarm":    "#e74c3c",
    "frozen":   "#8e44ad",
    "nodata":   "#aab0b8",
    "disabled": "#7f8c8d", # Grey for excluded
}
STATUS_BG = {
    "ok":       "#27ae60",
    "warn":     "#e67e22",
    "alarm":    "#e74c3c",
    "frozen":   "#8e44ad",
    "nodata":   "#d0d4d9",
    "disabled": "#bdc3c7", # Light grey background
}
STATUS_TEXT = {
    "ok":       "#ffffff",
    "warn":     "#ffffff",
    "alarm":    "#ffffff",
    "frozen":   "#ffffff",
    "nodata":   "#666c74",
    "disabled": "#ffffff",
}

AVG_COLOR = "#2471a3"
AVG_BG    = "#2471a3"
AVG_TEXT  = "#ffffff"

PAGE_BG   = "#f0f2f5"
PANEL_BG  = "#ffffff"
BORDER    = "#dde1e7"
HEADER_BG = "#ffffff"


# ── SENSOR CHIP ───────────────────────────────────────────────────

def sensor_chip(sensor: Thermocouple, group: TCGroup) -> html.Button:
    status  = group.sensor_status(sensor)
    bg      = STATUS_BG[status]
    txt     = STATUS_TEXT[status]
    val_str = f"{sensor.value:.2f}" if sensor.value is not None else "—"
    
    # Base style for the chip
    chip_style = {
        "backgroundColor": bg,
        "borderRadius":    "3px",
        "padding":         "5px 6px",
        "border":          "2px solid transparent", # Default border
        "textAlign":       "left",
        "cursor":          "pointer",
        "transition":      "all 0.1s ease",
        "position":        "relative",
        "overflow":        "hidden"
    }

    # Add graphic "Excluded" effects
    if sensor.disabled:
        chip_style.update({
            "opacity": "0.5",
            "border": "2px dashed #000000", # Black dashed border
            # Diagonal stripe overlay
            "backgroundImage": "linear-gradient(45deg, rgba(0,0,0,0.05) 25%, transparent 25%, transparent 50%, rgba(0,0,0,0.05) 50%, rgba(0,0,0,0.05) 75%, transparent 75%, transparent)",
            "backgroundSize": "10px 10px"
        })

    return html.Button([
        html.Div(sensor.tag, style={
            "fontSize":      "9px",
            "fontFamily":    "Inter, sans-serif",
            "color":         "rgba(0,0,0,0.6)" if sensor.disabled else "rgba(255,255,255,0.75)",
            "fontWeight":    "600",
            "lineHeight":    "1",
        }),
        html.Div(val_str, style={
            "fontSize":   "12px",
            "fontFamily": "Inter, sans-serif",
            "fontWeight": "700",
            "color":      "#000" if sensor.disabled else txt,
            "lineHeight": "1",
            "marginTop":  "3px",
        }),
    ], 
    id={'type': 'sensor-btn', 'tag': sensor.tag},
    n_clicks=None, # Ensure this is None
    style=chip_style)


def avg_chip(group: TCGroup) -> html.Div:
    proxy   = group.average_sensor()
    val_str = f"{proxy.value:.2f}" if proxy is not None else "—"
    return html.Div([
        html.Div("MED", style={ # Changed from AVG to MED
            "fontSize":      "9px",
            "fontFamily":    "Inter, sans-serif",
            "color":         "rgba(255,255,255,0.75)",
            "fontWeight":    "700",
            "letterSpacing": "0.05em",
            "lineHeight":    "1",
        }),
        html.Div(val_str, style={
            "fontSize":   "12px",
            "fontFamily": "Inter, sans-serif",
            "fontWeight": "700",
            "color":      AVG_TEXT,
            "lineHeight": "1",
            "marginTop":  "3px",
        }),
    ], style={
        "backgroundColor": AVG_BG,
        "borderRadius":    "3px",
        "padding":         "5px 6px",
        "minWidth":        "0",
    })


# ── GROUP PANEL ───────────────────────────────────────────────────────────

def _status_dot(status: str) -> html.Span:
    return html.Span(style={
        "display":         "inline-block",
        "width":           "7px",
        "height":          "7px",
        "borderRadius":    "50%",
        "backgroundColor": STATUS_COLORS.get(status, "#aaa"),
        "marginRight":     "6px",
        "flexShrink":      "0",
    })


def group_panel(group: TCGroup) -> html.Div:
    status       = group.status
    border_color = STATUS_COLORS.get(status, "#aaa")

    header = html.Div([
        html.Div([
            _status_dot(status),
            html.Span(group.name, style={
                "fontSize":      "11px",
                "fontWeight":    "700",
                "color":         "#1a1a2e",
                "letterSpacing": "0.03em",
                "fontFamily":    "Inter, sans-serif",
            }),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Span(group.summary, style={
            "fontSize":   "12px",
            "color":      "#999",
            "fontFamily": "Inter, sans-serif",
        }),
    ], style={
        "display":         "flex",
        "justifyContent":  "space-between",
        "alignItems":      "center",
        "padding":         "5px 8px",
        "borderBottom":    f"1px solid {BORDER}",
        "marginBottom":    "5px",
        "backgroundColor": "#fafbfc",
    })

    chips = [avg_chip(group)] + [sensor_chip(s, group) for s in group.sensors]

    grid = html.Div(chips, style={
        "display":             "grid",
        "gridTemplateColumns": "repeat(4, 1fr)",   # ← fixed cols, adjust to taste
        "gap":                 "4px",
        "padding":             "0 6px 6px 6px",
    })

    return html.Div([header, grid], style={
        "backgroundColor": PANEL_BG,
        "border":          f"1px solid {BORDER}",
        "borderTop":       f"2px solid {border_color}",
        "borderRadius":    "4px",
        "overflow":        "hidden",
        "boxShadow":       "0 1px 3px rgba(0,0,0,0.06)",
        "breakInside":     "avoid", 
        "marginBottom":    "8px", 
    })


# ── LEGEND ────────────────────────────────────────────────────────────────

def legend() -> html.Div:
    items = [
        ("ok",       "OK"),
        ("warn",     "WARN"),
        ("alarm",    "ALARM"),
        ("frozen",   "FROZEN"),
        ("disabled", "EXCLUDED"),
    ]
    return html.Div([
        html.Div([
            html.Span(style={
                "display":         "inline-block",
                "width":           "7px",
                "height":          "7px",
                "borderRadius":    "50%",
                "backgroundColor": STATUS_COLORS[s],
                "marginRight":     "4px",
            }),
            html.Span(label, style={
                "fontSize":   "9px",
                "color":      "#666",
                "fontFamily": "Inter, sans-serif",
            }),
        ], style={"display": "flex", "alignItems": "center", "marginRight": "10px"})
        for s, label in items
    ], style={"display": "flex", "alignItems": "center"})


# ── LAYOUT ────────────────────────────────────────────────────────────────

layout = html.Div([
    html.Link(
        rel="stylesheet",
        href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap"
    ),
    dcc.Interval(id="tc-interval", interval=1000, n_intervals=0),
    dcc.Store(id="tc-col-width", data=4),
    # Top bar
    html.Div([
        html.Div([
            html.Span("TC MONITOR", style={
                "fontSize":      "13px",
                "fontWeight":    "800",
                "letterSpacing": "0.12em",
                "color":         "#1a1a2e",
                "fontFamily":    "Inter, sans-serif",
            }),
        ]),
        html.Div([
            legend(),
            html.Span(id="tc-timestamp", style={
                "fontSize":    "10px",
                "color":       "#aaa",
                "fontFamily":  "Inter, sans-serif",
                "marginLeft":  "16px",
                "marginRight": "12px",
            }),
            html.Div([
                dbc.InputGroup([
                    dbc.Button("−", id="tc-width-minus", color="secondary", outline=True, size="sm"),
                    dbc.Input(id="tc-col-width-input", type="number", value=4, min=1, step=1, debounce=True,
                            size="sm", style={"width": "52px", "textAlign": "center"}),
                    dbc.Button("+", id="tc-width-plus", color="secondary", outline=True, size="sm"),
                ], size="sm", style={"marginRight": "10px"}),
            ], style={"display": "flex", "alignItems": "center", "marginRight": "10px"}),
            dbc.Button("↺ Reload Config", id="tc-reload-btn",
                       size="sm", color="secondary", outline=True,
                       style={"fontSize": "10px", "padding": "2px 8px"}),
            html.Span(id="tc-reload-msg", style={
                "fontSize":   "9px",
                "color":      "#aaa",
                "fontFamily": "Inter, sans-serif",
                "marginLeft": "8px",
            }),
        ], style={"display": "flex", "alignItems": "center"}),
    ], style={
        "display":         "flex",
        "justifyContent":  "space-between",
        "alignItems":      "center",
        "padding":         "8px 12px",
        "borderBottom":    f"1px solid {BORDER}",
        "marginBottom":    "8px",
        "backgroundColor": HEADER_BG,
        "boxShadow":       "0 1px 3px rgba(0,0,0,0.06)",
    }),

    html.Div(id="tc-grid-container", children=[]),

], style={
    "backgroundColor": PAGE_BG,
    "minHeight":       "100vh",
    "color":           "#1a1a2e",
})


# ── CALLBACKS ─────────────────────────────────────────────────────────────

@callback(
    Output("tc-grid-container", "children"),
    Output("tc-timestamp",      "children"),
    Input("tc-interval",        "n_intervals"),
    Input("tc-col-width",       "data"),
)
def cb_live_update(n, col_count):
    for group in _groups:
        group.read_all()

    panels = [group_panel(g) for g in _groups]
    grid = html.Div(panels, style={
        "columnCount": str(col_count or 4),
        "columnGap":   "8px",
        "padding":     "0 8px 8px 8px",
    })
    return grid, datetime.now().strftime("%H:%M:%S")


@callback(
    Output("tc-reload-msg", "children"),
    Input("tc-reload-btn",  "n_clicks"),
    prevent_initial_call=True,
)
def cb_reload(n):
    global _groups
    _groups = parse_config(CONFIG_FILE)
    for g in _groups:
        g.activate_all()
    return f"loaded {len(_groups)} groups · {datetime.now().strftime('%H:%M:%S')}"

@callback(
    Output("tc-grid-container", "children", allow_duplicate=True),
    Input({'type': 'sensor-btn', 'tag': ALL}, 'n_clicks'),
    State("tc-col-width", "data"),
    prevent_initial_call=True,
)
def cb_toggle_sensor(n_clicks, col_count):
    ctx = dash.callback_context
    if not ctx.triggered or ctx.triggered[0]['value'] is None:
        return dash.no_update

    triggered_id = dash.ctx.triggered_id
    tag_to_toggle = triggered_id['tag']

    for g in _groups:
        for s in g.sensors:
            if s.tag == tag_to_toggle:
                s.disabled = not s.disabled
                break

    panels = [group_panel(g) for g in _groups]
    return html.Div(panels, style={
        "columnCount": str(col_count or 4),
        "columnGap":   "8px",
        "padding":     "0 8px 8px 8px",
    })



# --------- change column width callback
@callback(
    Output("tc-col-width",       "data"),
    Output("tc-col-width-input", "value"),
    Input("tc-width-minus",      "n_clicks"),
    Input("tc-width-plus",       "n_clicks"),
    Input("tc-col-width-input",  "value"),
    State("tc-col-width",        "data"),
    prevent_initial_call=True,
)
def cb_col_width(minus, plus, input_val, current):
    triggered = dash.ctx.triggered_id
    if triggered == "tc-width-minus":
        val = max(1, current - 1)
    elif triggered == "tc-width-plus":
        val = current + 1
    else:
        val = int(input_val) if input_val and int(input_val) >= 1 else current
    return val, val