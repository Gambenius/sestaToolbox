import dash
from dash import dcc, html, Input, Output, State, callback, ALL, MATCH, no_update
import dash_bootstrap_components as dbc
import pandas as pd
import os
from datetime import datetime
from utils import data_processor as dp
import dash_ag_grid as dag 


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
    # RESULTS PREVIEW
    html.Div(id="cons-results-container", children=[
        html.Div([
            dbc.Row([
                dbc.Col(html.H5("Risultati Calcolo Consumi", className="text-success"), width=True),
                dbc.Col(dbc.Button("📥 Scarica CSV", id="btn-export-csv", color="outline-success", size="sm"), width="auto"),
            ], align="center", className="mb-2"),
            
            dag.AgGrid(
                id="cons-results-grid",
                columnDefs=[
                    {"field": "Tag", "headerName": "TAG", "checkboxSelection": False},
                    {"field": "Description", "headerName": "DESCRIZIONE", "flex": 2},
                    {"field": "Value", "headerName": "VALUE", "valueFormatter": 'params.value ? params.value : ""'},
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

    # MASTER SELECT ALL (Full Width)
    dbc.Card([
        dbc.CardBody(
            dbc.Checkbox(
                id="master-select-all",
                label="SELEZIONA TUTTI I GRUPPI",
                value=False,
                className="fw-bold text-primary"
            )
        )
    ], className="mb-4 border-primary shadow-sm"),

    # The groups will be injected here as a dbc.Row with 2 Cols
    html.Div(id="groups-container"),
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
     Output("cons-status-msg", "children", allow_duplicate=True)],
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

# @callback(
#     [Output("cons-results-inner", "style"),
#      Output("cons-results-grid", "rowData"),
#      Output("cons-status-msg", "children", allow_duplicate=True)],
#     Input("btn-calculate", "n_clicks"),
#     [State("time-start-comp", "value"),
#      State("time-stop-comp", "value"),
#      State({'type': 'exclude-start', 'index': ALL}, 'value'),
#      State({'type': 'exclude-end', 'index': ALL}, 'value'),
#      State("selected-tags-store", "data"),
#      State("cons-selected-path", "data")],
#     prevent_initial_call=True
# )
# def run_calculations(n, start_comp, stop_comp, ex_starts, ex_ends, selected_tags, file_path):
#     if not file_path:
#         return no_update, no_update, dbc.Alert("⚠️ Carica prima un file binario!", color="danger")
#     if not selected_tags:
#         return no_update, no_update, dbc.Alert("⚠️ Seleziona almeno un tag!", color="warning")

#     # --- Time Validations (from previous step) ---
#     if start_comp >= stop_comp:
#         return no_update, no_update, dbc.Alert("❌ Errore Orario Compressore", color="danger")
    
#     # Check for increasing order in exclusions
#     for i in range(len(ex_starts) - 1):
#         if ex_ends[i] > ex_starts[i+1]:
#             return no_update, no_update, dbc.Alert(f"❌ Errore Sequenza Esclusioni", color="danger")

#     # --- Prepare AG Grid Data ---
#     # Filter the main dataframe for the selected tags
#     results_df = dfCons[dfCons['Tag'].isin(selected_tags)].copy()
    
#     # Initialize the "Value" column as empty for now
#     results_df['Value'] = "" 
    
#     # Convert to dictionary for AG Grid
#     grid_data = results_df.to_dict('records')

#     # Show the grid container and update data
#     return {"display": "block"}, grid_data, dbc.Alert("✅ Calcolo completato. Risultati pronti.", color="success")


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
    [Output("cons-results-inner", "style"),
     Output("cons-results-grid", "rowData"),
     Output("cons-status-msg", "children", allow_duplicate=True)],
    Input("btn-calculate", "n_clicks"),
    [State("time-start-comp", "value"),
     State("time-stop-comp", "value"),
     State({'type': 'exclude-start', 'index': ALL}, 'value'),
     State({'type': 'exclude-end', 'index': ALL}, 'value'),
     State("selected-tags-store", "data"),
     State("cons-selected-path", "data"),
     State("cons-config-store", "data")], # Metadata needed for SID mapping
    prevent_initial_call=True
)
def cb_calculate_consumi(n, start_t, stop_t, ex_starts, ex_ends, selected_tags, file_path, config_meta):
    if not file_path or not selected_tags or not config_meta:
        return no_update, no_update, dbc.Alert("⚠️ Carica file e seleziona i tag.", color="warning")

    try:
        # A. Load data using mapping
        raw_df = load_and_process_binary(file_path, selected_tags, config_meta)
        
        # B. Get tag metadata (Algorithms)
        tag_info_df = dfCons[dfCons['Tag'].isin(selected_tags)]
        
        # C. Create Cumulative Dataframe (calcDf)
        calcDf = calculate_cumulative_data(raw_df, tag_info_df)

        # D. Slicing Math
        file_date = raw_df.index[0].date()
        t_start = datetime.combine(file_date, datetime.strptime(start_t, "%H:%M").time())
        t_stop = datetime.combine(file_date, datetime.strptime(stop_t, "%H:%M").time())

        results = []
        for tag in selected_tags:
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
            final_val = round((gross - total_excl) * conv, 3)
            
            results.append({
                "Tag": tag,
                "Description": tag_info_df[tag_info_df['Tag'] == tag]['Description'].values[0],
                "Value": final_val,
                "MeasurementUnit": tag_info_df[tag_info_df['Tag'] == tag]['MeasurementUnit'].values[0]
            })

        return {"display": "block"}, results, dbc.Alert("✅ Calcolo terminato.", color="success")

    except Exception as e:
        return no_update, no_update, dbc.Alert(f"Errore: {str(e)}", color="danger")


#region functions
def load_and_process_binary(file_path, selected_tags, config_metadata):
    analog_channels = config_metadata.get('analog_channels', [])
    tag_to_sid = {ch['tag']: ch['sid'] for ch in analog_channels if ch['tag'] in selected_tags}
    target_sids = list(tag_to_sid.values())

    if not target_sids:
        raise ValueError("Nessun SID corrispondente trovato per i tag selezionati.")

    raw_df = dp.read_wbin_data(file_path, target_sids, config_metadata)
    
    sid_to_tag = {v: k for k, v in tag_to_sid.items()}
    raw_df.rename(columns=sid_to_tag, inplace=True)
    return raw_df

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
    time_deltas = raw_df.index.to_series().diff().dt.total_seconds() / 3600.0
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
    print(calcDf.head())
    return calcDf