import dash
from dash import dcc, html, Input, Output, State, callback, ALL, MATCH, no_update
import dash_bootstrap_components as dbc
import pandas as pd
import os
from datetime import datetime
from utils import data_processor as dp
import re
# --- Configuration & Data ---
NETWORK_BASE_PATH = r"\\10.33.126.101\archivi\TOTALE\PROVE"
file_path = r"\\10.33.126.101\archivi\BinRev 3.0\consumption.json"

dash.register_page(__name__, path="/consumi")

dfCons = pd.read_json(file_path)
columns = ["Tag", "Description", "Algorithm", "Group", "ConversionFactor", "MeasurementUnit"]
dfCons = dfCons[columns].sort_values(by="Group").reset_index(drop=True)
dfCons['Selected'] = False

# --- Helper Functions ---
def format_file_size(size_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def list_bin_files(folder_path: str) -> list:
    files = []
    if not os.path.exists(folder_path):
        return files
    for f in os.listdir(folder_path):
        if f.lower().endswith('.bin'):
            full = os.path.join(folder_path, f)
            try:
                stat = os.stat(full)
                mtime = datetime.fromtimestamp(stat.st_mtime)
                files.append({
                    'label': f"{f}  |  {mtime.strftime('%Y-%m-%d %H:%M')}  |  {format_file_size(stat.st_size)}",
                    'value': full,
                })
            except:
                files.append({'label': f, 'value': full})
    files.sort(key=lambda x: x['value'])
    return files

# --- Layout ---
layout = html.Div([
    # Add this inside your layout Div
    html.Div([
        html.H5("Parametri Operativi", className="text-primary mt-4 mb-3"),
        
        dbc.Row([
            dbc.Col([
                html.Label("Inizio Compressore:", className="small fw-bold"),
                dbc.Input(id="time-start-comp", type="time", value="08:00")
            ], width=3),
            dbc.Col([
                html.Label("Fine Compressore:", className="small fw-bold"),
                dbc.Input(id="time-stop-comp", type="time", value="20:00")
            ], width=3),
        ], className="mb-3"),

        html.Div(id="exclusion-container", children=[]),

        dbc.ButtonGroup([
            dbc.Button("➕ Aggiungi Esclusione", id="btn-add-exclusion", color="outline-primary", size="sm"),
            dbc.Button("➖ Rimuovi Ultima", id="btn-remove-exclusion", color="outline-danger", size="sm"),
        ], className="mt-2"),
        
        html.Hr(),
        dbc.Button("🚀 CALCOLA CONSUMI", id="btn-calculate", color="success", className="w-100 mt-3")
    ], className="border p-3 rounded bg-light"),
    # Stores
    dcc.Store(id='cons-selected-path', data=None),
    dcc.Store(id='cons-config-store', data=None),
    dcc.Store(id='selected-tags-store', data=[]),

    html.H4("Selezione Tag Consumi", className="mb-4"),
    
    dbc.Button("📂 SELEZIONA BINARIO", id="cons-btn-open-modal", color="primary", className="mb-3"),
    
    # Status Message Area
    html.Div(id="cons-status-msg", className="mb-3"),

    # Modal for File Selection
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Seleziona File Binario")),
        dbc.ModalBody([
            html.Label("Seleziona Data:", className="fw-bold mb-2"),
            dcc.DatePickerSingle(
                id="cons-date-picker",
                date=datetime.now().date(),
                display_format='YYYY-MM-DD',
                className="mb-3"
            ),
            html.Div(id="cons-file-info-modal", className="mb-2"), 
            html.Label("File .bin disponibili:", className="fw-bold mb-2"),
            dcc.Dropdown(id="cons-file-dropdown", placeholder="Seleziona un file..."),
            # Placeholder for metadata card inside modal or outside
            html.Div(id="cons-file-info", className="mt-3") 
        ]),
        dbc.ModalFooter([
            dbc.Button("❌ Chiudi", id="cons-btn-close-modal", color="secondary", className="me-2"),
            dbc.Button("✅ Carica File", id="cons-btn-load-file", color="primary", disabled=True)
        ]),
    ], id="cons-file-modal", is_open=False),

    # Selection Controls
    dbc.Card([
        dbc.CardBody(
            dbc.Checkbox(
                id="master-select-all",
                label="SELEZIONA TUTTI I GRUPPI",
                value=False,
                className="fw-bold text-primary"
            )
        )
    ], className="mb-4 border-primary"),

    html.Div(id="groups-container", children=[]),
], className="p-4")

# --- Callbacks ---

# 1. Render Groups on Load
@callback(
    Output("groups-container", "children"),
    Input("groups-container", "id")
)
def render_groups(_):
    cards = []
    for group_name in dfCons['Group'].unique():
        group_df = dfCons[dfCons['Group'] == group_name]
        header = dbc.Row([
            dbc.Col(html.B(group_name)),
            dbc.Col(dbc.Checkbox(
                id={'type': 'select-all', 'index': group_name},
                label="Select All", value=False, className="small"
            ), width="auto")
        ], align="center")

        checklist = dbc.Checklist(
            options=[{"label": f"{r['Description']} - {r['Tag']}", "value": r['Tag']} for _, r in group_df.iterrows()],
            value=[],
            id={'type': 'tag-checklist', 'index': group_name},
        )
        cards.append(dbc.Card([dbc.CardHeader(header), dbc.CardBody(checklist)], className="mb-3"))
    return cards

# 2. Consolidated Modal Toggle & File Listing
@callback(
    [Output('cons-file-modal', 'is_open'),
     Output('cons-file-dropdown', 'options'),
     Output('cons-file-dropdown', 'value'),
     Output('cons-file-info-modal', 'children')],
    [Input('cons-btn-open-modal', 'n_clicks'),
     Input('cons-btn-close-modal', 'n_clicks'),
     Input('cons-btn-load-file', 'n_clicks'),
     Input('cons-date-picker', 'date')],
    [State('cons-file-modal', 'is_open')],
    prevent_initial_call=True
)
def handle_modal_and_files(n_open, n_close, n_load, selected_date, is_open):
    ctx = dash.callback_context
    trigger = ctx.triggered[0]['prop_id']

    # Handle Modal Toggle
    if any(x in trigger for x in ['cons-btn-open-modal', 'cons-btn-close-modal', 'cons-btn-load-file']):
        # If we are closing, just return False
        if is_open:
            return False, no_update, no_update, no_update
        
        # If opening, list files for current date
        is_open = True

    # Handle File Listing (Triggered by Opening OR Date Change)
    if not selected_date:
        return is_open, [], None, "Seleziona una data"

    folder_name = selected_date.replace("-", "")
    folder_path = os.path.join(NETWORK_BASE_PATH, folder_name)
    files = list_bin_files(folder_path)

    if not files:
        return is_open, [], None, html.Div("Nessun file trovato.", className="text-danger small")

    auto_select = files[0]['value'] if len(files) == 1 else None
    return is_open, files, auto_select, html.Div(f"{len(files)} file trovati", className="text-success small")

# 3. Path Selection and Button Enable
@callback(
    [Output('cons-btn-load-file', 'disabled'),
     Output('cons-selected-path', 'data')],
    Input('cons-file-dropdown', 'value'),
    prevent_initial_call=True
)
def cb_select_file(selected_path):
    return (selected_path is None), selected_path

# 4. Load Metadata (The Logic you requested)
@callback(
    [Output('cons-config-store', 'data'),
     Output('cons-file-info', 'children'),
     Output('cons-status-msg', 'children')],
    Input('cons-btn-load-file', 'n_clicks'),
    State('cons-selected-path', 'data'),
    prevent_initial_call=True
)
def cb_load_file(n_clicks, selected_path):
    if not selected_path or not os.path.exists(selected_path):
        return no_update, no_update, dbc.Alert("File non trovato.", color="danger")
    
    try:
        cfg = dp.get_wbin_metadata(selected_path)
        
        # Build your info_content card here based on cfg...
        info_content = html.Div([
            html.P(f"File: {os.path.basename(selected_path)}", className="small fw-bold"),
            html.P(f"Blocks: {cfg.get('total_blocks', 'N/A')}", className="small")
        ])

        return cfg, info_content, dbc.Alert(f"✓ {os.path.basename(selected_path)} caricato", color="success")
    except Exception as e:
        return no_update, no_update, dbc.Alert(f"Errore: {str(e)}", color="danger")

# 5. Selection Sync Callbacks
@callback(
    Output({'type': 'select-all', 'index': ALL}, 'value'),
    Input('master-select-all', 'value'),
    prevent_initial_call=True
)
def cb_master_toggle(master_checked):
    ctx = dash.callback_context
    return [master_checked] * len(ctx.outputs_list)

@callback(
    Output({'type': 'tag-checklist', 'index': MATCH}, 'value'),
    Input({'type': 'select-all', 'index': MATCH}, 'value'),
    State({'type': 'tag-checklist', 'index': MATCH}, 'options'),
    prevent_initial_call=True
)
def toggle_group_selection(is_checked, options):
    return [opt['value'] for opt in options] if is_checked else []

@callback(
    Output("selected-tags-store", "data"),
    Input({'type': 'tag-checklist', 'index': ALL}, 'value'),
    prevent_initial_call=True
)
def update_dataframe_selection(all_values):
    selected_tags = [tag for sublist in all_values for tag in sublist]
    global dfCons
    dfCons['Selected'] = dfCons['Tag'].isin(selected_tags)
    return selected_tags


@callback(
    Output("exclusion-container", "children"),
    [Input("btn-add-exclusion", "n_clicks"),
     Input("btn-remove-exclusion", "n_clicks")],
    State("exclusion-container", "children"),
    prevent_initial_call=True
)
def manage_exclusions(add_n, rem_n, current_children):
    ctx = dash.callback_context
    trigger = ctx.triggered[0]['prop_id']

    if "btn-add-exclusion" in trigger:
        new_idx = len(current_children)
        new_row = dbc.Row([
            dbc.Col([
                html.Label(f"Esclusione {new_idx + 1} - Inizio:", className="small text-muted"),
                dbc.Input(id={'type': 'exclude-start', 'index': new_idx}, type="time", value="12:00")
            ], width=3),
            dbc.Col([
                html.Label(f"Esclusione {new_idx + 1} - Fine:", className="small text-muted"),
                dbc.Input(id={'type': 'exclude-end', 'index': new_idx}, type="time", value="13:00")
            ], width=3),
        ], className="mb-2 animate__animated animate__fadeIn", id={'type': 'exclusion-row', 'index': new_idx})
        
        current_children.append(new_row)
        return current_children

    if "btn-remove-exclusion" in trigger and current_children:
        current_children.pop()
        return current_children

    return no_update



@callback(
    Output("cons-status-msg", "children", allow_duplicate=True),
    Input("btn-calculate", "n_clicks"),
    [State("time-start-comp", "value"),
     State("time-stop-comp", "value"),
     State({'type': 'exclude-start', 'index': ALL}, 'value'),
     State({'type': 'exclude-end', 'index': ALL}, 'value'),
     State("selected-tags-store", "data"),
     State("cons-selected-path", "data")],
    prevent_initial_call=True
)
def run_calculations(n, start_comp, stop_comp, ex_starts, ex_ends, selected_tags, file_path):
    if not file_path:
        return dbc.Alert("⚠️ Carica prima un file binario!", color="danger")
    if not selected_tags:
        return dbc.Alert("⚠️ Seleziona almeno un tag!", color="warning")

    # 1. Check Main Compressor Times
    if start_comp >= stop_comp:
        return dbc.Alert(
            f"❌ Errore Orario: L'inizio ({start_comp}) deve essere precedente alla fine ({stop_comp}).", 
            color="danger"
        )

    # 2. Check Dynamic Exclusions
    # We zip them together to check each pair: (start1, end1), (start2, end2)...
    for i, (ex_start, ex_end) in enumerate(zip(ex_starts, ex_ends)):
        # Check if start < end within the same exclusion
        if ex_start >= ex_end:
            return dbc.Alert(
                f"❌ Errore Esclusione {i+1}: L'orario di inizio ({ex_start}) deve essere precedente alla fine ({ex_end}).",
                color="danger"
            )
        
        # Optional: Check if the exclusion falls within the compressor operating window
        if ex_start < start_comp or ex_end > stop_comp:
            return dbc.Alert(
                f"⚠️ Nota: L'esclusione {i+1} ({ex_start}-{ex_end}) è parzialmente fuori dall'orario compressore ({start_comp}-{stop_comp}).",
                color="warning"
            )

    # 3. Check for Overlapping Exclusions (Increasing Order)
    # This ensures Excl 1 is before Excl 2, etc.
    for i in range(len(ex_starts) - 1):
        if ex_ends[i] > ex_starts[i+1]:
            return dbc.Alert(
                f"❌ Errore Sequenza: L'esclusione {i+1} finisce dopo l'inizio dell'esclusione {i+2}. Mantieni l'ordine cronologico.",
                color="danger"
            )

    # --- Proceed to Math if all checks pass ---
    try:
        # result = perform_math(file_path, selected_tags, start_comp, stop_comp, zip(ex_starts, ex_ends))
        return dbc.Alert("✅ Orari validi. Calcolo in corso...", color="success")
    except Exception as e:
        return dbc.Alert(f"Errore: {str(e)}", color="danger")