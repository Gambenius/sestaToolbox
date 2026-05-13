import asyncio
import threading
import os
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, date
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import dash
from dash import html, dcc, callback, Input, Output, State, no_update, Patch
import dash_bootstrap_components as dbc
import dash_daq as daq
import dash_ag_grid as dag

from asyncua import Client
from asyncua import ua
from dotenv import load_dotenv
load_dotenv()

dash.register_page(
    __name__, 
    path="/quickt", 
    name="Quicktrends",  # This is how it appears in links/registry
    title="Quicktrends"  # This is what appears in the browser tab
)
# ── CONSTANTS ──────────────────────────────────────────────────────────────
AXIS_PRESETS = {
    "Custom":  {"name": "",                  "rangeMIN": "",    "rangeMAX": ""},
    "bar H":   {"name": "Pressione [bar]",   "rangeMIN": "0",   "rangeMAX": "200"},
    "bar L":   {"name": "Pressione [bar]",   "rangeMIN": "0",   "rangeMAX": "10"},
    "mbar":    {"name": "Pressione [mbar]",  "rangeMIN": "0",   "rangeMAX": "1000"},
    "kgs H":   {"name": "Portata [kg/s]",    "rangeMIN": "0",   "rangeMAX": "30"},
    "kgs L":   {"name": "Portata [kg/s]",    "rangeMIN": "0",   "rangeMAX": "1"},
    "gs H":    {"name": "Portata [g/s]",     "rangeMIN": "0",   "rangeMAX": "1000"},
    "CH":      {"name": "Temperatura [°C]",  "rangeMIN": "0",   "rangeMAX": "2000"},
    "CL":      {"name": "temperatura [°C]",  "rangeMIN": "0",   "rangeMAX": "100"},
    "Amp":     {"name": "corrente [A]",      "rangeMIN": "0",   "rangeMAX": "200"},
    "Volt":    {"name": "Tensione [V]",      "rangeMIN": "0",   "rangeMAX": "400"},
}
AXIS_DROPDOWN_OPTIONS = list(AXIS_PRESETS.keys()) + ["1", "2", "3", "4", "5"]

OPC_URL        = "opc.tcp://10.33.126.101:51800"
OPC_NS         = 3
TAGS_CACHE_FILE = "utils/tags_cache.txt"
PRESETS_FILE   = "utils/quicktrends_presets.txt"
WINDOW_SECONDS = 1200   # 20 min rolling window
MAX_POINTS_PER_TAG = 10_000

# ── SHARED STATE ───────────────────────────────────────────────────────────
# tag_data: tag -> deque of (datetime, float)
tag_data      = defaultdict(lambda: deque(maxlen=MAX_POINTS_PER_TAG))
active_tags   = set()
state_lock    = threading.Lock()
opc_connected = False
# NEW — load cache eagerly at import time
cached_tags_list = []
cached_tags_desc = {}   # tag -> description string
node_to_tag = {}

def _load_tags_cache():
    global cached_tags_list, cached_tags_desc
    if not os.path.exists(TAGS_CACHE_FILE):
        print("[CACHE] WARNING: No tags_cache.txt found — tag dropdown will be empty")
        return
    tags, descs = [], {}
    with open(TAGS_CACHE_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if ";" in line:
                tag, desc = line.split(";", 1)
                tag, desc = tag.strip(), desc.strip()
            else:
                tag, desc = line.strip(), ""
            if tag:
                tags.append(tag)
                descs[tag] = desc
    cached_tags_list = tags
    cached_tags_desc = descs
    print(f"[CACHE] Loaded {len(tags)} tags")

_load_tags_cache()

# ── OPC UA SUBSCRIPTION HANDLER ───────────────────────────────────────────
class TagSubHandler:
    def datachange_notification(self, node, val, data):
        tag_name = node_to_tag.get(node.nodeid.Identifier)
        if tag_name is not None:
            ts = datetime.now()   # always local clock
            try:
                fval = float(val)
            except (TypeError, ValueError):
                return
            with state_lock:
                tag_data[tag_name].append((ts, fval))

# ── OPC UA BACKGROUND THREAD ──────────────────────────────────────────────
async def subscription_watcher(client, subscription, subscribed_tags):
    while True:
        with state_lock:
            current = set(active_tags)

        # Print live values
        if current:
            # print("[OPC] Current values:")
            for tag in sorted(current):
                dq = tag_data.get(tag, deque())
                if dq:
                    ts, val = dq[-1]
                    # print(f"  {tag}: {val:.4f} @ {ts.strftime('%H:%M:%S')}")
                else:
                    print(f"  {tag}: no data yet")

        # Subscribe new tags
        new_tags = current - subscribed_tags
        if new_tags:
            print(f"[OPC] Subscribing to {len(new_tags)} new tags...")
            nodes = []
            for tag in new_tags:
                try:
                    node = client.get_node(f"ns={OPC_NS};s={tag}.Value")
                    nodes.append((tag, node))
                except Exception as e:
                    print(f"[OPC] Node lookup failed for {tag}: {e}")

            BATCH = 50
            for i in range(0, len(nodes), BATCH):
                batch = nodes[i:i + BATCH]
                try:
                    handles = await subscription.subscribe_data_change(
                        [n for _, n in batch],
                        sampling_interval=1000,
                    )
                    for (tag, node), _ in zip(batch, handles):
                        node_to_tag[node.nodeid.Identifier] = tag
                        subscribed_tags.add(tag)
                    print(f"[OPC] Subscribed batch {i // BATCH + 1} ({len(batch)} tags)")
                except Exception as e:
                    print(f"[OPC] Subscription batch error: {e}")
                await asyncio.sleep(0.1)

        await asyncio.sleep(2)

async def heartbeat(subscribed_tags):
    """Stamp all active tags every second so static values still plot."""
    while True:
        now = datetime.now()
        with state_lock:
            for tag in subscribed_tags:
                dq = tag_data.get(tag)
                if dq:
                    _, last_val = dq[-1]
                    tag_data[tag].append((now, last_val))
        await asyncio.sleep(1)

async def opc_loop():
    global opc_connected, cached_tags_list

    # Load tag list from cache before doing anything else
    # if os.path.exists(TAGS_CACHE_FILE):
    #     with open(TAGS_CACHE_FILE) as f:
    #         raw_lines = [l.strip() for l in f if l.strip()]
    #     tags, descs = [], {}
    #     for line in raw_lines:
    #         if ";" in line:
    #             tag, desc = line.split(";", 1)
    #             tag = tag.strip()cb_filter_tags 
    #             desc = desc.strip()
    #         else:
    #             tag = line.strip()
    #             desc = ""
    #         if tag:
    #             tags.append(tag)
    #             descs[tag] = desc
    #     with state_lock:
    #         cached_tags_list = tags
    #         cached_tags_desc = descs
    #     print(f"[OPC] Loaded {len(cached_tags_list)} tags from cache")
    # else:
    #     print("[OPC] WARNING: No tags_cache.txt found — tag dropdown will be empty")

    subscribed_tags = set()

    while True:
        client = Client(OPC_URL)
        client.set_user(os.getenv("OPC_USER", "Administrator"))
        client.set_password(os.getenv("OPC_PASSWORD", ""))
        client.session_timeout = 60_000

        try:
            await client.connect()
            print("[OPC] Connected")
            opc_connected = True
            subscribed_tags.clear()
            node_to_tag.clear()

            handler      = TagSubHandler()
            subscription = await client.create_subscription(1000, handler)

            await asyncio.gather(
                subscription_watcher(client, subscription, subscribed_tags),
                heartbeat(subscribed_tags),
            )

        except Exception as e:
            print(f"[OPC] Connection error: {e}")
            opc_connected = False
        finally:
            try:
                await client.disconnect()
                print("[OPC] Disconnected cleanly")
            except Exception:
                pass

        await asyncio.sleep(5)

def start_opc_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(opc_loop())

# Only start in the main Werkzeug process (avoids double-start in debug mode)
if os.environ.get("WERKZEUG_RUN_MAIN", "true") == "true":
    if not any(t.name == "OPC_Worker" for t in threading.enumerate()):
        threading.Thread(target=start_opc_loop, name="OPC_Worker", daemon=True).start()

# ── PRESET UTILITIES ──────────────────────────────────────────────────────
def save_preset_to_file(title, tags):
    with open(PRESETS_FILE, "a") as f:
        f.write(f"\n")
        f.write(f"{title.upper()}\n{{\n")
        for tag in tags:
            f.write(f"{tag}\n")
        f.write("}\n")

def load_presets_from_file():
    if not os.path.exists(PRESETS_FILE):
        return {}
    presets = {}
    try:
        with open(PRESETS_FILE, "r") as f:
            lines = f.readlines()
        current_title, current_tags, in_block = None, [], False
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                in_block = True
            elif line.startswith("}"):
                if current_title:
                    presets[current_title] = current_tags
                current_tags, in_block = [], False
            elif in_block:
                current_tags.append(line)
            else:
                current_title = line
    except Exception as e:
        print(f"Error loading presets: {e}")
    return presets

# ── DATA HELPERS ──────────────────────────────────────────────────────────
def _ax_key(aid_int):
    return "yaxis" if aid_int == 1 else f"yaxis{aid_int}"

def get_tag_dataframe(selected_tags=None):
    """
    Returns a DataFrame [timestamp, tag, value] for the last WINDOW_SECONDS.
    Optionally filtered to selected_tags.
    """
    cutoff = datetime.now() - timedelta(seconds=WINDOW_SECONDS)
    rows = []
    with state_lock:
        tags_to_scan = selected_tags if selected_tags else list(tag_data.keys())
        for tag in tags_to_scan:
            dq = tag_data.get(tag, deque())
            for ts, val in dq:
                if ts >= cutoff:
                    rows.append({"timestamp": ts, "tag": tag, "value": val})

    if not rows:
        return pd.DataFrame(columns=["timestamp", "tag", "value"])

    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df

def _get_data_for_tags(selected_tags, start_dt, n_pts=1000):
    """
    Returns (time_axis, data_dict) where time_axis is a list of datetimes
    and data_dict maps tag -> list of float values aligned to time_axis.
    """
    df = get_tag_dataframe(selected_tags)

    if df.empty:
        # No data yet — return empty arrays
        return [], {tag: [] for tag in selected_tags}

    df = df[df["timestamp"] >= start_dt]

    if df.empty:
        return [], {tag: [] for tag in selected_tags}

    # Build a unified time axis from all timestamps, downsampled to n_pts
    all_times = sorted(df["timestamp"].unique())
    if len(all_times) > n_pts:
        step = max(1, len(all_times) // n_pts)
        all_times = all_times[::step]

    data_dict = {tag: [] for tag in selected_tags}
    for tag in selected_tags:
        tag_df = df[df["tag"] == tag].set_index("timestamp")["value"]
        tag_df = tag_df[~tag_df.index.duplicated(keep="last")].sort_index()
        for t in all_times:
            past = tag_df[tag_df.index <= t]
            data_dict[tag].append(float(past.iloc[-1]) if not past.empty else None)

    return all_times, data_dict

def _build_figure(current_rows, time_axis, data_dict, ax_map, y_store, font_size=12):
    fig = go.Figure()
    
    # Base linewidth calculation based on font size
    base_linewidth = 1.5 * (1 + (font_size - 12) * 0.10)
    
    used_ids_int  = sorted(set(int(r["axis_id"]) for r in current_rows))
    num_subplots  = len(used_ids_int)
    spacing       = 0.08
    p_height      = (1.0 - spacing * max(1, num_subplots - 1)) / max(1, num_subplots)

    # 1. Add Traces
    for row in current_rows:
        aid  = str(row["axis_id"])
        tag  = row["tag"]
        ydata = data_dict.get(tag, [])
        
        # Selection highlighting: thicker line if row is selected
        linewidth = base_linewidth * 2.5 if row.get("_selected") else base_linewidth
        
        fig.add_trace(go.Scattergl(
            x=time_axis, y=ydata,
            yaxis=f"y{aid}" if aid != "1" else "y",      
            mode="lines",                 
            name=row["name"], # Now uses the editable name for Plotly internals
            meta=row["tag"],  # Keeps the hardware tag as the permanent ID
            line=dict(color=row["color"], width=linewidth),
            showlegend=False,
            connectgaps=True,
            # Hover now shows the friendly name instead of just the tag
            hovertemplate=f"<b>{row['name']}</b>: %{{y:.3f}}<extra></extra>"
        ))

    # 2. Layout Base Configuration
    layout = {
        "template":      "plotly_white",
        "font":          {"size": font_size},
        "hovermode":     "x unified",
        "hoverdistance": -1,
        "autosize":      True,
        "margin":        dict(t=30, b=50, l=100, r=200),
        "uirevision":    "static",
        "showlegend":    False,
        "annotations":   [],
        "xaxis": {
            "title":      "Orario",
            "tickformat": "%H:%M:%S",
            "gridcolor":  "#eee",
            "showspikes": True,
        }
    }

    # 3. Subplot and Annotation logic
    for i, aid_int in enumerate(used_ids_int):
        aid     = str(aid_int)
        ak      = _ax_key(aid_int)
        ref_key = "y" if aid == "1" else f"y{aid}"
        
        start_y = max(0.0, 1.0 - (i + 1) * p_height - i * spacing)
        end_y   = min(1.0, start_y + p_height)
        mid_y   = start_y + p_height / 2

        # Add annotations for the "homemade legend" on the right
        subplot_rows = [r for r in current_rows if int(r["axis_id"]) == aid_int]
        for j, row in enumerate(subplot_rows):
            y_off = (len(subplot_rows) / 2 - j) * 0.035
            
            # This annotation now correctly displays the 'name' field
            layout["annotations"].append(dict(
                x=1.02, y=mid_y + y_off,
                xref="paper", yref="paper",
                text=f"<b>{row['name']}</b>", # Display name follows your edit
                showarrow=False,
                font=dict(color=row["color"], size=font_size),
                xanchor="left"
            ))

        # Axis Configuration (Limits and Labels)
        conf   = ax_map.get(aid, {})
        stored = y_store.get(ak) if y_store else None
        
        if isinstance(stored, list) and len(stored) == 2 and None not in stored:
            y_range, autorange = stored, False
        elif stored == "auto":
            y_range, autorange = None, True
        else:
            try:
                y_range, autorange = [float(conf["rangeMIN"]), float(conf["rangeMAX"])], False
            except (ValueError, TypeError, KeyError):
                y_range, autorange = None, True

        ax_def = {
            "domain":         [start_y, end_y],
            "title":          {"text": conf.get("name", f"Asse {aid}"), "font": {"size": font_size}},
            "tickfont":       {"size": font_size},
            "showgrid":       True,
            "showticklabels": True,
            "matches":        "x",
            "autorange":      autorange,
            "nticks":         5,
        }
        if y_range:
            ax_def["range"] = y_range
            
        layout[ak] = ax_def

        if i == num_subplots - 1:
            layout["xaxis"]["anchor"] = ref_key

    fig.update_layout(layout)
    fig.update_traces(xaxis="x")
    return fig

def chunks_in_order(chunks, haystack):
    pos = 0
    for chunk in chunks:
        idx = haystack.find(chunk, pos)
        if idx == -1:
            return False
        pos = idx + len(chunk)
    return True

def parse_mmss(s):
    try:
        parts = str(s).strip().split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(parts[0])
    except Exception:
        return WINDOW_SECONDS

# ── LAYOUT ────────────────────────────────────────────────────────────────
layout = dbc.Container([
    dcc.Store(id="qt-zoom-store",             data={"start": 0, "end": None}),
    dcc.Download(id="qt-download-csv"),
    dcc.Store(id="qt-selected-row-store",     data=None),
    dcc.Store(id="qt-color-edit-store",       data=None),
    dcc.Store(id="qt-selected-tag-store"),
    dcc.Store(id="qt-axis-config",            data={"1": {"min": None, "max": None}}),
    dcc.Store(id="qt-info-table-store"),
    dcc.Store(id="qt-x-range-store"),
    dcc.Store(id="qt-y-ranges-store"),
    dcc.Store(id="qt-redraw-store"),
    dcc.Interval(id="qt-opc-status-interval", interval=5000,  n_intervals=0),
    dcc.Interval(id="qt-live-interval",       interval=2000,  n_intervals=0),  # live redraw
    dcc.Store(id="qt-opc-status",             data=False),

    # Axis modal
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Configurazione Assi")),
        dbc.ModalBody([
            dag.AgGrid(
                id="qt-axis-config-grid",
                columnDefs=[
                    {"headerName": "ID",       "field": "id",       "width": 60,  "editable": False},
                    {"headerName": "Preset",   "field": "preset",   "editable": True, "width": 100,
                     "cellEditor": "agSelectCellEditor",
                     "cellEditorParams": {"values": list(AXIS_PRESETS.keys())}},
                    {"headerName": "Nome",     "field": "name",     "editable": True},
                    {"headerName": "Range Min","field": "rangeMIN", "editable": True, "width": 100},
                    {"headerName": "Range Max","field": "rangeMAX", "editable": True, "width": 100},
                ],
                rowData=[{"id": 1, "name": "Asse 1", "preset": "Custom", "rangeMIN": "", "rangeMAX": ""}],
                dashGridOptions={"singleClickEdit": True, "stopEditingWhenCellsLoseFocus": True}
            ),
            dbc.Button("+ Aggiungi Asse", id="qt-add-axis-row", color="link", size="sm")
        ]),
        dbc.ModalFooter(dbc.Button("Salva e Chiudi", id="qt-close-axis-modal", color="primary"))
    ], id="qt-axis-modal", size="lg"),

    # Color picker modal
    dbc.Modal(id="qt-color-picker-modal", children=[
        dbc.ModalHeader(dbc.ModalTitle("Seleziona Colore")),
        daq.ColorPicker(id="qt-color-input", value=dict(hex="#0000FF")),
        dbc.ModalFooter(dbc.Button("Conferma", id="qt-color-confirm", color="primary"))
    ]),

    # Main row
    dbc.Row([
        # Sidebar
        dbc.Col([
            html.Div([
                html.H4("QuickTrends Monitor", className="text-primary mb-4"),
                html.Div(id="qt-status-msg", className="mb-3"),
                html.Label("Cerca Canale:", className="small fw-bold"),
                dcc.Dropdown(
                    id="qt-tag-dropdown", multi=True,
                    placeholder="Cerca (es. TEMP*507, *acqua*)...",
                    className="mb-4", options=[], searchable=True,
                    maxHeight=500, optionHeight=50,   # increased from 35
                ),
                dbc.Button("Mostra grafico", id="qt-btn-plot", color="primary", className="w-100 mb-3"),
                html.Div(id="qt-plot-status", className="mb-3 small"),
                dcc.Dropdown(id="qt-preset-dropdown", placeholder="Seleziona un Preset...", className="mb-4"),
                dbc.Input(id="qt-new-preset-name", placeholder="Nome nuovo preset...", type="text", className="mb-4"),
                dbc.Button("Salva selezione corrente", id="save-preset-btn", color="primary", className="w-100 mb-3"),
                # dbc.Button("💀 Kill OPC Sessions", id="qt-btn-kill-sessions", color="danger", outline=True, className="w-100 mb-3"),
                # html.Div(id="qt-kill-sessions-msg", className="small"),
            ], style={"padding": "20px", "borderRight": "1px solid #ddd", "minHeight": "90vh"})
        ], id="qt-sidebar-col", width=3),

        # Graph area
        dbc.Col([
            html.Div(
                # dcc.Graph(id="qt-main-graph", style={"height": "100%", "width": "100%"}),
                dcc.Graph(
                    id="qt-main-graph", style={"height": "100%", "width": "100%"},
                    config={"displayModeBar": False},   # optional, removes toolbar flicker
                    figure=go.Figure(),
                ),
                style={
                    "height": "80vh", "minHeight": "300px", "overflow": "hidden",
                    "resize": "vertical", "borderBottom": "2px solid #ddd",
                    "paddingBottom": "5px", "border": "1px solid #4C78A8"
                }
            ),
            dbc.Row([
                dbc.Col(dbc.Button("⚙️ CONFIGURA ASSI", id="qt-btn-axis-modal",
                                color="secondary", outline=True, size="sm"), width="auto"),
                dbc.Col(html.Small("Usa la colonna 'Asse' per raggruppare i canali",
                                className="text-muted"), className="text-end me-auto"),
                dbc.Col([
                    dbc.InputGroup([
                        dbc.InputGroupText("⏱"),
                        dbc.Input(id="qt-window-input", type="text", value="5:00",
                                debounce=True, size="sm", style={"width": "70px"}),
                    ], size="sm"),
                ], width="auto"),
                dbc.Col([
                    dbc.InputGroup([
                        dbc.Button("−", id="qt-btn-fontsize-down", color="secondary", outline=True, size="sm"),
                        dbc.Input(id="qt-fontsize-input", type="text", value="12", debounce=True,
                                size="sm", style={"width": "52px", "textAlign": "center"}),
                        dbc.Button("+", id="qt-btn-fontsize-up", color="secondary", outline=True, size="sm"),
                    ], size="sm"),
                ], width="auto"),
                dbc.Col(dbc.Button("🔍 Autoscale Y", id="qt-btn-autoscale",
                                color="secondary", outline=True, size="sm"), width="auto"),
                dbc.Col(dbc.Button("📄 Salva come PDF", id="qt-btn-export-pdf",
                                color="secondary", outline=True, size="sm"), width="auto"),
                dcc.Download(id="qt-download-pdf"),
            ], className="my-2 align-items-center g-2"),

            dag.AgGrid(
                id="qt-info-table",
                dangerously_allow_code=True,
                columnDefs=[
                    {"headerName": "🎨   ", "field": "color", "width": 60,
                     "resizable": False, "suppressSizeToFit": True},
                    {"headerName": "Tag",  "field": "tag", "hide": True},
                    {
                        "headerName": "Name", 
                        "field": "name", 
                        "singleClickEdit": True,
                        "resizable": True, 
                        "editable": True, 
                        "flex": 1,
                        "cellStyle": {
                            "styleConditions": [
                                {
                                    "condition": "params.data._selected === true",
                                    "style": {"fontWeight": "bold", "color": "#000"} 
                                },
                                {
                                    "condition": "params.data._selected === false || params.data._selected === undefined",
                                    "style": {"fontWeight": "normal"}
                                }
                            ]
                        }
                    },
                    {
                        "headerName": "Description", 
                        "field": "desc", 
                        "flex": 2,
                        "cellStyle": {
                            "styleConditions": [
                                {"condition": "params.data._selected === true", "style": {"fontWeight": "bold"}},
                                {"condition": "params.data._selected !== true", "style": {"fontWeight": "normal"}}
                            ]
                        }
                    },
                    {"headerName": "Cursore", "field": "cursor_val", "width": 100, "resizable": True,
                        "cellStyle": {"defaultStyle": {"textAlign": "right"}}
                    },
                    {"headerName": "Attuale", "field": "cur_val", "width": 100, "resizable": True,
                        "cellStyle": {"defaultStyle": {"textAlign": "right"}}
                    },
                    {"headerName": "Asse", "field": "axis_sel", "singleClickEdit": True,
                        "editable": True, "cellEditor": "agSelectCellEditor",
                        "cellEditorParams": {"values": AXIS_DROPDOWN_OPTIONS}, "width": 100
                     },
                    {"headerName": "Rimuovi", "field": "delete-row", "width": 90,
                        "suppressSizeToFit": False, "resizable": False,
                        "cellStyle": {"cursor": "pointer", "textAlign": "center",
                                    "color": "red", "fontWeight": "bold"}
                    },
                ],
                defaultColDef={"resizable": True, "sortable": False, "filter": False},
                rowData=[],
                dashGridOptions={"rowClassRules": {"selected-row": "params.data.tag === selectedTag"},
                                "getRowId": "params.data.tag", # Crucial: tells AG Grid how to identify rows
                                "suppressScrollOnNewData": True,
                                "undoRedoCellEditing": True,
                                "domLayout": "autoHeight",
                                }
            )
        ], id="qt-main-col", width=9, style={"position": "relative"})
    ], className="mt-3")
], fluid=True, style={"backgroundColor": "#f8f9fa", "minHeight": "100vh"})

# ── CALLBACKS ─────────────────────────────────────────────────────────────

# ─── 0. OPC STATUS ───────────────────────────────────────────────────────
@callback(
    Output("qt-status-msg", "children"),
    Input("qt-opc-status-interval", "n_intervals"),
)
def cb_opc_status_display(n):
    with state_lock:
        conn   = opc_connected
        n_tags = len(active_tags)
        n_avail = len(cached_tags_list)
    if conn:
        return dbc.Badge(
            f"✓ OPC Connesso  |  Tag attivi: {n_tags}  |  Disponibili: {n_avail}",
            color="success", className="w-100 text-center"
        )
    return dbc.Badge("✗ OPC Disconnesso - Tentativo connessione...",
                     color="danger", className="w-100 text-center")

# ─── 1. TAG DROPDOWN FILTER ──────────────────────────────────────────────
@callback(
    Output("qt-tag-dropdown", "options"),
    Input("qt-tag-dropdown", "search_value"),
    State("qt-tag-dropdown", "value"),
)
def cb_filter_tags(search, selected_values):
    with state_lock:
        pool = list(cached_tags_list)
    descs = cached_tags_desc  # write-once at startup, safe to read freely

    def make_option(tag, search_hint=None):
        desc = descs.get(tag, "")
        # Appending (search_hint) fools Dash's client-side filter into showing
        # all server-returned results even when searching by description
        suffix = f" ({search_hint})" if search_hint else ""
        label = f"{tag}  -  {desc}{suffix}" if desc else f"{tag}{suffix}"
        return {"label": label, "value": tag}

    seen = set()
    final_options = []

    # Always keep currently selected tags visible
    for tag in (selected_values or []):
        if tag in descs or tag in pool:
            final_options.append(make_option(tag))
            seen.add(tag)

# No search: show first 60 tags unfiltered
    if not search or not search.strip() or search.strip() == "*":
        for tag in pool:
            if tag not in seen:
                final_options.append(make_option(tag))
                seen.add(tag)
            if len(final_options) >= 60:
                break
        return final_options

    # Wildcard chunk search across tag + description
    s = search.upper().strip()
    chunks = [c.strip() for c in s.split("*") if c.strip()]

    if not chunks:   # nothing meaningful typed
        return final_options

    for tag in pool:
        desc = descs.get(tag, "")
        haystack = f"{tag} {desc}".upper()
        if chunks_in_order(chunks, haystack):
            if tag not in seen:
                final_options.append(make_option(tag, search_hint=search))
                seen.add(tag)
        if len(final_options) >= 100:
            break

    return final_options

# ─── 2. AXIS CONFIG ROW ADD ──────────────────────────────────────────────
@callback(
    Output("qt-axis-config-grid", "rowData", allow_duplicate=True),
    Input("qt-add-axis-row", "n_clicks"),
    State("qt-axis-config-grid", "rowData"),
    prevent_initial_call=True
)
def add_axis_row(n, rows):
    rows = rows or []
    new_id = max([int(r["id"]) for r in rows]) + 1 if rows else 1
    rows.append({"id": new_id, "name": f"Asse {new_id}",
                 "preset": "Custom", "rangeMIN": "", "rangeMAX": ""})
    return rows

# ─── 3. CLICK ON GRAPH ───────────────────────────────────────────────────
@callback(
    [Output("qt-info-table", "rowData", allow_duplicate=True),
     Output("qt-main-graph", "figure",  allow_duplicate=True)],
    Input("qt-main-graph", "clickData"),
    [State("qt-info-table", "rowData"),
     State("qt-main-graph", "figure")],
    prevent_initial_call=True
)
def update_on_click(clickData, current_table, fig):
    if not clickData or not current_table or not fig:
        return no_update, no_update
    clicked_x = clickData["points"][0]["x"]
    try:
        clicked_dt = datetime.fromisoformat(clicked_x.replace("Z", ""))
    except Exception:
        return no_update, no_update

    for row in current_table:
        tag = row["tag"]
        val = "---"
        for trace in fig["data"]:
            if trace.get("meta") == tag:
                try:
                    x_vals = trace.get("x") or []
                    y_vals = trace.get("y") or []
                    if not x_vals or not y_vals:
                        break
                    # Parse all x to datetime and find nearest
                    dts = [datetime.fromisoformat(str(v).replace("Z", "")) for v in x_vals]
                    diffs = [abs((dt - clicked_dt).total_seconds()) for dt in dts]
                    idx = diffs.index(min(diffs))
                    y_val = y_vals[idx]
                    if y_val is not None:
                        val = f"{y_val:.3f}"
                except Exception:
                    pass
                break
        row["cursor_val"] = val

    cursor_line = {
        "type": "line", "x0": clicked_x, "x1": clicked_x,
        "y0": 0, "y1": 1, "yref": "paper",
        "line": {"color": "red", "width": 2, "dash": "dot"},
    }
    fig["layout"]["shapes"]     = [cursor_line]
    fig["layout"]["uirevision"] = "constant"
    return current_table, fig

# ─── 4. PRESET DROPDOWN REFRESH ──────────────────────────────────────────
@callback(
    Output("qt-preset-dropdown", "options"),
    [Input("save-preset-btn", "n_clicks"),
     Input("qt-opc-status-interval", "n_intervals")],
)
def update_preset_dropdown(n, n_int):
    presets = load_presets_from_file()
    return [{"label": k, "value": k} for k in presets]

# ─── 5. SAVE PRESET ──────────────────────────────────────────────────────
@callback(
    Output("qt-new-preset-name", "value"),
    Input("save-preset-btn", "n_clicks"),
    [State("qt-new-preset-name", "value"),
     State("qt-tag-dropdown",    "value")],
    prevent_initial_call=True
)
def save_current_selection(n_clicks, name, current_selection):
    if not n_clicks or not name or not current_selection:
        return no_update
    save_preset_to_file(name, current_selection)
    return ""

# ─── 6. APPLY PRESET ─────────────────────────────────────────────────────
@callback(
    [Output("qt-tag-dropdown", "value"),
     Output("qt-tag-dropdown", "options", allow_duplicate=True)],
    Input("qt-preset-dropdown", "value"),
    State("qt-tag-dropdown", "options"),
    prevent_initial_call=True
)
def apply_preset(preset_name, current_options):
    if not preset_name:
        return no_update, no_update
    presets = load_presets_from_file()
    selected_tags = presets.get(preset_name, [])
    with state_lock:
        for t in selected_tags:
            active_tags.add(t)
        descs = dict(cached_tags_desc)

    new_options = list(current_options or [])
    existing_ids = {o["value"] for o in new_options}
    for tag in selected_tags:
        if tag not in existing_ids:
            desc = descs.get(tag, "")
            label = f"{tag}  -  {desc}" if desc else tag
            new_options.append({"label": label, "value": tag, "search": f"{tag} {desc}"})
    return selected_tags, new_options

# ─── 7. TRACK X RANGE ────────────────────────────────────────────────────
@callback(
    Output("qt-x-range-store", "data"),
    Input("qt-main-graph", "relayoutData"),
    prevent_initial_call=True
)
def cb_track_x_range(relayout_data):
    if not relayout_data:
        return no_update
    if "xaxis.range[0]" in relayout_data:
        return {
            "x0": str(relayout_data["xaxis.range[0]"]).replace("Z", ""),
            "x1": str(relayout_data["xaxis.range[1]"]).replace("Z", ""),
        }
    if relayout_data.get("xaxis.autorange"):
        return {}
    return no_update

# ─── 8. TRACK Y RANGES ───────────────────────────────────────────────────
@callback(
    Output("qt-y-ranges-store", "data"),
    Input("qt-main-graph", "relayoutData"),
    State("qt-y-ranges-store", "data"),
    prevent_initial_call=True
)
def cb_track_y_ranges(relayout_data, current_store):
    if not relayout_data:
        return no_update
    if not any(k.startswith("yaxis") for k in relayout_data):
        return no_update
    store   = dict(current_store or {})
    updated = False
    for key, val in relayout_data.items():
        if ".range[" in key and key.startswith("yaxis"):
            ak  = key.split(".range[")[0]
            idx = int(key.split("[")[1].rstrip("]"))
            if not isinstance(store.get(ak), list):
                store[ak] = [None, None]
            store[ak][idx] = val
            updated = True
        elif key.startswith("yaxis") and ".autorange" in key:
            ak = key.split(".autorange")[0]
            store[ak] = None
            updated = True
    return store if updated else no_update

# ─── 9. AXIS ASSIGNMENT FROM INFO TABLE ──────────────────────────────────
@callback(
    [Output("qt-info-table",      "rowData",  allow_duplicate=True),
     Output("qt-axis-config-grid","rowData",  allow_duplicate=True),
     Output("qt-y-ranges-store",   "data",     allow_duplicate=True),
     Output("qt-redraw-store",     "data",     allow_duplicate=True)],
    Input("qt-info-table", "cellValueChanged"),
    [State("qt-info-table",       "rowData"),
     State("qt-axis-config-grid", "rowData"),
     State("qt-y-ranges-store",   "data")],
    prevent_initial_call=True
)
def cb_cell_value_changed(cell_changed, info_rows, axis_rows, y_store):
    if not cell_changed or not info_rows:
        return no_update, no_update, no_update, no_update
    
    changed = cell_changed[0]
    col_id  = changed.get("colId")
    row_tag = changed["data"]["tag"]

    if col_id == "name":
        return info_rows, no_update, no_update, {"ts": datetime.now().isoformat(), "reason": "name_edit"}

    if col_id == "axis_sel":
        selected  = changed["value"]
        axis_rows = [dict(r) for r in (axis_rows or [])]
        info_rows = [dict(r) for r in info_rows]
        y_store   = dict(y_store or {})

        if selected.isdigit():
            target_id   = int(selected) + 100
            existing_ids = [int(a["id"]) for a in axis_rows]
            if target_id not in existing_ids:
                axis_rows.append({"id": target_id, "preset": "Custom",
                                  "name": f"Cust. {selected}", "rangeMIN": "", "rangeMAX": ""})
            y_store[_ax_key(target_id)] = None
        else:
            preset = AXIS_PRESETS.get(selected, {})
            existing_axis = next((a for a in axis_rows if a.get("preset") == selected), None)
            if existing_axis:
                target_id = int(existing_axis["id"])
            else:
                preset_ids = [int(a["id"]) for a in axis_rows if int(a["id"]) < 100]
                target_id  = max(preset_ids) + 1 if preset_ids else 1
                axis_rows.append({"id": target_id, "preset": selected,
                                  "name": preset.get("name", ""),
                                  "rangeMIN": preset.get("rangeMIN", ""),
                                  "rangeMAX": preset.get("rangeMAX", "")})
            ak = _ax_key(target_id)
            try:
                y_store[ak] = [float(preset["rangeMIN"]), float(preset["rangeMAX"])]
            except (ValueError, TypeError, KeyError):
                y_store[ak] = None

        for row in info_rows:
            if row["tag"] == row_tag:
                row["axis_id"]  = target_id
                row["axis_sel"] = selected
                break

        axis_rows = sorted(axis_rows, key=lambda x: int(x["id"]))
        return info_rows, axis_rows, y_store, {"ts": datetime.now().isoformat(), "reason": "axis_sel"}

    return no_update, no_update, no_update, no_update

# ─── 10. LIVE REFRESH TRIGGER ────────────────────────────────────────────
@callback(
    Output("qt-redraw-store", "data", allow_duplicate=True),
    Input("qt-live-interval", "n_intervals"),
    State("qt-info-table", "rowData"),
    prevent_initial_call=True
)
def cb_live_refresh(n, info_rows):
    if not info_rows:
        return no_update
    return {"ts": datetime.now().isoformat(), "reason": "live"}

# ─── 11. MAIN RENDER ─────────────────────────────────────────────────────
@callback(
    [Output("qt-main-graph", "figure"),
     Output("qt-info-table", "rowData")],
    [Input("qt-btn-plot",     "n_clicks"),
     Input("qt-redraw-store", "data")],
    [State("qt-tag-dropdown",     "value"),
     State("qt-info-table",       "rowData"),
     State("qt-axis-config-grid", "rowData"),
     State("qt-x-range-store",    "data"),
     State("qt-y-ranges-store",   "data"),
     State("qt-fontsize-input",   "value"),
     State("qt-window-input",     "value")],
    prevent_initial_call=True
)
def cb_render_graph(n_clicks, redraw_store,
                    selected_tags, current_rows_state,
                    axis_defs, x_store, y_store, font_size, window_value):  
    if not selected_tags:
        return go.Figure(), []

    ctx     = dash.callback_context
    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    reason  = (redraw_store or {}).get("reason", "")

    current_rows = list(current_rows_state or [])
    axis_rows    = list(axis_defs or [])
    
    with state_lock:
        active_tags.clear()
        _desc_lookup = dict(cached_tags_desc)

        for full_entry in selected_tags:
            clean_tag = full_entry.split(";")[0].strip()
            active_tags.add(clean_tag)

    new_rows = []
    _desc_lookup = cached_tags_desc  # safe: write-once at startup

    for i, full_entry in enumerate(selected_tags):
        t_id = full_entry.strip()
        t_desc = _desc_lookup.get(t_id, "")

        existing = next((r for r in current_rows if r.get("tag") == t_id), None)
        
        if existing:
            new_rows.append(dict(existing))
        elif reason != "delete": 
            colors = ["#636EFA", "#EF553B", "#00CC96", "#AB63FA",
                      "#FFA15A", "#19D3F3", "#FF6692", "#B6E880"]
            new_rows.append({
                "tag":        t_id,
                "name":       t_id,    # Initialized to tag
                "desc":       t_desc,
                "axis_sel":   "Custom",
                "color":      colors[len(new_rows) % len(colors)],
                "axis_id":    1,
                "delete-row": "✘",
                "_selected":  False,
                "cur_val":    "",
                "cursor_val": "",
            })
    current_rows = new_rows

    now = datetime.now()
    seconds = parse_mmss(window_value or "5:00")
    start_dt = now - timedelta(seconds=seconds)

    clean_tag_list = [r["tag"] for r in current_rows]
    time_axis, data_dict = _get_data_for_tags(clean_tag_list, start_dt)

    LAYOUT_REASONS = {"delete", "tag_edit", "axis_sel", "color", "autoscale", "name_edit"}
    needs_layout_rebuild = (trigger == "qt-btn-plot" or (reason in LAYOUT_REASONS and reason != "live"))

    if needs_layout_rebuild:
        ax_map = {str(a["id"]): a for a in (axis_rows or [])}
        fig = _build_figure(current_rows, time_axis, data_dict, ax_map, y_store,
                            font_size=int(font_size or 12))
        fig.update_layout(transition={"duration": 0}, uirevision="stable")
        return fig, current_rows

    # --- Legend Sync via Patch ---
    now = datetime.now()
    seconds = parse_mmss(...)  # you need the window value here
    start = now - timedelta(seconds=seconds)

    now = datetime.now()
    seconds = parse_mmss(window_value or "5:00")
    start = now - timedelta(seconds=seconds)

    patched = Patch()
    patched["layout"]["xaxis"]["range"] = [start.isoformat(), now.isoformat()]
    patched["layout"]["xaxis"]["autorange"] = False

    for i, row in enumerate(current_rows):
        tag = row["tag"]
        ydata = data_dict.get(tag, [])
        patched["data"][i]["x"] = time_axis
        patched["data"][i]["y"] = ydata
        patched["data"][i]["name"] = row.get("name", tag)
        patched["data"][i]["meta"] = tag

    return patched, no_update

@callback(
    Output("qt-info-table", "rowData", allow_duplicate=True),
    Input("qt-live-interval", "n_intervals"),
    State("qt-info-table", "rowData"),
    prevent_initial_call=True
)
def cb_live_update_values(n, current_rows):
    if not current_rows:
        return no_update
    new_rows = []
    with state_lock:
        for row in current_rows:
            row = dict(row)
            dq = tag_data.get(row["tag"], deque())
            if dq:
                _, val = dq[-1]
                row["cur_val"] = f"{val:.3f}"
            new_rows.append(row)
    return new_rows

# ─── 12. OPEN AXIS MODAL ─────────────────────────────────────────────────
@callback(
    [Output("qt-axis-modal",      "is_open"),
     Output("qt-axis-config-grid","rowData", allow_duplicate=True)],
    [Input("qt-btn-axis-modal",   "n_clicks"),
     Input("qt-close-axis-modal", "n_clicks")],
    [State("qt-axis-modal",       "is_open"),
     State("qt-axis-config-grid", "rowData"),
     State("qt-y-ranges-store",   "data")],
    prevent_initial_call=True
)
def cb_modal_open_close(open_clicks, close_clicks, is_open, axis_rows, y_store):
    trigger = dash.callback_context.triggered[0]["prop_id"].split(".")[0]
    if trigger == "qt-btn-axis-modal" and not is_open:
        if axis_rows:
            new_rows = []
            for row in axis_rows:
                row = dict(row)
                ak  = _ax_key(int(row["id"]))
                stored = (y_store or {}).get(ak)
                if isinstance(stored, list) and len(stored) == 2 and None not in stored:
                    row["rangeMIN"] = f"{stored[0]:.4g}"
                    row["rangeMAX"] = f"{stored[1]:.4g}"
                new_rows.append(row)
            return True, new_rows
        return True, no_update
    return False, no_update

# ─── 13. CLOSE AXIS MODAL: APPLY ─────────────────────────────────────────
@callback(
    [Output("qt-y-ranges-store", "data",   allow_duplicate=True),
     Output("qt-main-graph",     "figure", allow_duplicate=True)],
    Input("qt-close-axis-modal", "n_clicks"),
    [State("qt-axis-config-grid","rowData"),
     State("qt-info-table",      "rowData"),
     State("qt-main-graph",      "figure"),
     State("qt-y-ranges-store",  "data")],
    prevent_initial_call=True
)
def cb_modal_save(n_clicks, axis_rows, info_rows, current_fig, y_store):
    if not n_clicks or not axis_rows or not current_fig:
        return no_update, no_update
    y_store  = dict(y_store or {})
    ax_map   = {str(a["id"]): a for a in axis_rows}
    used_ids = sorted(set(int(r["axis_id"]) for r in (info_rows or [])))
    layout_patch = {}
    for aid_int in used_ids:
        aid  = str(aid_int)
        ak   = _ax_key(aid_int)
        conf = ax_map.get(aid, {})
        ax_update = {"title": {"text": conf.get("name", f"Asse {aid}"), "font": {"size": 12}}}
        try:
            rmin, rmax     = float(conf["rangeMIN"]), float(conf["rangeMAX"])
            ax_update["range"]     = [rmin, rmax]
            ax_update["autorange"] = False
            y_store[ak]            = [rmin, rmax]
        except (ValueError, TypeError, KeyError):
            ax_update["autorange"] = True
            y_store[ak]            = None
        layout_patch[ak] = ax_update
    patched = go.Figure(current_fig)
    patched.update_layout(layout_patch)
    return y_store, patched

# ─── 14. PRESET IN AXIS GRID ─────────────────────────────────────────────
@callback(
    Output("qt-axis-config-grid", "rowData", allow_duplicate=True),
    Input("qt-axis-config-grid",  "cellValueChanged"),
    State("qt-axis-config-grid",  "rowData"),
    prevent_initial_call=True
)
def cb_grid_preset_changed(cell_changed, axis_rows):
    if not cell_changed or not axis_rows:
        return no_update
    changed    = cell_changed[0]
    if changed.get("colId") != "preset":
        return no_update
    preset_key = changed["value"]
    row_id     = str(changed["data"]["id"])
    preset     = AXIS_PRESETS.get(preset_key)
    if not preset:
        return no_update
    new_rows = []
    for row in axis_rows:
        row = dict(row)
        if str(row["id"]) == row_id:
            row["preset"] = preset_key
            if preset_key != "Custom":
                row["name"]     = preset["name"]
                row["rangeMIN"] = preset["rangeMIN"]
                row["rangeMAX"] = preset["rangeMAX"]
        new_rows.append(row)
    return new_rows

# ─── 15. CELL CLICK: DELETE / COLOR / HIGHLIGHT ──────────────────────────
@callback(
    [Output("qt-info-table",           "rowData",  allow_duplicate=True),
     Output("qt-main-graph",           "figure",   allow_duplicate=True),
     Output("qt-tag-dropdown",         "value",    allow_duplicate=True),
     Output("qt-selected-row-store",   "data"),
     Output("qt-color-picker-modal",   "is_open"),
     Output("qt-color-edit-store",     "data"),
     Output("qt-color-input",          "value"),
     Output("qt-redraw-store",         "data",     allow_duplicate=True)],
    Input("qt-info-table", "cellClicked"),
    [State("qt-info-table",    "rowData"),
     State("qt-main-graph",    "figure"),
     State("qt-tag-dropdown",  "value")],
    prevent_initial_call=True
)
def cb_cell_clicked(clicked, current_rows, fig, current_tags):
    nu = no_update
    if not clicked or not current_rows:
        return nu, nu, nu, nu, False, nu, nu, nu
    
    row_idx = clicked.get("rowIndex")
    col_id  = clicked.get("colId")
    
    # Do not interrupt if user is trying to edit Name or Axis Selection
    if col_id in ("axis_sel", "name"):
        return nu, nu, nu, nu, False, nu, nu, nu
        
    if row_idx is None or row_idx >= len(current_rows):
        return nu, nu, nu, None, False, nu, nu, nu
        
    selected_tag = current_rows[row_idx]["tag"]

    # --- Handle Deletion ---
    if col_id == "delete-row":
        new_table = [r for i, r in enumerate(current_rows) if i != row_idx]
        if fig and "data" in fig:
            # Match by the tag stored in 'meta'
            fig["data"] = [t for t in fig["data"] if selected_tag != t.get("meta")]
        
        # Sync dropdown: remove the entry that starts with this tag
        new_tags = [s for s in (current_tags or []) if not s.startswith(selected_tag)]
        
        with state_lock:
            active_tags.discard(selected_tag)
            
        return (new_table, fig, new_tags, None, False, None, None, 
                {"ts": datetime.now().isoformat(), "reason": "delete"})

    # --- Handle Color Picker ---
    if col_id == "color":
        current_color = current_rows[row_idx].get("color", "#0000FF")
        return nu, nu, nu, selected_tag, True, row_idx, {"hex": current_color}, nu

    # --- Handle Row Selection & Highlighting ---
    # 1. Update the Plotly Figure (Highlight the selected trace)
    if fig and "data" in fig:
        for trace in fig["data"]:
            # Set width to 4 if it's the clicked tag, otherwise reset to 1.5
            trace["line"]["width"] = (4 if selected_tag == trace.get("meta") else 1.5)
        fig["layout"]["uirevision"] = "static"
        
    # 2. Update the Table Rows (Bold logic)
    # We create a brand new list where ONLY the clicked tag is True
    updated_rows = []
    for r in current_rows:
        new_row = dict(r)
        # This logic ensures only one row is True at a time
        new_row["_selected"] = (new_row["tag"] == selected_tag)
        updated_rows.append(new_row)
        
    return updated_rows, fig, nu, selected_tag, False, None, None, nu

# ─── 16. COLOR CONFIRM ───────────────────────────────────────────────────
@callback(
    [Output("qt-info-table",         "rowData",  allow_duplicate=True),
     Output("qt-color-picker-modal", "is_open",  allow_duplicate=True),
     Output("qt-redraw-store",       "data",     allow_duplicate=True)],
    Input("qt-color-confirm", "n_clicks"),
    [State("qt-color-input",      "value"),
     State("qt-color-edit-store", "data"),
     State("qt-info-table",       "rowData")],
    prevent_initial_call=True
)
def update_row_color(n_clicks, color_value, row_idx, current_rows):
    if n_clicks is None or row_idx is None:
        return no_update, False, no_update
    new_hex = "#0000FF"
    if isinstance(color_value, dict) and "hex" in color_value:
        new_hex = color_value["hex"]
    elif isinstance(color_value, str):
        new_hex = color_value
    if row_idx < len(current_rows):
        new_rows            = [row.copy() for row in current_rows]
        new_rows[row_idx]["color"] = new_hex
        return new_rows, False, {"ts": datetime.now().isoformat(), "reason": "color"}
    return no_update, False, no_update

# ─── 17. SYNC TABLE COLOR TO GRAPH ───────────────────────────────────────
@callback(
    Output("qt-main-graph", "figure", allow_duplicate=True),
    Input("qt-info-table",  "rowData"),
    State("qt-main-graph",  "figure"),
    prevent_initial_call=True
)
def sync_table_color_to_graph(table_data, fig):
    if not table_data or not fig:
        return no_update
    color_map = {row["tag"]: row["color"] for row in table_data}
    for trace in fig["data"]:
        tag_name = trace.get("name", "")
        if tag_name in color_map:
            trace["line"]["color"] = color_map[tag_name]
    fig["layout"]["uirevision"] = "constant"
    return fig

# ─── 18. COLOR COLUMN STYLE ──────────────────────────────────────────────
@callback(
    Output("qt-info-table", "columnDefs"),
    Input("qt-info-table",  "rowData"),
    State("qt-info-table",  "columnDefs"),
)
def update_color_column_style(row_data, col_defs):
    if not row_data:
        return col_defs
    colors = list({row["color"] for row in row_data if row.get("color")})
    style_conditions = [
        {"condition": f"params.value === '{c}'",
         "style": {"backgroundColor": c, "color": c}}
        for c in colors
    ]
    for col in col_defs:
        if col.get("field") == "color":
            col["cellStyle"] = {
                "styleConditions": style_conditions,
                "defaultStyle":    {"backgroundColor": "white", "color": "white"}
            }
    return col_defs

# ─── 19. AUTOSCALE Y ─────────────────────────────────────────────────────
@callback(
    [Output("qt-y-ranges-store", "data",  allow_duplicate=True),
     Output("qt-redraw-store",   "data",  allow_duplicate=True)],
    Input("qt-btn-autoscale", "n_clicks"),
    State("qt-info-table",    "rowData"),
    prevent_initial_call=True
)
def cb_autoscale_y(n_clicks, info_rows):
    if not n_clicks:
        return no_update, no_update
    y_store = {_ax_key(int(row["axis_id"])): "auto" for row in (info_rows or [])}
    return y_store, {"ts": datetime.now().isoformat(), "reason": "autoscale"}

# ─── 20. FONTSIZE BUTTONS ────────────────────────────────────────────────
@callback(
    Output("qt-fontsize-input", "value"),
    [Input("qt-btn-fontsize-down", "n_clicks"),
     Input("qt-btn-fontsize-up",   "n_clicks"),
     Input("qt-fontsize-input",    "value")],
    prevent_initial_call=True
)
def cb_fontsize_buttons(down, up, typed):
    trigger  = dash.callback_context.triggered[0]["prop_id"].split(".")[0]
    minSize, maxSize = 6, 20
    if trigger == "qt-btn-fontsize-down":
        try:    return str(max(minSize, int(typed or 10) - 1))
        except: return "10"
    if trigger == "qt-btn-fontsize-up":
        try:    return str(min(maxSize, int(typed or 10) + 1))
        except: return "10"
    try:    return str(max(minSize, min(maxSize, int(typed))))
    except: return "10"

# ─── 21. APPLY FONTSIZE ──────────────────────────────────────────────────
@callback(
    Output("qt-main-graph", "figure", allow_duplicate=True),
    Input("qt-fontsize-input", "value"),
    [State("qt-main-graph",   "figure"),
     State("qt-info-table",   "rowData")],
    prevent_initial_call=True
)
def cb_apply_fontsize(font_size, figure, info_rows):
    if not figure or not font_size:
        return no_update
    fs        = int(font_size)
    linewidth = 1.5 * (1 + (fs - 10) * 0.10)
    patched   = Patch()
    patched["layout"]["font"]                        = {"size": fs}
    patched["layout"]["xaxis"]["title"]["font"]      = {"size": fs}
    patched["layout"]["xaxis"]["tickfont"]           = {"size": fs}
    old_layout = figure.get("layout", {})
    for key in old_layout:
        if key.startswith("yaxis"):
            patched["layout"][key]["title"]["font"] = {"size": fs}
            patched["layout"][key]["tickfont"]      = {"size": fs}
    new_annotations = []
    for ann in old_layout.get("annotations", []):
        ann = dict(ann)
        ann["font"] = dict(ann.get("font", {}))
        ann["font"]["size"] = fs
        new_annotations.append(ann)
    patched["layout"]["annotations"] = new_annotations
    for i in range(len(figure.get("data", []))):
        patched["data"][i]["line"]["width"] = linewidth
    return patched

# ─── 22. EXPORT PDF ──────────────────────────────────────────────────────
@callback(
    Output("qt-download-pdf", "data"),
    Input("qt-btn-export-pdf", "n_clicks"),
    State("qt-main-graph",     "figure"),
    prevent_initial_call=True
)
def cb_export_pdf(n_clicks, figure):
    if not n_clicks or not figure:
        return no_update
    filename = f"{date.today().strftime('%Y_%m_%d')}_quicktrends.pdf"
    fig      = go.Figure(figure)
    pdf      = fig.to_image(format="pdf", width=1920, height=1080, scale=1)
    return dcc.send_bytes(pdf, filename=filename)

# 23. APPLY TIME RANGE
@callback(
    Output("qt-main-graph", "figure", allow_duplicate=True),
    Input("qt-window-input", "n_submit"),
    [State("qt-window-input", "value"),
     State("qt-main-graph", "figure")],
    prevent_initial_call=True
)
def cb_apply_window(n_submit, window_value, figure):
    if not figure or not window_value:
        return no_update
    seconds = parse_mmss(window_value)
    now = datetime.now()
    start = now - timedelta(seconds=seconds)
    patched = Patch()
    patched["layout"]["xaxis"]["range"] = [start.isoformat(), now.isoformat()]
    patched["layout"]["xaxis"]["autorange"] = False
    return patched