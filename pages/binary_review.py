import os, re, struct
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd
import plotly.graph_objects as go

import dash
from dash import html, dcc, callback, Input, Output, State, no_update, Patch
import dash_bootstrap_components as dbc
import dash_daq as daq
import dash_ag_grid as dag
from utils import data_processor as dp


# Registrazione della pagina
dash.register_page(__name__, path="/wbin")


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


n_pts = 1000 #shown in plots

NETWORK_BASE_PATH = r"\\10.33.126.101\archivi\TOTALE\PROVE"
# NETWORK_BASE_PATH = r"/home/edoardo/Documenti/sestaToolbox/data"

PRESETS_FILE = "utils/lists/binrev_presets.txt"
# ─────────────────────────────────────────────────────────────────
# 1. LOGICA DI ESTRAZIONE METADATI (Mantenuta e rifinita)
# ─────────────────────────────────────────────────────────────────



# ─────────────────────────────────────────────────────────────────
# 2. LAYOUT LIGHT MODE (Bootstrap Standard)
# ─────────────────────────────────────────────────────────────────

layout = dbc.Container([
    dcc.Store(id='wbin-config-store'),
    dcc.Store(id='wbin-zoom-store', data={'start': 0, 'end': None}),
    dcc.Store(id='wbin-selected-path'),
    dcc.Download(id="download-csv"),
    dcc.Store(id='wbin-selected-row-store', data=None),
    dcc.Store(id='wbin-color-edit-store', data=None),
    dcc.Store(id="wbin-selected-tag-store"),
    dcc.Store(id='wbin-axis-config', data={'1': {'min': None, 'max': None}}),
    dcc.Store(id='wbin-axis-definitions-store', data={'1': {'name': 'Primary', 'range': 'Auto', 'style': 'solid'}}),
    dcc.Store(id='wbin-info-table-store'),
    dcc.Store(id='wbin-x-range-store'),
    dcc.Store(id='wbin-y-ranges-store'),
    dcc.Store(id='wbin-redraw-store'),
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Configurazione Assi")),
        dbc.ModalBody([
            dag.AgGrid(
                id='wbin-axis-config-grid',
                columnDefs=[
                    {"headerName": "ID", "field": "id", "width": 60, "editable": False},
                    {
                        "headerName": "Preset",
                        "field": "preset",
                        "editable": True,
                        "width": 100,
                        "cellEditor": "agSelectCellEditor",
                        "cellEditorParams": {"values": list(AXIS_PRESETS.keys())},
                    },
                    {"headerName": "Nome", "field": "name", "editable": True},
                    {"headerName": "Range Min", "field": "rangeMIN", "editable": True, "width": 100},
                    {"headerName": "Range Max", "field": "rangeMAX", "editable": True, "width": 100},
                ],
                rowData=[{'id': '1', 'name': 'Asse 1', 'preset': 'Custom', 'rangeMIN': '', 'rangeMAX': ''}],
                dashGridOptions={
                    "singleClickEdit": True,
                    "stopEditingWhenCellsLoseFocus": True,
                }
            ),
            dbc.Button("+ Aggiungi Asse", id="wbin-add-axis-row", color="link", size="sm")
        ]),
        dbc.ModalFooter(dbc.Button("Salva e Chiudi", id="wbin-close-axis-modal", color="primary"))
    ], id="wbin-axis-modal", size="lg"),
    dbc.Modal(id='wbin-color-picker-modal', children=[
        dbc.ModalHeader(dbc.ModalTitle("Seleziona Colore")),
        daq.ColorPicker(
                id='wbin-color-input',
                # label='Color Picker',
                value=dict(hex="#0000FF"),
            ),
        dbc.ModalFooter(dbc.Button("Conferma", id="wbin-color-confirm", color="primary"))
    ]),
    dbc.Row([
        # Sidebar
        dbc.Col([
            html.Div([
                html.H4("Lettore archiviazioni binarie", className="text-primary mb-4"),
                
                dbc.Button(
                    "📂 SELEZIONA BINARIO",
                    id="wbin-btn-open-modal",
                    color="primary",
                    # outline=True,
                    className="w-100 mb-3",
                ),

                # Modal per selezione file da rete
                dbc.Modal(
                    [
                        dbc.ModalHeader(dbc.ModalTitle("Seleziona File Binario da Rete")),
                        dbc.ModalBody([
                            html.Label("Seleziona Data (Cartella YYYY-MM-DD):", className="fw-bold mb-2"),
                            dcc.DatePickerSingle(
                                id="wbin-date-picker",
                                date=datetime.now().date(),
                                min_date_allowed=datetime(1990, 1, 1),
                                max_date_allowed=datetime.now().date()+ timedelta(days=7),
                                className="mb-3",
                            ),
                            html.Label("File .bin disponibili:", className="fw-bold mb-2"),
                            dcc.Dropdown(
                                id="wbin-file-dropdown",
                                options=[],
                                placeholder="Seleziona una data per caricare i file...",
                                className="mb-3",
                            ),
                            html.Div(
                                id="wbin-file-info-modal",
                                className="small text-muted mb-3",
                            ),
                        ]),
                        dbc.ModalFooter([
                            dbc.Button(
                                "❌ Chiudi",
                                id="wbin-btn-close-modal",
                                color="secondary",
                                className="me-2",
                            ),
                            dbc.Button(
                                "✅ Carica File Selezionato",
                                id="wbin-btn-load-file",
                                color="primary",
                                disabled=True,
                            ),
                        ]),
                    ],
                    id="wbin-file-modal",
                    backdrop="static",
                    size="lg",
                ),
                
                # Box Info File e Metadati (Sfondo chiaro, testo scuro)
                html.Div(id="wbin-file-info", children=[
                    dbc.Card([
                        dbc.CardBody([
                            html.P("Al momento carica solo da ARCHIVI/TOTALE/PROVE", className="text-muted small mb-0")
                        ])
                    ], className="bg-light")
                ], className="mb-3"),
                
                html.Label("Cerca Canale:", className="small fw-bold"),
                dcc.Dropdown(
                    id='wbin-tag-dropdown',
                    multi=True,
                    placeholder="Cerca (es. 004*PV)...",
                    className="mb-4",
                    options=[],
                    searchable=True,
                    maxHeight=500,     
                    optionHeight=35
                ),
                dbc.Button("Mostra grafico", id="wbin-btn-plot", color="primary", className="w-100 mb-3"),
                
                html.Div(id="wbin-status-msg"),

                dcc.Dropdown(id='preset-dropdown', placeholder="Seleziona un Preset...", className="mb-4"   ),

                dbc.Input(id='new-preset-name', placeholder="Nome nuovo preset...", type="text", className="mb-4"),

                dbc.Button("Salva selezione corrente", id='save-preset-btn', color="primary",className="w-100 mb-3"),
                html.Div([
                    html.H4("Esportazione CSV", className="text-primary mb-4"),
                    
                    # Riga per gli input affiancati
                    dbc.Row([
                        dbc.Col([
                            dbc.Input(id='start-timecut', placeholder="HH:MM:SS", type="text")
                        ], width=5),
                        dbc.Col([
                            html.Span("-", className="fw-bold")
                        ], width=2, className="text-center d-flex align-items-center justify-content-center"),
                        dbc.Col([
                            dbc.Input(id='end-timecut', placeholder="HH:MM:SS", type="text")
                        ], width=5),
                    ], className="mb-4 g-0"), # g-0 rimuove lo spazio eccessivo tra le colonne (gutter)
                    dbc.Button("Esporta selezione come CSV", id='save-csv-btn', color="primary", className="w-100 mb-3"),
                    html.Div(id="csv-status-msg", className="small")
                ], style={'padding': '0px', 'borderTop': '1px solid #ddd'})
            ], style={'padding': '20px', 'borderRight': '1px solid #ddd', 'minHeight': '90vh'})
        ],id="wbin-sidebar-col", width=3),
        
        # Grafico
        dbc.Col([
            dcc.Loading(
                html.Div(
                    dcc.Graph(
                        id='wbin-main-graph', 
                        style={'height': '100%', 'width': '100%'} # Importante: occupa tutto il div
                    ),
                    style={
                        'height': '80vh',          # Altezza iniziale
                        'minHeight': '300px',      # Altezza minima
                        'overflow': 'hidden',      # Necessario per il resize
                        'resize': 'vertical',      # Abilita il trascinamento dal bordo inferiore
                        'borderBottom': '2px solid #ddd', # Un piccolo bordo per far capire dove trascinare
                        'paddingBottom': '5px',
                        'if': {'state': 'active'},
                        'backgroundColor': '#e8f0fe', # Un azzurrino molto tenue quando la cella è attiva
                        'border': '1px solid #4C78A8'
                    }
                ),
                type="default"
            ),
            dbc.Row([
                dbc.Col(dbc.Button("⚙️ CONFIGURA ASSI", id="wbin-btn-axis-modal", color="secondary", outline=True, size="sm"), width="auto"),
                dbc.Col(html.Small("Usa la colonna 'Asse' per raggruppare i canali", className="text-muted"), className="text-end me-auto"),
                dbc.Col([
                    dbc.InputGroup([
                        dbc.Button("−", id="wbin-btn-fontsize-down", color="secondary", outline=True, size="sm"),
                        dbc.Input(id="wbin-fontsize-input", type="text", value="10",
                                    debounce=True,   # ← fires only on Enter or blur
                                    size="sm", style={"width": "52px", "textAlign": "center"}),
                        dbc.Button("+", id="wbin-btn-fontsize-up", color="secondary", outline=True, size="sm"),
                    ], size="sm"),
                ], width="auto"),
                dbc.Col(dbc.Button("🔍 Autoscale Y", id="wbin-btn-autoscale", color="secondary", outline=True, size="sm"), width="auto"),
                dbc.Col(dbc.Button("📄 Salva come PDF", id="wbin-btn-export-pdf", color="secondary", outline=True, size="sm"), width="auto"),
                dcc.Download(id='wbin-download-pdf'),
            ], className="my-2 align-items-center g-2"),
            dag.AgGrid(
                id='wbin-info-table',
                dangerously_allow_code=True,
                # columnSize="responsiveSizeToFit",
                columnDefs=[
                    {
                        "headerName": "🎨   ",
                        "field": "color",
                        "width": 60,
                        "resizable": False,
                        "suppressSizeToFit": True,  # keeps it exactly 60px
                    },
                    {
                        "headerName": "Tag",
                        "field": "tag",
                        "singleClickEdit": True, 
                        "resizable": True,
                        "editable": True,
                        "flex": 1,
                        "cellStyle": {
                            "styleConditions": [
                                {
                                    "condition": "params.data._selected === true",
                                    "style": {"fontWeight": "bold"}
                                }
                            ]
                        }
                    },
                    {
                        "headerName": "Descrizione",
                        "field": "desc",
                        "resizable": True,
                        "flex": 2,  # fills remaining space
                        "cellStyle": {
                            "styleConditions": [
                                {
                                    "condition": "params.data._selected === true",
                                    "style": {"fontWeight": "bold"}
                                }
                            ]
                        }
                    },
                    {
                        "headerName": "Valore",
                        "field": "cur_val",
                        "width": 100,
                        "resizable": True,
                        "cellStyle": {
                            "styleConditions": [
                                {
                                    "condition": "params.data._selected === true",
                                    "style": {"fontWeight": "bold", "textAlign": "right"}
                                }
                            ],
                            "defaultStyle": {"textAlign": "right"}
                        }
                    },
                    {
                        "headerName": "Asse",
                        "field": "axis_sel",
                        "singleClickEdit": True, 
                        "editable": True,
                        "cellEditor": "agSelectCellEditor",
                        "cellEditorParams": {"values": AXIS_DROPDOWN_OPTIONS},
                        "width": 100,
                    },
                    {
                        "headerName": "Rimuovi",
                        "field": "delete-row",
                        "width": 90,
                        "suppressSizeToFit": False,
                        "resizable": False,
                        "cellStyle": {
                            "cursor": "pointer",
                            "textAlign": "center",
                            "color": "red",
                            "fontWeight": "bold"
                        }
                    }
                ],

                defaultColDef={
                    "resizable": True,
                    "sortable": False,
                    "filter": False,
                },

                rowData=[],

                dashGridOptions={
                    # replaces your bold selected_tag logic
                    "rowClassRules": {
                        "selected-row": "params.data.tag === selectedTag"
                    }
                }
            )
        ], id="wbin-main-col", width=9, style={"position": "relative"})
    ], className="mt-3")
], fluid=True, style={'backgroundColor': '#f8f9fa', 'minHeight': '100vh'})

# ─────────────────────────────────────────────────────────────────
# 3. CALLBACKS
# ─────────────────────────────────────────────────────────────────

def format_file_size(size_bytes: int) -> str:
    """Converte byte in formato leggibile (KB, MB, GB)."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def list_bin_files(folder_path: str) -> list:
    """Restituisce lista di file .bin con nome, data e dimensione."""
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

def chunks_in_order(chunks, haystack):
    pos = 0
    for chunk in chunks:
        idx = haystack.find(chunk, pos)
        if idx == -1:
            return False
        pos = idx + len(chunk)
    return True


# --- CALLBACK: APRI MODAL ---
@callback(
    Output('wbin-file-modal', 'is_open'),
    Input('wbin-btn-open-modal', 'n_clicks'),
    Input('wbin-btn-close-modal', 'n_clicks'),
    Input('wbin-btn-load-file', 'n_clicks'),
    State('wbin-file-modal', 'is_open'),
    prevent_initial_call=True
)
def cb_toggle_modal(open_n, close_n, load_n, is_open):
    ctx = dash.callback_context
    if not ctx.triggered:
        return False
    prop = ctx.triggered[0]['prop_id']
    if prop == 'wbin-btn-open-modal.n_clicks':
        return True
    # Chiude sempre il modal (chiusura o caricamento)
    return False

@callback(
    [Output('wbin-file-dropdown',  'options'),
     Output('wbin-file-dropdown',  'value'),  
     Output('wbin-file-info-modal','children')],
    [Input('wbin-date-picker', 'date'),
     Input('wbin-file-modal', 'is_open')],
    State('wbin-date-picker', 'date'),
    prevent_initial_call=True
)
def cb_list_files(date_str, is_open, date_str_state):
    trigger = dash.callback_context.triggered[0]['prop_id'].split('.')[0]

    # Use state date when triggered by modal open
    if trigger == 'wbin-file-modal':
        if not is_open:
            return no_update, no_update, no_update  # ← add third

    if not date_str:
        return [], None, ""  

    dt          = datetime.strptime(date_str, '%Y-%m-%d')
    folder_name = dt.strftime('%Y%m%d')
    folder_path = os.path.join(NETWORK_BASE_PATH, folder_name)
    files       = list_bin_files(folder_path)

    if not files:
        return [], None, html.Div("Nessun file .bin trovato nella cartella.", className="text-danger small")

    auto_select = files[0]['value'] if len(files) == 1 else None

    return files, auto_select, html.Div(f"{len(files)} file .bin trovati in {folder_name}", className="text-success small")

# --- CALLBACK: FILE SELEZIONATO → ABILITA PULSANTE CARICA ---
@callback(
    [Output('wbin-btn-load-file', 'disabled'),
     Output('wbin-selected-path', 'data')],
    Input('wbin-file-dropdown', 'value'),
    prevent_initial_call=True
)
def cb_select_file(selected_path):
    if selected_path:
        return False, selected_path
    return True, None

# --- CALLBACK: CARICA FILE SELEZIONATO (stessa logica di prima) ---
@callback(
    [Output('wbin-config-store', 'data'),
     Output('wbin-file-info', 'children'),
     Output('wbin-status-msg', 'children')],
    Input('wbin-btn-load-file', 'n_clicks'),
    State('wbin-selected-path', 'data'),
    prevent_initial_call=True
)
def cb_load_file(n_clicks, selected_path):
    if not selected_path or not os.path.exists(selected_path):
        return no_update, no_update, dbc.Alert("File non valido o non trovato.", color="danger", className="small")
    try:
        cfg = dp.get_wbin_metadata(selected_path)
        n_analog = cfg.get('n_analog', 0)
        n_digital = len(cfg.get('digital_channels', []))
        m = cfg.get('meta', {'campaign': 'N/A', 'customer': 'N/A', 'coordinator': 'N/A'})

        info_content = dbc.Card([
            dbc.CardHeader("INFORMAZIONI FILE", className="fw-bold small"),
            dbc.CardBody([
                html.Div([
                    html.P([html.B("File: "), os.path.basename(selected_path)], className="mb-1 small"),
                    html.P([html.B("Quantità dati: "), f"{cfg['total_blocks']:,}"], className="mb-1 small"),
                    html.P([html.B("Canali analogici: "), str(n_analog)], className="mb-1 small"),
                    html.P([html.B("Canali digitali: "), str(n_digital)], className="mb-3 small"),
                ]),
                html.Hr(),
                html.Div([
                    html.Label("CAMPAIGN", className="text-primary fw-bold", style={'fontSize': '10px'}),
                    html.P(m.get('campaign', 'N/A'), className="small mb-2"),
                    html.Label("CUSTOMER", className="text-primary fw-bold", style={'fontSize': '10px'}),
                    html.P(m.get('customer', 'N/A'), className="small mb-2"),
                    html.Label("COORDINATOR", className="text-primary fw-bold", style={'fontSize': '10px'}),
                    html.P(m.get('coordinator', 'N/A'), className="small"),
                ])
            ])
        ], className="shadow-sm")

        return cfg, info_content, dbc.Alert("✓ Caricato", color="success", className="py-1 px-2 small text-center")
    except Exception as e:
        return no_update, no_update, dbc.Alert(f"Errore: {str(e)}", color="danger", className="small")

@callback(
    Output('wbin-tag-dropdown', 'options'),
    Input('wbin-tag-dropdown', 'search_value'),
    State('wbin-tag-dropdown', 'value'),
    State('wbin-config-store', 'data')
)
def cb_filter_tags(search, selected_values, cfg):
    # Se non c'è un file caricato, svuota il menu
    if not cfg: 
        return []
    
    # 1. RECUPERO OPZIONI SELEZIONATE (Per non perderle alla chiusura)
    final_options = []
    if selected_values:
        for sid in selected_values:
            v_type, v_idx = sid.split('_')
            idx = int(v_idx)
            # Scegliamo la lista giusta in base al prefisso
            ch_list = cfg['analog_channels'] if v_type == 'A' else cfg['digital_channels']
            if idx < len(ch_list):
                ch = ch_list[idx]
                final_options.append({
                    'label': f"[{v_type}] {ch['tag']} - {ch.get('desc', '')[:35]}", 
                    'value': sid
                })

    # 2. PREPARAZIONE LISTA UNIFICATA PER LA RICERCA
    # Creiamo un "librone" unico dove cercare, mettendo un'etichetta A o D
    search_pool = []
    for i, ch in enumerate(cfg['analog_channels']):
        search_pool.append({'info': ch, 'sid': f"A_{i}", 'type': 'A'})
    for i, ch in enumerate(cfg['digital_channels']):
        search_pool.append({'info': ch, 'sid': f"D_{i}", 'type': 'D'})

    # 3. GESTIONE RICERCA E ASTERISCHI
    # Se l'utente non sta scrivendo, mostriamo solo i selezionati + i primi 20 analogici
    if not search:
        existing_ids = [opt['value'] for opt in final_options]
        for item in search_pool[:20]:
            if item['sid'] not in existing_ids:
                final_options.append({
                    'label': f"[{item['type']}] {item['info']['tag']}", 
                    'value': item['sid']
                })
        return final_options

    # Logica Chunks per l'asterisco (es: "004*PV" -> ["004", "PV"])
    s = search.upper().strip()
    chunks = [c.strip() for c in s.split('*') if c.strip()]
    
    matches = []
    for item in search_pool:
        ch = item['info']
        # Testo su cui cercare: Tag + Descrizione
        target_text = f"{ch['tag']} {ch.get('desc', '')}".upper()
        
        # Un canale passa il filtro se contiene TUTTI i pezzi cercati
        if chunks and chunks_in_order(chunks, target_text):
            matches.append({
                # Il (search) alla fine serve a ingannare il filtro client di Dash
                'label': f"[{item['type']}] {ch['tag']} - {ch.get('desc', '')[:35]} ({search})",
                'value': item['sid']
            })
            
        # Limite per non rallentare il browser (max 100 risultati)
        if len(matches) >= 100: 
            break

    # 4. UNIONE RISULTATI
    current_ids = [opt['value'] for opt in final_options]
    for m in matches:
        if m['value'] not in current_ids:
            final_options.append(m)
            
    return final_options

# ─────────────────────────────────────────────────────────────────
# CALLBACK PRINCIPALE: RENDER GRAFICO + INIZIALIZZAZIONE TABELLA
# ─────────────────────────────────────────────────────────────────

@callback(
    Output("wbin-axis-config-grid", "rowData", allow_duplicate=True),
    Input("wbin-add-axis-row", "n_clicks"),
    State("wbin-axis-config-grid", "rowData"),
    prevent_initial_call=True
)
def add_axis_row(n, rows):
    if not rows: rows = []
    new_id = str(max([int(r['id']) for r in rows]) + 1) if rows else "1"
    rows.append({'id': new_id, 'name': f'Asse {new_id}', 'range': 'Auto', 'style': 'solid'})
    return rows

# ─────────────────────────────────────────────────────────────────
# CALLBACK CLICK: POSIZIONA CURSORE + AGGIORNA VALORI TABELLA
# ─────────────────────────────────────────────────────────────────
@callback(
    [Output('wbin-info-table', 'rowData', allow_duplicate=True),
     Output('wbin-main-graph', 'figure', allow_duplicate=True)],
    Input('wbin-main-graph', 'clickData'),
    [State('wbin-info-table', 'rowData'),
     State('wbin-main-graph', 'figure')],
    prevent_initial_call=True
)
def update_on_click(clickData, current_table, fig):
    if not clickData or not current_table or not fig:
        return no_update, no_update

    clicked_x = clickData['points'][0]['x']
    clicked_dt = datetime.fromisoformat(clicked_x)

    for row in current_table:
        tag = row['tag']
        val = "---"
        for trace in fig['data']:
            if trace.get('name') and tag in trace['name']:
                try:
                    x_vals = [datetime.fromisoformat(v) if isinstance(v, str) else v for v in trace['x']]
                    if clicked_dt in x_vals:
                        idx = x_vals.index(clicked_dt)
                        y_val = trace['y'][idx]
                        val = f"{y_val:.3f}"
                except:
                    pass
                break
        row['cur_val'] = val

    # 3. Crea la linea verticale (Cursore)
    cursor_line = {
        'type': 'line',
        'x0': clicked_x, 'x1': clicked_x,
        'y0': 0, 'y1': 1, 'yref': 'paper',
        'line': {
            'color': 'red',
            'width': 2,
            'dash': 'dot',
        }
    }
    
    # Aggiorna il layout della figura esistente con la nuova shape
    fig['layout']['shapes'] = [cursor_line]
    fig['layout']['uirevision'] = 'constant' # Fondamentale per non perdere lo zoom

    return current_table, fig

@callback(
    Output('wbin-zoom-store', 'data'),
    Input('wbin-main-graph', 'relayoutData'),
    State('wbin-config-store', 'data'),
    prevent_initial_call=True
)
def update_zoom_limits(relayout_data, cfg):
    if not cfg: return no_update
    
    # Se l'utente fa doppio clic (reset)
    if not relayout_data or 'xaxis.autorange' in relayout_data or 'autosize' in relayout_data:
        return {'start': 0, 'end': cfg['total_blocks'] - 1}
    
    # Se l'utente zooma
    if 'xaxis.range[0]' in relayout_data:
        # Il grafico usa il tempo (stringhe), ma noi dobbiamo convertirlo in indici di blocco
        # Un trucco semplice: se l'asse X è basato su indici o tempi, 
        # Plotly restituisce i valori visibili. 
        # Se i tuoi dati sono a 1Hz, possiamo mappare i tempi o usare gli indici.
        return no_update # Gestiremo lo zoom direttamente nella callback di plot
    
    return no_update

# ─────────────────────────────────────────────────────────────────
# 4. GESTIONE PRESET (Salvataggio su File e Caricamento)
# ─────────────────────────────────────────────────────────────────


def save_preset_to_file(title, tags):
    with open(PRESETS_FILE, "a") as f:
        f.write(f"\n")
        f.write(f"{title.upper()}\n{{\n")
        for tag in tags:
            f.write(f"{tag}\n")
        f.write("}\n")

def load_presets_from_file():
    """Carica i preset dal file di testo."""
    if not os.path.exists(PRESETS_FILE):
        return {}
    
    presets = {}
    with open(PRESETS_FILE, "r") as f:
        lines = f.readlines()
        
    current_title = None
    current_tags = []
    in_block = False
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith("{"):
            in_block = True
        elif line.startswith("}"):
            if current_title:
                presets[current_title] = current_tags
            current_tags = []
            in_block = False
        elif in_block:
            current_tags.append(line)
        else:
            current_title = line
    return presets

def get_sid_from_tagname(tagname, cfg):
    """Trova l'ID (A_x o D_x) partendo dal nome del tag."""
    tagname = tagname.strip().upper()
    # Cerca tra gli analogici
    for i, ch in enumerate(cfg.get('analog_channels', [])):
        if ch['tag'].upper() == tagname:
            return f"A_{i}"
    # Cerca tra i digitali
    for i, ch in enumerate(cfg.get('digital_channels', [])):
        if ch['tag'].upper() == tagname:
            return f"D_{i}"
    return None

def get_tagname_from_sid(sid, cfg):
    """Trova il nome del tag partendo dall'ID (A_x o D_x)."""
    try:
        v_type, v_idx = sid.split('_')
        idx = int(v_idx)
        if v_type == 'A':
            return cfg['analog_channels'][idx]['tag']
        else:
            return cfg['digital_channels'][idx]['tag']
    except:
        return None
# --- CALLBACKS PRESET ---

# --- CALLBACK 1: AGGIORNA IL MENU DEI PRESET APPENA SALVI ---
@callback(
    Output('preset-dropdown', 'options'),
    [Input('save-preset-btn', 'n_clicks'),
     Input('wbin-config-store', 'data')], # Si aggiorna anche quando carichi un nuovo file
    prevent_initial_call=False
)
def update_preset_dropdown(n, cfg):
    presets = load_presets_from_file()
    return [{'label': k, 'value': k} for k in presets.keys()]

# --- CALLBACK 2: SALVA E TRADUCI ---
@callback(
    Output('new-preset-name', 'value'),
    Input('save-preset-btn', 'n_clicks'),
    State('new-preset-name', 'value'),
    State('wbin-tag-dropdown', 'value'),
    State('wbin-config-store', 'data'),
    prevent_initial_call=True
)
def save_current_selection(n_clicks, name, current_selection, cfg):
    if not n_clicks or not name or not current_selection or not cfg:
        return no_update
    
    human_tags = []
    for sid in current_selection:
        tag_name = get_tagname_from_sid(sid, cfg)
        if tag_name:
            human_tags.append(tag_name)
    
    save_preset_to_file(name, human_tags)
    return "" 

# --- CALLBACK 3: APPLICA IL PRESET E FORZA LE OPZIONI ---
@callback(
    [Output('wbin-tag-dropdown', 'value'),
     Output('wbin-tag-dropdown', 'options', allow_duplicate=True)], # IMPORTANTE: allow_duplicate
    Input('preset-dropdown', 'value'),
    [State('wbin-config-store', 'data'),
     State('wbin-tag-dropdown', 'options')],
    prevent_initial_call=True
)
def apply_preset(preset_name, cfg, current_options):
    if not preset_name or not cfg:
        return no_update, no_update
    
    presets = load_presets_from_file()
    selected_tagnames = presets.get(preset_name, [])
    
    new_selection_ids = []
    new_options = list(current_options) if current_options else []
    existing_ids = [o['value'] for o in new_options]
    
    for tagname in selected_tagnames:
        sid = get_sid_from_tagname(tagname, cfg)
        if sid:
            new_selection_ids.append(sid)
            # Se l'ID non è tra le opzioni correnti, dobbiamo aggiungerlo 
            # altrimenti il dropdown non lo mostrerà/selezionerà
            if sid not in existing_ids:
                new_options.append({
                    'label': f"{tagname} (da preset)", 
                    'value': sid
                })
            
    return new_selection_ids, new_options


# --- GESTIONE CSV E ESPORTAZIONE
def time_to_seconds(t_str):
    """Converte HH:MM:SS in secondi totali."""
    try:
        # Rimuove tutto ciò che non è numero o :
        t_str = re.sub(r'[^0-9:]', '', t_str)
        h, m, s = map(int, t_str.split(':'))
        return h * 3600 + m * 60 + s
    except:
        return None

# --- CALLBACK 1: SINCRONIZZAZIONE ZOOM -> INPUT TESTO ---
@callback(
    [Output('start-timecut', 'value'),
     Output('end-timecut', 'value')],
    [Input('wbin-config-store', 'data'),
     Input('wbin-main-graph', 'relayoutData')],
    [State('wbin-main-graph', 'figure')],
    prevent_initial_call=True
)
def sync_export_range(cfg, relayout_data, fig):
    ctx = dash.callback_context
    if not ctx.triggered: return no_update, no_update
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # SE CARICHI UN NUOVO FILE
    if trigger_id == 'wbin-config-store' and cfg:
        return cfg.get('start_time', ''), cfg.get('end_time', '')

    # SE INTERAGISCI COL GRAFICO
    if trigger_id == 'wbin-main-graph' and relayout_data:
        # TASTO HOME O RESET
        if 'xaxis.autorange' in relayout_data or 'autosize' in relayout_data:
            if cfg:
                return cfg.get('start_time', ''), cfg.get('end_time', '')
        
        # ZOOM MANUALE
        if 'xaxis.range[0]' in relayout_data:
            try:
                x_start = datetime.fromisoformat(relayout_data['xaxis.range[0]'])
                x_end = datetime.fromisoformat(relayout_data['xaxis.range[1]'])
                t_s = f"{x_start.hour:02d}:{x_start.minute:02d}:{x_start.second:02d}"
                t_e = f"{x_end.hour:02d}:{x_end.minute:02d}:{x_end.second:02d}"
                return t_s, t_e
            except Exception as e:
                print(f"Errore sync zoom: {e}")
                return no_update, no_update

    return no_update, no_update

# --- CALLBACK 2: GENERAZIONE E DOWNLOAD CSV ---
@callback(
    [Output("download-csv", "data"),
     Output("csv-status-msg", "children")],
    Input("save-csv-btn", "n_clicks"),
    [State('start-timecut', 'value'),
     State('end-timecut', 'value'),
     State('wbin-tag-dropdown', 'value'),
     State('wbin-config-store', 'data')],
    prevent_initial_call=True
)
def export_csv(n_clicks, t_start_raw, t_end_raw, selected_sids, cfg):
    if not n_clicks or not selected_sids or not cfg:
        return no_update, "Carica un file e seleziona canali."

    # 1. Validazione Orari
    s_sec = time_to_seconds(t_start_raw)
    e_sec = time_to_seconds(t_end_raw)
    
    if s_sec is None or e_sec is None:
        return no_update, dbc.Alert("Formato HH:MM:SS non valido!", color="warning")
    if s_sec >= e_sec:
        return no_update, dbc.Alert("Start deve essere prima di End!", color="danger")

    # 2. Estrazione Integrale (Tutti i punti nel range)
    # Prepariamo le colonne del CSV
    headers = ["Time"] + [get_tagname_from_sid(sid, cfg) for sid in selected_sids]
    rows = []
    today = date.today()

    # Read first block to get start time for block index calculation
    with open(cfg['path'], 'rb') as f:
        f.seek(cfg['data_offset'])
        first_record = f.read(cfg['block_size'])
    h0, m0, s0 = first_record[4], first_record[5], first_record[6]
    start_dt = datetime(today.year, today.month, today.day, h0, m0, s0)
    start_sec = h0 * 3600 + m0 * 60 + s0

    rows = []
    with open(cfg['path'], 'rb') as f:
        for b_idx in range(cfg['total_blocks']):
            f.seek(cfg['data_offset'] + (b_idx * cfg['block_size']))
            record = f.read(cfg['block_size'])
            if len(record) < cfg['block_size']:
                break
            h, m, s = record[4], record[5], record[6]
            curr_sec = h * 3600 + m * 60 + s

            if curr_sec < s_sec: continue
            if curr_sec > e_sec: break

            row = [f"{h:02d}:{m:02d}:{s:02d}"]
            for sid in selected_sids:
                v_type, v_idx = sid.split('_')
                idx = int(v_idx)
                if v_type == 'A':
                    offset = 13 + (idx * 4)
                    val = struct.unpack('>f', record[offset:offset+4])[0]
                    row.append(val)
                else:
                    ch = cfg['digital_channels'][idx]
                    dig_base = 13 + (cfg['n_analog'] * 4)
                    group_offset = dig_base + (ch['group'] * 4)
                    full_word = struct.unpack('<I', record[group_offset:group_offset+4])[0]
                    row.append((full_word >> ch['bit']) & 1)
            rows.append(row)

    if not rows:
        return no_update, "Nessun dato trovato nel range."

    # 3. Creazione DataFrame e Invio
    df = pd.DataFrame(rows, columns=headers)
    return dcc.send_data_frame(df.to_csv, "export_data.csv", index=False), f"Esportati {len(rows)} record."

# --- TABELLE E GRAFICA
@callback(
    Output('wbin-info-table', 'columnDefs'),
    Input('wbin-info-table', 'rowData'),
    State('wbin-info-table', 'columnDefs'),
)
def update_color_column_style(row_data, col_defs):
    if not row_data:
        return col_defs
    
    # Get unique colors currently in the data
    colors = list({row['color'] for row in row_data if row.get('color')})
    
    # Build styleConditions for each color
    style_conditions = [
        {
            "condition": f"params.value === '{c}'",
            "style": {"backgroundColor": c, "color": c}
        }
        for c in colors
    ]
    
    # Update just the color column
    for col in col_defs:
        if col.get('field') == 'color':
            col['cellStyle'] = {
                "styleConditions": style_conditions,
                "defaultStyle": {"backgroundColor": "white", "color": "white"}
            }
    
    return col_defs


# CALLBACK PER SALVARE IL NUOVO COLORE SELEZIONATO
@callback(
    [Output('wbin-info-table', 'rowData', allow_duplicate=True),
     Output('wbin-color-picker-modal', 'is_open', allow_duplicate=True),
     Output('wbin-redraw-store', 'data', allow_duplicate=True)],  # ← add
    Input('wbin-color-confirm', 'n_clicks'),
    [State('wbin-color-input', 'value'),
     State('wbin-color-edit-store', 'data'),
     State('wbin-info-table', 'rowData')],
    prevent_initial_call=True
)
def update_row_color(n_clicks, color_value, row_idx, current_rows):
    if n_clicks is None or row_idx is None:
        return no_update, False, no_update

    new_hex = "#0000FF"
    if isinstance(color_value, dict) and 'hex' in color_value:
        new_hex = color_value['hex']
    elif isinstance(color_value, str):
        new_hex = color_value

    if row_idx < len(current_rows):
        new_rows = [row.copy() for row in current_rows]
        new_rows[row_idx]['color'] = new_hex
        ping = {"ts": datetime.now().isoformat(), "reason": "color"}
        return new_rows, False, ping  

    return no_update, False, no_update

@callback(
    Output('wbin-main-graph', 'figure', allow_duplicate=True),
    Input('wbin-info-table', 'rowData'),
    State('wbin-main-graph', 'figure'),
    prevent_initial_call=True
)
def sync_table_color_to_graph(table_data, fig):
    if not table_data or not fig:
        return no_update

    color_map = {row['tag']: row['color'] for row in table_data}

    for trace in fig['data']:
        tag_name = trace.get('name', '')
        if tag_name in color_map:
            trace['line']['color'] = color_map[tag_name]

    fig['layout']['uirevision'] = 'constant'
    return fig


# ------------- NEW SHIT

# ─── CONSTANTS ────────────────────────────────────────────────────────────────



# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _ax_key(aid_int):
    """Plotly axis key from integer axis id."""
    return "yaxis" if aid_int == 1 else f"yaxis{aid_int}"

def _read_blocks(cfg, start_block, end_block, selected_indices, start_dt, n_pts=500):
    """Read binary file and return (time_axis, data_dict)."""
    actual_range  = max(1, end_block - start_block)
    block_indices = np.linspace(start_block, end_block,
                                min(n_pts, actual_range + 1)).astype(int)
    data_dict = {sid: [] for sid in selected_indices}
    time_axis = []
    with open(cfg['path'], 'rb') as f:
        for b_idx in block_indices:
            f.seek(cfg['data_offset'] + int(b_idx) * cfg['block_size'])
            record = f.read(cfg['block_size'])
            if len(record) < cfg['block_size']:
                break
            time_axis.append(start_dt + timedelta(seconds=int(b_idx)))
            for sid in selected_indices:
                v_type, v_idx = sid.split('_')
                idx = int(v_idx)
                if v_type == 'A':
                    val = struct.unpack('>f', record[13+(idx*4):13+(idx*4)+4])[0]
                    data_dict[sid].append(val if abs(val) < 1e15 else 0.0)
                else:
                    ch = cfg['digital_channels'][idx]
                    raw = record[13+(cfg['n_analog']*4)+(ch['group']*4):
                                 13+(cfg['n_analog']*4)+(ch['group']*4)+4]
                    data_dict[sid].append((struct.unpack('<I', raw)[0] >> ch['bit']) & 1)
    return time_axis, data_dict

def _build_figure(current_rows, time_axis, data_dict, ax_map, y_store, font_size=10):
    fig          = go.Figure()
    linewidth    = 1.5 * (1 + (font_size - 10) * 0.10)
    used_ids_int = sorted(set(int(r['axis_id']) for r in current_rows))
    num_subplots = len(used_ids_int)
    spacing      = 0.08
    p_height     = (1.0 - spacing * max(1, num_subplots - 1)) / max(1, num_subplots)

    for row in current_rows:
        aid = str(row['axis_id'])
        fig.add_trace(go.Scattergl(
            x=time_axis, y=data_dict[row['sid']], name=row['tag'],
            yaxis=f"y{aid}" if aid != '1' else "y",
            line=dict(color=row['color'], width=linewidth),
            showlegend=False,
            hovertemplate=f"<b>{row['tag']}</b>: %{{y:.3f}}<extra></extra>"
        ))

    layout = {
        "template":      "plotly_white",
        "font": {"size": font_size},
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

    for i, aid_int in enumerate(used_ids_int):
        aid     = str(aid_int)
        ak      = _ax_key(aid_int)
        ref_key = "y" if aid == '1' else f"y{aid}"

        start_y = max(0.0, 1.0 - (i + 1) * p_height - i * spacing)
        end_y   = min(1.0, start_y + p_height)
        mid_y   = start_y + p_height / 2

        # DIY legend
        subplot_rows = [r for r in current_rows if int(r['axis_id']) == aid_int]
        for j, row in enumerate(subplot_rows):
            y_off = (len(subplot_rows) / 2 - j) * 0.035
            layout["annotations"].append(dict(
                x=1.02, y=mid_y + y_off,
                xref="paper", yref="paper",
                text=f"<b>{row['tag']}</b>",
                showarrow=False,
                font=dict(color=row['color'], size=font_size),
                xanchor="left"
            ))

        conf = ax_map.get(aid, {})

        # Y range priority: y_store (drag/modal) > preset > autoscale
        stored = y_store.get(ak) if y_store else None

        if isinstance(stored, list) and len(stored) == 2 and None not in stored:
            y_range   = stored
            autorange = False
        elif stored == "auto":
            # Explicitly autoscaled — skip preset entirely
            y_range   = None
            autorange = True
        else:
            # No entry yet — fall back to preset
            try:
                y_range   = [float(conf['rangeMIN']), float(conf['rangeMAX'])]
                autorange = False
            except (ValueError, TypeError, KeyError):
                y_range   = None
                autorange = True

        ax_def = {
            "domain":         [start_y, end_y],
            "title":          {"text": conf.get('name', f'Asse {aid}'),
                            "font": {"size": font_size}},   # ← add
            "tickfont":       {"size": font_size},              # ← add
            "showgrid":       True,
            "showticklabels": True,
            "matches":        "x",
            "autorange":      autorange,
            "nticks":         5,    # ~4 gridlines (nticks includes the endpoints)
        }
        if y_range:
            ax_def["range"] = y_range


        layout[ak] = ax_def

        if i == num_subplots - 1:
            layout["xaxis"]["anchor"] = ref_key

    fig.update_layout(layout)
    fig.update_traces(xaxis="x")
    return fig


# ─── 1. TRACK X RANGE ─────────────────────────────────────────────────────────
# Job: keep wbin-x-range-store in sync with whatever x window the user sees.

@callback(
    Output('wbin-x-range-store', 'data'),
    Input('wbin-main-graph', 'relayoutData'),
    prevent_initial_call=True
)
def cb_track_x_range(relayout_data):
    if not relayout_data:
        return no_update
    if 'xaxis.range[0]' in relayout_data:
        return {
            'x0': str(relayout_data['xaxis.range[0]']).replace('Z', ''),
            'x1': str(relayout_data['xaxis.range[1]']).replace('Z', ''),
        }
    if relayout_data.get('xaxis.autorange'):
        return {}
    return no_update


# ─── 2. TRACK Y RANGES ────────────────────────────────────────────────────────
# Job: keep wbin-y-ranges-store in sync with y drags only.
# Does NOT touch the figure — just records what the user dragged to.

@callback(
    Output('wbin-y-ranges-store', 'data'),
    Input('wbin-main-graph', 'relayoutData'),
    State('wbin-y-ranges-store', 'data'),
    prevent_initial_call=True
)
def cb_track_y_ranges(relayout_data, current_store):
    if not relayout_data:
        return no_update

    has_y = any(k.startswith('yaxis') for k in relayout_data)
    if not has_y:
        return no_update

    store   = dict(current_store or {})
    updated = False

    for key, val in relayout_data.items():
        if '.range[' in key and key.startswith('yaxis'):
            ak  = key.split('.range[')[0]
            idx = int(key.split('[')[1].rstrip(']'))
            if not isinstance(store.get(ak), list):
                store[ak] = [None, None]
            store[ak][idx] = val
            updated = True
        elif key.startswith('yaxis') and '.autorange' in key:
            ak = key.split('.autorange')[0]
            store[ak] = None
            updated = True

    return store if updated else no_update


# ─── 3. AXIS ASSIGNMENT FROM INFO TABLE ───────────────────────────────────────
# Job: when user picks a preset or custom axis in the table:
#   - update info_rows with new axis_id
#   - update axis_config_grid with new axis entry if needed
#   - pre-populate y_store with preset range so the graph applies it immediately
#   - ping wbin-redraw-store to trigger graph redraw


@callback(
    [Output('wbin-info-table',       'rowData',  allow_duplicate=True),
     Output('wbin-axis-config-grid', 'rowData',  allow_duplicate=True),
     Output('wbin-y-ranges-store',   'data',     allow_duplicate=True),
     Output('wbin-redraw-store',     'data',     allow_duplicate=True)],
    Input('wbin-info-table', 'cellValueChanged'),
    [State('wbin-info-table',       'rowData'),
     State('wbin-axis-config-grid', 'rowData'),
     State('wbin-y-ranges-store',   'data')],
    prevent_initial_call=True
)
def cb_cell_value_changed(cell_changed, info_rows, axis_rows, y_store):
    if not cell_changed or not info_rows:
        return no_update, no_update, no_update, no_update

    changed = cell_changed[0]
    col_id  = changed.get('colId')

    # --- Tag edited ---
    if col_id == 'tag':
        new_tag = changed['value']
        row_sid = changed['data']['sid']
        new_rows = []
        for row in info_rows:
            row = dict(row)
            if row['sid'] == row_sid:
                row['tag'] = new_tag
            new_rows.append(row)
        ping = {"ts": datetime.now().isoformat(), "reason": "tag_edit"}
        return new_rows, no_update, no_update, ping

    # --- Axis assigned ---
    if col_id == 'axis_sel':
        selected  = changed['value']
        row_sid   = changed['data']['sid']
        axis_rows = [dict(r) for r in (axis_rows or [])]
        info_rows = [dict(r) for r in info_rows]
        y_store   = dict(y_store or {})

        if selected.isdigit():
            target_id    = int(selected) + 100
            existing_ids = [int(a['id']) for a in axis_rows]
            if target_id not in existing_ids:
                axis_rows.append({
                    "id": target_id, "preset": "Custom",
                    "name": f"Cust. {selected}", "rangeMIN": "", "rangeMAX": "",
                })
            ak = _ax_key(target_id)
            y_store[ak] = None
        else:
            preset        = AXIS_PRESETS.get(selected, {})
            existing_axis = next((a for a in axis_rows if a.get('preset') == selected), None)
            if existing_axis:
                target_id = int(existing_axis['id'])
            else:
                preset_ids = [int(a['id']) for a in axis_rows if int(a['id']) < 100]
                target_id  = max(preset_ids) + 1 if preset_ids else 1
                axis_rows.append({
                    "id": target_id, "preset": selected,
                    "name":     preset.get('name', ''),
                    "rangeMIN": preset.get('rangeMIN', ''),
                    "rangeMAX": preset.get('rangeMAX', ''),
                })
            ak = _ax_key(target_id)
            try:
                y_store[ak] = [float(preset['rangeMIN']), float(preset['rangeMAX'])]
            except (ValueError, TypeError, KeyError):
                y_store[ak] = None

        for row in info_rows:
            if row['sid'] == row_sid:
                row['axis_id']  = target_id
                row['axis_sel'] = selected
                break

        axis_rows = sorted(axis_rows, key=lambda x: int(x['id']))
        ping = {"ts": datetime.now().isoformat(), "reason": "axis_sel"}
        return info_rows, axis_rows, y_store, ping

    return no_update, no_update, no_update, no_update


# ─── 4. MAIN RENDER ───────────────────────────────────────────────────────────
# Triggers: plot button, x zoom, redraw store (axis assignment / delete)
# Never triggered by y drags.

@callback(
    [Output('wbin-main-graph',  'figure'),
     Output('wbin-info-table',  'rowData')],
    [Input('wbin-btn-plot',     'n_clicks'),
     Input('wbin-main-graph',   'relayoutData'),
     Input('wbin-redraw-store', 'data')],
    [State('wbin-tag-dropdown',    'value'),
     State('wbin-config-store',    'data'),
     State('wbin-info-table',      'rowData'),
     State('wbin-axis-config-grid','rowData'),
     State('wbin-x-range-store',   'data'),
     State('wbin-y-ranges-store',  'data'),
    State('wbin-fontsize-input',   'value')],
    prevent_initial_call=True
)
def cb_render_graph(n_clicks, relayout_data, redraw_store,
                    selected_indices, cfg, current_rows_state,
                    axis_defs, x_store, y_store,font_size):

    if not selected_indices or not cfg:
        return go.Figure(), []

    ctx     = dash.callback_context
    trigger = ctx.triggered[0]['prop_id'].split('.')[0]

    current_rows = list(current_rows_state or [])
    axis_rows    = list(axis_defs or [])

    # --- Start time ---
    with open(cfg['path'], 'rb') as f:
        f.seek(cfg['data_offset'])
        rec = f.read(cfg['block_size'])
    h0, m0, s0 = rec[4], rec[5], rec[6]
    today    = datetime.now().date()
    start_dt = datetime(today.year, today.month, today.day, h0, m0, s0)

    # --- Block range ---
    start_block, end_block = 0, cfg['total_blocks'] - 1

    if trigger == 'wbin-main-graph' and relayout_data:
        keys = set(relayout_data)

        # Pure y interaction — skip entirely, cb_track_y_ranges handles it
        y_only = ('yaxis', 'autosize')
        if all(any(k.startswith(p) for p in y_only) for k in keys):
            return no_update, no_update

        if 'xaxis.range[0]' in relayout_data:
            try:
                x0 = datetime.fromisoformat(relayout_data['xaxis.range[0]'].replace('Z',''))
                x1 = datetime.fromisoformat(relayout_data['xaxis.range[1]'].replace('Z',''))
                start_block = max(0, int((x0 - start_dt).total_seconds()))
                end_block   = min(cfg['total_blocks']-1, int((x1 - start_dt).total_seconds()))
            except:
                pass

    elif trigger == 'wbin-redraw-store':
        # Recover x window from store
        if x_store and x_store.get('x0'):
            try:
                x0 = datetime.fromisoformat(x_store['x0'])
                x1 = datetime.fromisoformat(x_store['x1'])
                start_block = max(0, int((x0 - start_dt).total_seconds()))
                end_block   = min(cfg['total_blocks']-1, int((x1 - start_dt).total_seconds()))
            except:
                pass

    # --- Row sync ---
    colors = ['#636EFA','#EF553B','#00CC96','#AB63FA',
              '#FFA15A','#19D3F3','#FF6692','#B6E880']
    new_rows = []
    for i, sid in enumerate(selected_indices):
        existing = next((r for r in current_rows if r.get('sid') == sid), None)
        if existing:
            existing = dict(existing)
            existing['axis_id'] = int(existing.get('axis_id', 1))
            new_rows.append(existing)
        else:
            v_type, v_idx = sid.split('_')
            idx     = int(v_idx)
            ch_info = (cfg['analog_channels'][idx] if v_type == 'A'
                       else cfg['digital_channels'][idx])
            new_rows.append({
                "sid":        sid,
                "tag":        ch_info['tag'],
                "desc":       ch_info.get('desc', 'N/A'),
                "axis_sel":   "1",
                "color":      colors[i % len(colors)],
                "axis_id":    1,
                "delete-row": "✘",
                "_selected":  False,
                "cur_val":    "",
            })
    current_rows = new_rows

    # --- Axis map ---
    used_ids     = set(int(r['axis_id']) for r in current_rows)
    existing_ids = set(int(a['id']) for a in axis_rows)
    for aid in used_ids:
        if aid not in existing_ids:
            axis_rows.append({
                "id": aid, "preset": "Custom",
                "name": f"Asse {aid}", "rangeMIN": "", "rangeMAX": "",
            })
    axis_rows = sorted(axis_rows, key=lambda x: int(x['id']))
    ax_map    = {str(a['id']): a for a in axis_rows}

    # --- Read data ---
    time_axis, data_dict = _read_blocks(
        cfg, start_block, end_block, selected_indices, start_dt
    )

    # --- Build figure (y_store is the single source of truth for ranges) ---
    fig = _build_figure(current_rows, time_axis, data_dict, ax_map, y_store,font_size=int(font_size or 10))
                        
    return fig, current_rows


# ─── 5. OPEN MODAL → SYNC GRID FROM Y STORE ───────────────────────────────────
# Job: when modal opens, write current y ranges from store into grid.
#      When modal closes, just close it (apply is a separate callback).

@callback(
    [Output('wbin-axis-modal',       'is_open'),
     Output('wbin-axis-config-grid', 'rowData', allow_duplicate=True)],
    [Input('wbin-btn-axis-modal',    'n_clicks'),
     Input('wbin-close-axis-modal',  'n_clicks')],
    [State('wbin-axis-modal',        'is_open'),
     State('wbin-axis-config-grid',  'rowData'),
     State('wbin-y-ranges-store',    'data')],
    prevent_initial_call=True
)
def cb_modal_open_close(open_clicks, close_clicks, is_open, axis_rows, y_store):
    trigger = dash.callback_context.triggered[0]['prop_id'].split('.')[0]

    if trigger == 'wbin-btn-axis-modal' and not is_open:
        if axis_rows:
            new_rows = []
            for row in axis_rows:
                row = dict(row)
                ak  = _ax_key(int(row['id']))
                stored = (y_store or {}).get(ak)
                if isinstance(stored, list) and len(stored) == 2 and None not in stored:
                    row['rangeMIN'] = f"{stored[0]:.4g}"
                    row['rangeMAX'] = f"{stored[1]:.4g}"
                new_rows.append(row)
            return True, new_rows
        return True, no_update

    return False, no_update


# ─── 6. CLOSE MODAL → APPLY TO Y STORE + PATCH FIGURE ────────────────────────
# Job: on Salva e Chiudi, write grid values into y store and patch figure.
#      y store becomes the source of truth for the new manual ranges.

@callback(
    [Output('wbin-y-ranges-store', 'data',   allow_duplicate=True),
     Output('wbin-main-graph',     'figure', allow_duplicate=True)],
    Input('wbin-close-axis-modal', 'n_clicks'),
    [State('wbin-axis-config-grid', 'rowData'),
     State('wbin-info-table',       'rowData'),
     State('wbin-main-graph',       'figure'),
     State('wbin-y-ranges-store',   'data')],
    prevent_initial_call=True
)
def cb_modal_save(n_clicks, axis_rows, info_rows, current_fig, y_store):
    if not n_clicks or not axis_rows or not current_fig:
        return no_update, no_update

    y_store      = dict(y_store or {})
    ax_map       = {str(a['id']): a for a in axis_rows}
    used_ids     = sorted(set(int(r['axis_id']) for r in (info_rows or [])))
    layout_patch = {}

    for aid_int in used_ids:
        aid  = str(aid_int)
        ak   = _ax_key(aid_int)
        conf = ax_map.get(aid, {})

        ax_update = {
            "title": {"text": conf.get('name', f'Asse {aid}'), "font": {"size": 12}}
        }

        try:
            rmin = float(conf['rangeMIN'])
            rmax = float(conf['rangeMAX'])
            ax_update["range"]     = [rmin, rmax]
            ax_update["autorange"] = False
            y_store[ak]            = [rmin, rmax]   # ← write into store
        except (ValueError, TypeError, KeyError):
            ax_update["autorange"] = True
            y_store[ak]            = None

        layout_patch[ak] = ax_update

    patched = go.Figure(current_fig)
    patched.update_layout(layout_patch)
    return y_store, patched


# ─── 7. PRESET IN AXIS CONFIG GRID ────────────────────────────────────────────
# Job: when preset dropdown is changed inside the modal grid,
#      auto-fill name and rangeMIN/MAX for that row.

@callback(
    Output('wbin-axis-config-grid', 'rowData', allow_duplicate=True),
    Input('wbin-axis-config-grid',  'cellValueChanged'),
    State('wbin-axis-config-grid',  'rowData'),
    prevent_initial_call=True
)
def cb_grid_preset_changed(cell_changed, axis_rows):
    if not cell_changed or not axis_rows:
        return no_update

    changed = cell_changed[0]
    if changed.get('colId') != 'preset':
        return no_update

    preset_key = changed['value']
    row_id     = str(changed['data']['id'])
    preset     = AXIS_PRESETS.get(preset_key)
    if not preset:
        return no_update

    new_rows = []
    for row in axis_rows:
        row = dict(row)
        if str(row['id']) == row_id:
            row['preset'] = preset_key
            if preset_key != 'Custom':
                row['name']     = preset['name']
                row['rangeMIN'] = preset['rangeMIN']
                row['rangeMAX'] = preset['rangeMAX']
        new_rows.append(row)
    return new_rows


# ─── 8. CELL CLICK: DELETE / COLOR / HIGHLIGHT ────────────────────────────────

@callback(
    [Output('wbin-info-table',        'rowData',  allow_duplicate=True),
     Output('wbin-main-graph',        'figure',   allow_duplicate=True),
     Output('wbin-tag-dropdown',      'value',    allow_duplicate=True),
     Output('wbin-selected-row-store','data'),
     Output('wbin-color-picker-modal','is_open'),
     Output('wbin-color-edit-store',  'data'),
     Output('wbin-color-input',       'value'),
     Output('wbin-redraw-store',      'data',     allow_duplicate=True)],
    Input('wbin-info-table', 'cellClicked'),
    [State('wbin-info-table',  'rowData'),
     State('wbin-main-graph',  'figure'),
     State('wbin-tag-dropdown','value'),
     State('wbin-config-store','data')],
    prevent_initial_call=True
)
def cb_cell_clicked(clicked, current_rows, fig, current_tags, cfg):
    nu = no_update
    if not clicked or not current_rows:
        return nu, nu, nu, nu, False, nu, nu, nu

    row_idx = clicked.get("rowIndex")
    col_id  = clicked.get("colId")

    if col_id in ('axis_sel', 'tag'):
        return nu, nu, nu, nu, False, nu, nu, nu

    if row_idx is None or row_idx >= len(current_rows):
        return nu, nu, nu, None, False, nu, nu, nu

    selected_tag = current_rows[row_idx]['tag']

    if col_id == 'delete-row':
        new_table = [r for i, r in enumerate(current_rows) if i != row_idx]
        if fig and 'data' in fig:
            fig['data'] = [t for t in fig['data']
                           if selected_tag not in t.get('name', '')]
        new_tags = [sid for sid in (current_tags or [])
                    if get_tagname_from_sid(sid, cfg) != selected_tag]
        ping = {"ts": datetime.now().isoformat(), "reason": "delete"}
        return new_table, fig, new_tags, None, False, None, None, ping

    elif col_id == 'color':
        current_color = current_rows[row_idx].get('color', '#0000FF')
        return nu, nu, nu, selected_tag, True, row_idx, {"hex": current_color}, nu

    else:
        if fig and 'data' in fig:
            for trace in fig['data']:
                trace['line']['width'] = (4 if selected_tag in trace.get('name','')
                                          else 1.5)
            fig['layout']['uirevision'] = 'static'
        new_rows = []
        for r in current_rows:
            r = dict(r)
            r['_selected'] = (r['tag'] == selected_tag)
            new_rows.append(r)
        return new_rows, fig, nu, selected_tag, False, None, None, nu
  
  # SAVE AND EXPORT PDF

@callback(
    Output('wbin-download-pdf', 'data'),
    Input('wbin-btn-export-pdf', 'n_clicks'),
    [State('wbin-main-graph', 'figure'),
     State('wbin-config-store', 'data'),
     State('wbin-date-picker', 'date')],
    prevent_initial_call=True
)
def cb_export_pdf(n_clicks, figure, cfg, date_str):
    if not n_clicks or not figure:
        return no_update
    date_part = date_str.replace('-', '_') if date_str else 'nodata'
    filename  = f"{date_part}_binrev.pdf"
    fig = go.Figure(figure)
    pdf = fig.to_image(format='pdf', width=1920, height=1080, scale=1)
    return dcc.send_bytes(pdf, filename=filename)

# autoscale y button
@callback(
    [Output('wbin-y-ranges-store', 'data',   allow_duplicate=True),
     Output('wbin-redraw-store',   'data',   allow_duplicate=True)],
    Input('wbin-btn-autoscale', 'n_clicks'),
    State('wbin-info-table', 'rowData'),
    prevent_initial_call=True
)
def cb_autoscale_y(n_clicks, info_rows):
    if not n_clicks:
        return no_update, no_update
    y_store = {}
    for row in (info_rows or []):
        ak = _ax_key(int(row['axis_id']))
        y_store[ak] = "auto"   # ← sentinel, not None, not a list
    return y_store, {"ts": datetime.now().isoformat(), "reason": "autoscale"}

# Change fontsize with buttons
    
@callback(
    Output('wbin-fontsize-input', 'value'),
    [Input('wbin-btn-fontsize-down', 'n_clicks'),
     Input('wbin-btn-fontsize-up',   'n_clicks'),
     Input('wbin-fontsize-input',    'value')],  # debounced, fires on Enter/blur
    prevent_initial_call=True
)
def cb_fontsize_buttons(down, up, typed):
    trigger = dash.callback_context.triggered[0]['prop_id'].split('.')[0]
    minSize = 6
    maxSize = 20
    if trigger == 'wbin-btn-fontsize-down':
        try:
            return str(max(minSize, int(typed or 10) - 1))
        except ValueError:
            return "10"
    if trigger == 'wbin-btn-fontsize-up':
        try:
            return str(min(maxSize, int(typed or 10) + 1))
        except ValueError:
            return "10"

    # Enter or blur — clamp
    try:
        return str(max(minSize, min(maxSize, int(typed))))
    except ValueError:
        return "10"
    

@callback(
    Output('wbin-main-graph', 'figure', allow_duplicate=True),
    Input('wbin-fontsize-input', 'value'),
    [State('wbin-main-graph', 'figure'),
     State('wbin-info-table', 'rowData')],
    prevent_initial_call=True
)
def cb_apply_fontsize(font_size, figure, info_rows):
    if not figure or not font_size:
        return no_update

    fs        = int(font_size)
    linewidth = 1.5 * (1 + (fs - 10) * 0.10)

    patched = Patch()   # ← from dash import Patch

    patched['layout']['font']                    = {"size": fs}
    patched['layout']['xaxis']['title']['font']  = {"size": fs}
    patched['layout']['xaxis']['tickfont']       = {"size": fs}

    # Yaxes
    old_layout = figure.get('layout', {})
    for key in old_layout:
        if key.startswith('yaxis'):
            patched['layout'][key]['title']['font'] = {"size": fs}
            patched['layout'][key]['tickfont']      = {"size": fs}

    # Annotations (DIY legend)
    old_annotations = old_layout.get('annotations', [])
    new_annotations = []
    for ann in old_annotations:
        ann = dict(ann)
        ann['font'] = dict(ann.get('font', {}))
        ann['font']['size'] = fs
        new_annotations.append(ann)
    patched['layout']['annotations'] = new_annotations

    # Traces
    for i in range(len(figure.get('data', []))):
        patched['data'][i]['line']['width'] = linewidth

    return patched

# @callback(
#     [Output('wbin-sidebar-col',    'width'),
#      Output('wbin-sidebar-col',    'style'),
#      Output('wbin-main-col',       'width'),
#      Output('wbin-sidebar-toggle', 'children')],
#     Input('wbin-sidebar-toggle', 'n_clicks'),
#     prevent_initial_call=True
# )
# def cb_toggle_sidebar(n_clicks):
#     if n_clicks and n_clicks % 2 == 1:
#         # Collapsed
#         return 0, {"display": "none"}, 12, "▶"
#     # Expanded
#     return 3, {"display": "block"}, 9, "◀"


