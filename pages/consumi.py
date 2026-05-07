import dash
from dash import dcc, html, Input, Output, State, callback, ALL, MATCH, no_update
import dash_bootstrap_components as dbc
import pandas as pd
import os
from datetime import datetime
from utils import data_processor as dp
import dash_ag_grid as dag
import io

#region CONFIG
NETWORK_BASE_PATH = r"\\10.33.126.101\archivi\TOTALE\PROVE"
file_path = r"\\10.33.126.101\archivi\BinRev 3.0\consumption.json"

dash.register_page(__name__, path="/consumi")

dfCons = pd.read_json(file_path)
columns = ["Tag", "Description", "Algorithm", "Group", "ConversionFactor", "MeasurementUnit"]
dfCons = dfCons[columns].sort_values(by="Group").reset_index(drop=True)
dfCons['Selected'] = False

#region LAYOUT
layout = html.Div([
    
    # Stores
    dcc.Store(id='cons-selected-paths', data=[]),
    dcc.Store(id='cons-config-store', data=None),
    dcc.Store(id='selected-tags-store', data=[]),
    dcc.Store(id='storage-info', storage_type='memory'),
    dcc.Download(id="download-text"),
    html.H4("Gestione consumi complessivi", className="mb-4"),
        
    # Status Message Area
    html.Div(id="cons-status-msg", className="mb-3"),
    # Add this inside your layout Div
    html.Div([
        html.H5("Orari", className="text-primary mt-0 mb-3"),
        
        dbc.Row([
            dbc.Col([
                html.Label("Accensione Compressore:", className="small fw-bold"),
                dbc.Input(id="time-start-comp", type="time", value="08:00")
            ], width=3),
            dbc.Col([
                html.Label("Spegnimento Compressore:", className="small fw-bold"),
                dbc.Input(id="time-stop-comp", type="time", value="20:00")
            ], width=3),
        ], className="mb-3"),

        html.Div(id="exclusion-container", children=[]),

        dbc.ButtonGroup([
            dbc.Button("➕ Aggiungi Esclusione", id="btn-add-exclusion", color="outline-primary", size="sm"),
            dbc.Button("➖ Rimuovi Ultima", id="btn-remove-exclusion", color="outline-danger", size="sm"),
        ], className="mt-2"),
        
        html.Hr(),
        dbc.Row([
            dbc.Col(dbc.Button("📂 SELEZIONA BINARIO", id="cons-btn-open-modal", color="primary"), width="auto"),
            dbc.Col(dbc.Button("🚀 CALCOLA CONSUMI", id="btn-calculate", color="success"), width="auto", className="ms-auto"),
        ], className="mb-3 mt-3"),
    ], className="border p-3 rounded bg-light"),

    

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
            dcc.Dropdown(id="cons-file-dropdown", placeholder="Seleziona uno o più file...", multi=True),
            # Placeholder for metadata card inside modal or outside
            html.Div(id="cons-file-info", className="mt-3") 
        ]),
        dbc.ModalFooter([
            dbc.Button("❌ Chiudi", id="cons-btn-close-modal", color="secondary", className="me-2"),
            dbc.Button("✅ Carica File", id="cons-btn-load-file", color="primary", disabled=True)
        ]),
    ], id="cons-file-modal", is_open=False),
    html.Div(id="clamp-warning", className="mb-3 mt-3"), # clamping warning for negative measurements set to 0
    # RESULTS PREVIEW
    html.Div(id="cons-results-container", children=[
        html.Div([
            dbc.Row([
                dbc.Col(html.H5("Risultati Calcolo Consumi", className="text-success"), width=True),
                dbc.Col(dbc.Button("📥 Scarica CSV", id="btn-export-csv", color="outline-success", size="sm"), width="auto"),
                dbc.Col(dbc.Button("📥 Scarica TXT", id="btn-export-txt", color="outline-success", size="sm"), width="auto"),
            ], align="center", className="mb-2 mt-2"),
            
            dag.AgGrid(
                id="cons-results-grid",
                columnDefs=[
                    {"field": "Tag", "headerName": "TAG", "checkboxSelection": False},
                    {"field": "Description", "headerName": "DESCRIZIONE", "flex": 2},
                    {"field": "Value", "headerName": "VALUE", "valueFormatter": "typeof params.value === 'boolean' ? (params.value ? '✅' : '❌') : params.value !== null ? params.value.toFixed(3) : ''"},                     
                    {"field": "MeasurementUnit", "headerName": "UNIT", "width": 100},
                ],
                rowData=[],
                dashGridOptions={
                    "rowSelection": "multiple", 
                    "animateRows": False,
                    "domLayout": "autoHeight"
                },
                columnSize="responsiveSizeToFit",
                defaultColDef={"resizable": True, "sortable": True, "filter": True},
                style={"width": "100%"}
            ),
            html.Hr(className="my-4"),
        ], id="cons-results-inner", style={"display": "none"}) # Hidden by default
    ]),
    # master select all
    dbc.Card([
        dbc.CardBody(
            dbc.Checkbox(
                id="master-select-all",
                label="SELEZIONA TUTTI I GRUPPI",
                value=False,
                className="fw-bold text-primary"
            )
        )
    ], className="mb-4 mt-4 border-primary shadow-sm w-auto d-inline-block"),

    dbc.Card([
        dbc.CardHeader(dbc.Row([
            dbc.Col(html.B("SISTEMI ATTIVI")),
            dbc.Col(
                dbc.Checkbox(id='select-all-systems', label="Select All", value=False, className="small"),
                width="auto"
            )
        ], align="center")),
        dbc.CardBody(
            dbc.Checklist(
                options=[{"label": s, "value": s} for s in [
                    "TosiCompressor", "BHCompressor", "InertSystem", "LpgLowFlowSystem",
                    "LpgHighFlowSystem", "HydrogenSystem", "MultigasSystem", "SyngasSystem",
                    "JetA1System", "Blowers", "SteamGenerator", "DieselTestSystem", "Heather10EH800"
                ]],
                value=[],
                id="systems-checklist"
            )
        )
    ], className="mb-3 shadow-sm"),
    html.Hr(),
    # The groups will be injected here as a dbc.Row with 2 Cols
    html.Div(id="groups-container"),

    # animation modal when loading
    dbc.Modal([
        dbc.ModalBody([
            html.Div([
                html.Img(src="https://media.giphy.com/media/JIX9t2j0ZTN9S/giphy.gif", 
                        style={"width": "200px", "borderRadius": "12px"}),
                html.P("Calcolo in corso...", className="mt-3 fw-bold text-primary")
            ], className="text-center py-3")
        ])
    ], id="loading-modal", is_open=False, centered=True, backdrop="static", keyboard=False),
], className="p-4 bg-white", style={"minHeight": "100vh"})

#region CALLBACKS

# 1. Render Groups on Load
# ------------- render groups (Balanced 2-Column Version)
@callback(
    Output("groups-container", "children"),
    Input("groups-container", "id") 
)
def render_groups(_):
    col_left = []
    col_right = []
    
    # Track the "height" of each column based on number of tags
    height_left = 0
    height_right = 0

    # Get groups and sort them by size (optional, but helps balancing)
    unique_groups = dfCons['Group'].unique()
    
    for group_name in unique_groups:
        group_df = dfCons[dfCons['Group'] == group_name]
        num_tags = len(group_df)
        
        # Build the Card
        header = dbc.Row([
            dbc.Col(html.B(group_name.upper())),
            dbc.Col(
                dbc.Checkbox(
                    id={'type': 'select-all', 'index': group_name},
                    label="Select All", value=False, className="small"
                ), width="auto"
            )
        ], align="center")

        checklist = dbc.Checklist(
            options=[
                {"label": f"{row['Description']} - {row['Tag']}", "value": row['Tag']}
                for _, row in group_df.iterrows()
            ],
            value=[],
            id={'type': 'tag-checklist', 'index': group_name},
            className="cons-checklist" # Custom class for styling if needed
        )

        card = dbc.Card([
            dbc.CardHeader(header),
            dbc.CardBody(checklist)
        ], className="mb-3 shadow-sm")

        # Decide which column to place it in based on current height
        if height_left <= height_right:
            col_left.append(card)
            height_left += (num_tags + 4) # +4 accounts for header/spacing
        else:
            col_right.append(card)
            height_right += (num_tags + 4)

    # Return a Row containing two Columns
    return dbc.Row([
        dbc.Col(col_left, width=12, lg=6),
        dbc.Col(col_right, width=12, lg=6)
    ])


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

    # With multi=True, auto_select must be a list (or None)
    auto_select = [files[0]['value']] if len(files) == 1 else None
    return is_open, files, auto_select, html.Div(f"{len(files)} file trovati (multi-selezionabile)", className="text-success small")

# 3. Path Selection and Button Enable
@callback(
    [Output('cons-btn-load-file', 'disabled'),
     Output('cons-selected-paths', 'data')],
    Input('cons-file-dropdown', 'value'),
    prevent_initial_call=True
)
def cb_select_file(selected_paths):
    is_disabled = not selected_paths or len(selected_paths) == 0
    return is_disabled, selected_paths if selected_paths else []

# 4. Load Metadata
@callback(
    [Output('cons-config-store', 'data'),
     Output('cons-file-info', 'children'),
     Output("cons-status-msg", "children", allow_duplicate=True),
     Output('storage-info', 'data')],
    Input('cons-btn-load-file', 'n_clicks'),    
    State('cons-selected-paths', 'data'),
    prevent_initial_call=True
)
def cb_load_file(n_clicks, selected_paths):
    if not selected_paths or len(selected_paths) == 0:
        return no_update, no_update, dbc.Alert("Nessun file selezionato.", color="danger", className="small"), no_update
    
    # Validate all files exist
    valid_paths = [p for p in selected_paths if os.path.exists(p)]
    if not valid_paths:
        return no_update, no_update, dbc.Alert("Nessun file valido trovato.", color="danger", className="small"), no_update
    
    try:
        # Load metadata from the first file (all files in same date folder share structure)
        cfg = dp.get_wbin_metadata(valid_paths[0])
        meta = cfg.get('meta', {})
        
        file_count = len(valid_paths)
        filenames = ", ".join([os.path.basename(p) for p in valid_paths])
        
        # Extract metadata and initialize TIME placeholders for the export logic
        info_data = {
            'campaign': meta.get('campaign', 'N/A'),
            'customer': meta.get('customer', 'N/A'),
            'coordinator': meta.get('coordinator', 'N/A'),
            'filenames': filenames,
            'file_count': file_count,
            'total_blocks': cfg.get('total_blocks', 0),
            
            # These will be filled by your time-calculation logic/inputs later
            'comp_start': 'Not set',
            'comp_stop': 'Not set',
            'excl_log': 'None',
            'total_duration': '0 min',
            'total_excluded': '0 min',
            'effective_time': '0 min'
        }

        # UI Card display
        info_content = html.Div([
            html.Div([
                html.B("Files: "), html.Span(str(file_count) + " file selezionati"),
                html.Br(),
                html.B("Campaign: "), html.Span(info_data['campaign']),
                html.Br(),
                html.B("Customer: "), html.Span(info_data['customer']),
                html.Br(),
                html.B("Coordinator: "), html.Span(info_data['coordinator']),
            ], className="small mb-2"),
            html.P(f"Total files: {file_count}", className="small text-muted mb-0")
        ])

        return (
            cfg, 
            info_content, 
            dbc.Alert(f"✓ {file_count} file caricati", color="success", className="small"),
            info_data
        )

    except Exception as e:
        return no_update, no_update, dbc.Alert(f"Errore: {str(e)}", color="danger", className="small"), no_update


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
    Output("systems-checklist", "value"),
    Input("select-all-systems", "value"),
    prevent_initial_call=True
)
def toggle_systems(checked):
    if checked:
        return ["TosiCompressor","BHCompressor","InertSystem","LpgLowFlowSystem",
                "LpgHighFlowSystem","HydrogenSystem","MultigasSystem","SyngasSystem",
                "JetA1System","Blowers","SteamGenerator","DieselTestSystem","Heather10EH800"]
    return []

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
                html.Label(f"Inizio:", className="small text-muted"),
                dbc.Input(id={'type': 'exclude-start', 'index': new_idx}, type="time", value="12:00")
            ], width=2),
            dbc.Col([
                html.Label(f"Fine:", className="small text-muted"),
                dbc.Input(id={'type': 'exclude-end', 'index': new_idx}, type="time", value="13:00")
            ], width=2),
            dbc.Col([
                html.Label(f"Motivazione Esclusione:", className="small text-muted"),
                dbc.Input(id={'type': 'exclude-reason', 'index': new_idx}, type="text", placeholder="Hai visto dov'è andata la fiamma? L'ho persa e non la riesco a ritrovare.")
            ], width=5), # Text box for reason
        ], className="mb-2 animate__animated animate__fadeIn", id={'type': 'exclusion-row', 'index': new_idx}, align="end")
        
        current_children.append(new_row)
        return current_children

    if "btn-remove-exclusion" in trigger and current_children:
        current_children.pop()
        return current_children

    return no_update

@callback(
    Output("cons-results-grid", "exportDataAsCsv"),
    Input("btn-export-csv", "n_clicks"),
    prevent_initial_call=True
)
def export_results_csv(n):
    if n:
        return True
    return False

@callback(
    Output("loading-modal", "is_open", allow_duplicate=True),
    Input("btn-calculate", "n_clicks"),
    prevent_initial_call=True
)
def open_loading_modal(n):
    return True if n else False

@callback(
    [Output("loading-modal", "is_open"),  
     Output("cons-results-inner", "style"),
     Output("cons-results-grid", "rowData"),
     Output("cons-status-msg", "children", allow_duplicate=True),
     Output("clamp-warning", "children")],
    Input("btn-calculate", "n_clicks"),
    [State("time-start-comp", "value"),
     State("time-stop-comp", "value"),
     State({'type': 'exclude-start', 'index': ALL}, 'value'),
     State({'type': 'exclude-end', 'index': ALL}, 'value'),
     State("selected-tags-store", "data"),
     State("cons-selected-paths", "data"),
     State("cons-config-store", "data"),
     State("systems-checklist", "value")], # Metadata needed for SID mapping
    prevent_initial_call=True
)
def cb_calculate_consumi(n, start_t, stop_t, ex_starts, ex_ends, selected_tags, file_paths, config_meta, systems):
    if not file_paths or len(file_paths) == 0:
        return False, no_update, no_update, dbc.Alert("⚠️ Seleziona un binario prima!", color="danger"), no_update
    if not selected_tags:
        return False, no_update, no_update, dbc.Alert("⚠️ Seleziona almeno una tag!", color="danger"), no_update
    # Check for overlapping exclusions
    for i in range(len(ex_starts)):
        for j in range(i+1, len(ex_starts)):
            if ex_starts[i] < ex_ends[j] and ex_starts[j] < ex_ends[i]:
                return False, no_update, no_update, dbc.Alert("❌ Esclusioni sovrapposte!", color="danger"), no_update
    try:
        # Load and merge data from ALL selected binary files
        raw_df, n_clamped = load_and_process_binaries(file_paths, selected_tags, config_meta)
        clamp_warn = dbc.Alert(f"⚠️ {n_clamped} valori negativi azzerati.", color="warning") if n_clamped > 0 else ""

        if raw_df.empty:
            return False, no_update, no_update, dbc.Alert("⚠️ Nessun dato caricato dai file selezionati.", color="warning"), no_update

        # Determine file_date from the merged dataframe index
        file_date = raw_df.index.min().date()

        # Convert UI time strings to datetime objects
        t_start = datetime.combine(file_date, datetime.strptime(start_t, "%H:%M").time())
        t_stop = datetime.combine(file_date, datetime.strptime(stop_t, "%H:%M").time())

        # Clamp t_start/t_stop to actual data range
        t_start = max(t_start, raw_df.index.min())
        t_stop = min(t_stop, raw_df.index.max())

        # Now create calcDf safely
        tag_info_df = dfCons[dfCons['Tag'].isin(selected_tags)]
        calcDf = calculate_cumulative_data(raw_df, tag_info_df)
        results = []
        for system in systems:
            results.append({
                "Tag": system,
                "Description": f"IN USO - {system}",
                "Value": 1,
                "MeasurementUnit": "IN USO"
            })
        for tag in selected_tags:
            if tag not in calcDf.columns:
                continue
            # Get values at start/stop using 'asof' for safety
            v_start = calcDf[tag].asof(t_start)
            v_stop = calcDf[tag].asof(t_stop)
            gross = v_stop - v_start
            # Calculate exclusions
            total_excl = 0
            for s, e in zip(ex_starts, ex_ends):
                ts_s = datetime.combine(file_date, datetime.strptime(s, "%H:%M").time())
                ts_e = datetime.combine(file_date, datetime.strptime(e, "%H:%M").time())
                total_excl += (calcDf[tag].asof(ts_e) - calcDf[tag].asof(ts_s))

            # Get conversion factor from dfCons
            conv = tag_info_df[tag_info_df['Tag'] == tag]['ConversionFactor'].values[0]
            conv = 1 if pd.isna(conv) else conv
            final_val = round((gross - total_excl) * conv, 3)
            
            results.append({
                "Tag": tag,
                "Description": tag_info_df[tag_info_df['Tag'] == tag]['Description'].values[0],
                "Value": final_val,
                "MeasurementUnit": tag_info_df[tag_info_df['Tag'] == tag]['MeasurementUnit'].values[0]
            })

        return False, {"display": "block"}, results, dbc.Alert("✅ Calcolo terminato su {} file.".format(len(file_paths)), color="success"), clamp_warn
    except Exception as e:
        return False, no_update, no_update, dbc.Alert(f"Errore: {str(e)}", color="danger"), no_update

@callback(
    Output('storage-info', 'data', allow_duplicate=True),
    Input('btn-calculate', 'n_clicks'),
    [State('storage-info', 'data'),
     State('time-start-comp', 'value'),
     State('time-stop-comp', 'value'),
     State({'type': 'exclude-start', 'index': ALL}, 'value'),
     State({'type': 'exclude-end', 'index': ALL}, 'value'),
     State({'type': 'exclude-reason', 'index': ALL}, 'value')], # Added state
    prevent_initial_call=True
)
def sync_params_to_storage(n, current_info, start_val, stop_val, ex_starts, ex_ends, ex_reasons):
    if not n or current_info is None:
        return no_update
    
    current_info['comp_start'] = start_val
    current_info['comp_stop'] = stop_val
    current_info['exclusions'] = [
        {'start': s, 'stop': e, 'reason': r} # Added reason to dictionary
        for s, e, r in zip(ex_starts, ex_ends, ex_reasons)
    ]
    
    return current_info

@callback(
    Output("btn-calculate", "disabled"),
    Output("btn-calculate", "title"),
    Input("selected-tags-store", "data"),
    prevent_initial_call=True
)
def toggle_modal_btn(selected_tags):
    if not selected_tags:
        return True, "Seleziona almeno una tag"
    return False, ""

@callback(
    Output("download-text", "data"),
    Input("btn-export-txt", "n_clicks"),
    State("cons-results-grid", "virtualRowData"),
    State("storage-info", "data"),
    prevent_initial_call=True
)
def export_formatted_text(n, grid_data, info):
    if not n or not grid_data:
        return None

    df = pd.DataFrame(grid_data)
    info = info or {}
    output = io.StringIO()
    
    # --- HEADER ---
    output.write("--- Info ---\n")
    output.write(f"Campagna:   {info.get('campaign', 'N/A')}\n")
    output.write(f"Cliente:    {info.get('customer', 'N/A')}\n")
    output.write("-" * 30 + "\n\n")
    
    # --- TIME LOG ---
    output.write("TIME LOG:\n")
    output.write(f"  [Accensione COMP]  {info.get('comp_start', '--:--:--')}\n")
    
    exclusions_list = info.get('exclusions', [])
    if exclusions_list:
        for i, slot in enumerate(exclusions_list, 1):
            s = slot.get('start', 'N/A')
            e = slot.get('stop', 'N/A')
            r = slot.get('reason', '')
            reason_str = f" | Motivo: {r}" if r else ""
            output.write(f"  [EXCL{i}]  {s} to {e}{reason_str}\n")
    else:
        output.write("  [EXCL ]  None\n")
        
    output.write(f"  [Spegnimento COMP ]  {info.get('comp_stop', '--:--:--')}\n")
    output.write("\n\n")
    
    # ... rest of the table formatting logic ...
    # (Same as your original code)
    w_tag, w_desc, w_val, w_unit = 35, 60, 15, 15
    header = "TAG".ljust(w_tag) + "DESCRIZIONE".ljust(w_desc) + "VALUE".ljust(w_val) + "UNIT".ljust(w_unit) + "\n"
    output.write(header)
    output.write("-" * (w_tag + w_desc + w_val + w_unit) + "\n")
    
    for _, row in df.iterrows():
        val = row.get('Value')
        val_str = f"{val:.3f}" if isinstance(val, (int, float)) else str(val or "")
        line = (
            str(row.get('Tag', '')).ljust(w_tag) +
            str(row.get('Description', '')).ljust(w_desc) +
            val_str.ljust(w_val) +
            str(row.get('MeasurementUnit', '')).ljust(w_unit) + "\n"
        )
        output.write(line)
    
    content = output.getvalue()
    output.close()
    filename = f"Report_{info.get('campaign', 'Export')}.txt".replace(" ", "_")
    return dcc.send_string(content, filename)

#region functions
def load_and_process_binaries(file_paths, selected_tags, config_metadata):
    """
    Load and merge data from multiple binary files.
    Each file gets its own metadata loaded to handle potential structural differences.
    
    Returns a single concatenated DataFrame sorted by timestamp.
    """
    analog_channels = config_metadata.get('analog_channels', [])
    tag_to_sid = {ch['tag']: ch['sid'] for ch in analog_channels if ch['tag'] in selected_tags}
    target_sids = list(tag_to_sid.values())

    if not target_sids:
        raise ValueError("Nessun SID corrispondente trovato per i tag selezionati.")

    all_dfs = []
    total_clamped = 0
    
    for file_path in file_paths:
        if not os.path.exists(file_path):
            continue
        
        try:
            # Load per-file metadata to handle potential structural differences
            file_config = dp.get_wbin_metadata(file_path)
            
            # Build per-file tag_to_sid in case channel order differs
            file_analog = file_config.get('analog_channels', [])
            file_tag_to_sid = {ch['tag']: ch['sid'] for ch in file_analog if ch['tag'] in selected_tags}
            file_target_sids = list(file_tag_to_sid.values())
            
            if not file_target_sids:
                continue
            
            # Read data from this file (no time slicing - load all, filter after merge)
            raw_df = dp.read_wbin_data(file_path, file_target_sids, file_config)
            if raw_df.empty:
                continue
            
            # Count and clamp negative values
            total_clamped += (raw_df < 0).sum().sum()
            raw_df = raw_df.clip(lower=0)
            
            # Rename SID columns to tag names for this file
            file_sid_to_tag = {v: k for k, v in file_tag_to_sid.items()}
            raw_df.rename(columns=file_sid_to_tag, inplace=True)
            
            all_dfs.append(raw_df)
        except Exception as e:
            # Skip files that fail to load, continue with others
            continue
    
    if not all_dfs:
        return pd.DataFrame(), 0
    
    # Concatenate all DataFrames
    merged_df = pd.concat(all_dfs, ignore_index=False)
    
    # Sort by datetime index to ensure proper chronological order
    merged_df = merged_df.sort_index()
    
    return merged_df, total_clamped


def load_and_process_binary(file_path, selected_tags, config_metadata, t_start=None, t_stop=None):
    analog_channels = config_metadata.get('analog_channels', [])
    tag_to_sid = {ch['tag']: ch['sid'] for ch in analog_channels if ch['tag'] in selected_tags}
    target_sids = list(tag_to_sid.values())

    if not target_sids:
        raise ValueError("Nessun SID corrispondente trovato per i tag selezionati.")

    # A. Read the data
    raw_df = dp.read_wbin_data(file_path, target_sids, config_metadata, t_start, t_stop)
    
    if raw_df.empty:
        return raw_df, 0

    # B. Calculate n_clamped outside (values < 0)
    n_clamped = (raw_df < 0).sum().sum()
    
    # C. Apply the clamp
    raw_df = raw_df.clip(lower=0) 
    
    # D. Final mapping
    sid_to_tag = {v: k for k, v in tag_to_sid.items()}
    raw_df.rename(columns=sid_to_tag, inplace=True)
    
    return raw_df, n_clamped

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

def calculate_cumulative_data(raw_df, selected_tags_info):
    """
    raw_df: Index is Datetime, columns are Tags.
    selected_tags_info: Dataframe/List containing 'Tag' and 'Algorithm'.
    """
    calcDf = pd.DataFrame(index=raw_df.index)
    
    # Calculate time delta in hours for Alg 1 integration
    # (Assuming indices are sorted datetimes)
    time_deltas = raw_df.index.to_series().diff().dt.total_seconds() #removed 3600 for seconds
    time_deltas = time_deltas.fillna(0)

    for _, row in selected_tags_info.iterrows():
        tag = row['Tag']
        alg = row['Algorithm']
        
        if tag not in raw_df.columns:
            continue
            
        if alg == 1:
            # INSTANTANEOUS -> CUMULATIVE
            # Integration: Sum(Value * Delta_t)
            instant_values = raw_df[tag]
            incremental_cons = instant_values * time_deltas
            calcDf[tag] = incremental_cons.cumsum()
        else:
            # ALREADY CUMULATIVE
            calcDf[tag] = raw_df[tag]
    return calcDf















