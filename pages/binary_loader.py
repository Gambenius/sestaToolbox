import os, re, struct
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd
import plotly.graph_objects as go

import dash
from dash import html, dcc, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc
import dash_daq as daq
import dash_ag_grid as dag


# Registrazione della pagina
dash.register_page(__name__, path="/wbin")

AXIS_PRESETS = {
    "bar H":   {"name": "pressione [bar]",   "rangeMIN": "0",   "rangeMAX": "200"},
    "bar L":   {"name": "pressione [bar]",   "rangeMIN": "0",   "rangeMAX": "10"},
    "mbar":    {"name": "pressione [mbar]",  "rangeMIN": "0",   "rangeMAX": "1000"},
    "kgs H":   {"name": "portata [kg/s]",    "rangeMIN": "0",   "rangeMAX": "30"},
    "kgs L":   {"name": "portata [kg/s]",    "rangeMIN": "0",   "rangeMAX": "1"},
    "gs H":    {"name": "portata [g/s]",     "rangeMIN": "0",   "rangeMAX": "1000"},
    "CH":      {"name": "temperatura [°C]",  "rangeMIN": "0",   "rangeMAX": "2000"},
    "CL":      {"name": "temperatura [°C]",  "rangeMIN": "0",   "rangeMAX": "100"},
    "Amp":     {"name": "corrente [A]",      "rangeMIN": "0",   "rangeMAX": "200"},
    "Volt":    {"name": "Tensione [V]",      "rangeMIN": "0",   "rangeMAX": "400"},
}

PRESET_OPTIONS = [{"label": k, "value": k} for k in AXIS_PRESETS]
AXIS_DROPDOWN_OPTIONS = list(AXIS_PRESETS.keys()) + ["1", "2", "3", "4", "5"]
n_pts = 1000 #shown in plots

# NETWORK_BASE_PATH = r"\\10.33.126.101\archivi\TOTALE\PROVE"
NETWORK_BASE_PATH = r"/home/edoardo/Documenti/sestaToolbox/data"

PRESETS_FILE = "utils/binrev_presets.txt"
# ─────────────────────────────────────────────────────────────────
# 1. LOGICA DI ESTRAZIONE METADATI (Mantenuta e rifinita)
# ─────────────────────────────────────────────────────────────────

def get_wbin_metadata(path):
    MARKER = b'[END]'
    MARKER_DIG = '[DIGITAL]'
    
    with open(path, 'rb') as f:
        blob = f.read(2048 * 1024)
    
    cuts = [m.start() for m in re.finditer(re.escape(MARKER), blob)]
    if len(cuts) < 2:
        raise ValueError("Marker [END] non trovati.")

    # ───── HEADER PARTS (CRITICAL) ─────
    part1 = blob[:cuts[0]].decode('latin-1', errors='ignore')
    part2 = blob[cuts[0]:cuts[1]].decode('latin-1', errors='ignore')

    lines = part1.split('\n')   # only \n

    # ───── CAMPAIGN ─────
    campaign_info = {"campaign": "N/A", "customer": "N/A", "coordinator": "N/A"}
    if lines:
        parts = [p.strip() for p in lines[0].split('\t') if p.strip()]
        if len(parts) >= 4:
            campaign_info = {
                "campaign": parts[1],
                "customer": parts[2],
                "coordinator": parts[3]
            }

    # ───── ANALOG ─────
    analog_channels = []
    hdr_map = {}
    parsing_analog = False

    for line in lines:
        cols = [c.strip() for c in line.split('\t')]
        
        if 'Tag' in cols:
            hdr_map = {col: i for i, col in enumerate(cols)}
            parsing_analog = True
            continue
        
        if parsing_analog and len(cols) > 1:
            tag = cols[hdr_map.get('Tag', 0)].upper()
            if tag:
                analog_channels.append({
                    'tag': tag,
                    'unit': cols[hdr_map.get('EU', 1)] if 'EU' in hdr_map else "",
                    'desc': cols[hdr_map.get('Comment', 2)] if 'Comment' in hdr_map else ""
                })

    # ───── DIGITAL (MAPPATURA TAG <-> DESCRIZIONE) ─────
    digital_channels = []
    group_idx = 0

    for line in part2.split('\n'):
        line = line.strip()
        if not line or MARKER_DIG in line.upper() or not line.upper().startswith('DIGITAL'):
            continue
        
        cols = line.split('\t')
        
        # Cerchiamo la colonna dei tag (quella con le virgole)
        try:
            v_col = next((i for i, c in enumerate(cols) if ',' in c), 1)
        except StopIteration:
            continue 

        if v_col < len(cols):
            # Split dei TAG (es. Z50XL108, Z50XU108...)
            tags = [t.strip() for t in cols[v_col].split(',') if t.strip()]
            
            # Split delle DESCRIZIONI (es. Min ecc statica..., Reg ecc...)
            # Usiamo la colonna successiva v_col + 1
            descs = []
            if len(cols) > (v_col + 1):
                descs = [d.strip() for d in cols[v_col + 1].split(',')]

            for bit_idx, tag in enumerate(tags[:32]):
                # Prendiamo la descrizione corrispondente per indice
                # Se per qualche motivo il file ha meno descrizioni dei tag, evitiamo il crash
                current_desc = descs[bit_idx] if bit_idx < len(descs) else ""
                
                digital_channels.append({
                    'tag': tag.upper(),
                    'group': group_idx,
                    'bit': bit_idx,
                    'type': 'D',
                    'desc': current_desc # <--- ECCOLA QUI!
                })
            
            group_idx += 1

    # ───── OFFSET (USE VERSION 2 LOGIC) ─────
    match = re.search(r'#(\d{9})', part1)
    data_offset = int(match.group(1)) if match else 0

    # ───── BLOCK SIZE (CRITICAL FIX) ─────
    n_analog = len(analog_channels)

    # use REAL digital word count (NOT parsed groups)
    n_uint32 = len([l for l in part2.split('\n') if ',' in l and '\t' in l])

    block_size = 13 + (n_analog * 4) + (n_uint32 * 4)

    total_blocks = (os.path.getsize(path) - data_offset) // block_size
    file_size = os.path.getsize(path)

    # 4. Estrazione orari dal binario
    with open(path, 'rb') as f:
        # Orario d'inizio
        f.seek(data_offset)
        s_rec = f.read(7)
        t_start = f"{s_rec[4]:02d}:{s_rec[5]:02d}:{s_rec[6]:02d}"
        
        # Orario di fine (Usa file_size e block_size appena definiti)
        f.seek(file_size - block_size)
        e_rec = f.read(7)
        t_end = f"{e_rec[4]:02d}:{e_rec[5]:02d}:{e_rec[6]:02d}"
    return {
        'path': path,
        'data_offset': data_offset,
        'block_size': block_size,
        'total_blocks': total_blocks,
        'n_analog': n_analog,
        'analog_channels': analog_channels,
        'digital_channels': digital_channels,
        'meta': campaign_info,
        'start_time': t_start,
        'end_time': t_end,
    }

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
        ], width=3),
        
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
                dbc.Col(dbc.Button("⚙️ CONFIGURA ASSI", id="wbin-btn-axis-modal", color="secondary", outline=True, size="sm"), width=3),
                dbc.Col(html.Small("Usa la colonna 'Asse' per raggruppare i canali", className="text-muted"), width=9, className="text-end")
            ], className="my-2"),
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
                        "resizable": True,
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
        ], width=9)
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

# --- CALLBACK: DATA → LISTA FILE .BIN ---
@callback(
    [Output('wbin-file-dropdown', 'options'),
     Output('wbin-file-info-modal', 'children')],
    Input('wbin-date-picker', 'date'),
    prevent_initial_call=True
)
def cb_list_files(date_str):
    if not date_str:
        return [], ""
    # date_str è ISO "YYYY-MM-DD"
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    folder_name = dt.strftime('%Y%m%d')
    folder_path = os.path.join(NETWORK_BASE_PATH, folder_name)
    files = list_bin_files(folder_path)
    if not files:
        return [], html.Div("Nessun file .bin trovato nella cartella.", className="text-danger small")
    return files, html.Div(f"{len(files)} file .bin trovati in {folder_name}", className="text-success small")

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
        cfg = get_wbin_metadata(selected_path)
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
        if all(chunk in target_text for chunk in chunks) or not chunks:
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
    Output('wbin-axis-config-grid', 'rowData', allow_duplicate=True),
    Input('wbin-axis-config-grid', 'cellValueChanged'),
    State('wbin-axis-config-grid', 'rowData'),
    prevent_initial_call=True
)
def cb_apply_axis_preset(cell_changed, axis_rows):
    if not cell_changed or not axis_rows:
        return dash.no_update

    # cellValueChanged is a list with one entry
    changed = cell_changed[0]
    if changed.get('colId') != 'preset':
        return dash.no_update

    preset_key = changed['value']
    row_id = str(changed['data']['id'])
    preset = AXIS_PRESETS.get(preset_key)
    if not preset:
        return dash.no_update

    new_rows = []
    for row in axis_rows:
        if str(row['id']) == row_id:
            row = dict(row)  # don't mutate in place
            row['preset'] = preset_key
            if preset_key != 'Custom':
                # Only overwrite name/range if not custom
                row['name'] = preset['name']
                row['rangeMIN'] = preset['rangeMIN']
                row['rangeMAX'] = preset['rangeMAX']
        new_rows.append(row)

    return new_rows

@callback(
    Output('wbin-main-graph', 'figure', allow_duplicate=True),
    Input('wbin-close-axis-modal', 'n_clicks'),
    [State('wbin-main-graph', 'figure'),
     State('wbin-axis-config-grid', 'rowData'),
     State('wbin-info-table', 'rowData')],
    prevent_initial_call=True
)
def cb_apply_axis_config(n_clicks, current_fig, axis_rows, info_rows):
    if not n_clicks or not current_fig or not axis_rows:
        return dash.no_update

    ax_map = {str(a['id']): a for a in axis_rows}
    layout_patch = {}

    # Collect which axis IDs are actually used
    used_ids = sorted(set(int(r['axis_id']) for r in (info_rows or [])))

    for aid_int in used_ids:
        aid = str(aid_int)
        ax_key = "yaxis" if aid == '1' else f"yaxis{aid}"
        conf = ax_map.get(aid, {})

        axis_update = {
            "title": {"text": conf.get('name', f'Asse {aid}'), "font": {"size": 12}}
        }

        # Apply range only if both min and max are valid numbers
        range_min = conf.get('rangeMIN', '')
        range_max = conf.get('rangeMAX', '')
        try:
            axis_update["range"] = [float(range_min), float(range_max)]
            axis_update["autorange"] = False
        except (ValueError, TypeError):
            axis_update["autorange"] = True  # fallback to auto if blank/invalid

        layout_patch[ax_key] = axis_update

    # Patch figure layout in-place — no data re-read
    patched = go.Figure(current_fig)
    patched.update_layout(layout_patch)
    return patched

@callback(
    Output('wbin-axis-config-grid', 'rowData'),
    Input('wbin-info-table', 'rowData'),
    State('wbin-axis-config-grid', 'rowData'),
    prevent_initial_call=True
)
def cb_sync_axis_rows(info_rows, axis_rows):
    if not info_rows:
        return dash.no_update

    axis_rows = [dict(r) for r in (axis_rows or [])]
    used_ids = set(int(r['axis_id']) for r in info_rows)
    existing_ids = set(int(a['id']) for a in axis_rows)

    changed = False
    for aid in used_ids:
        if aid not in existing_ids:
            axis_rows.append({
                "id": aid,
                "preset": "Custom",
                "name": f"Asse {aid}",
                "rangeMIN": "",
                "rangeMAX": "",
            })
            changed = True

    if not changed:
        return dash.no_update

    return sorted(axis_rows, key=lambda x: int(x['id']))


@callback(
    [Output('wbin-main-graph', 'figure'),
     Output('wbin-info-table', 'rowData')],
    [Input('wbin-btn-plot', 'n_clicks'),
     Input('wbin-main-graph', 'relayoutData'),
     Input('wbin-info-table-store', 'data')],  # ← was cellValueChanged
    [State('wbin-tag-dropdown', 'value'),
     State('wbin-config-store', 'data'),
     State('wbin-info-table', 'rowData'),
     State('wbin-axis-config-grid', 'rowData'),
     State('wbin-main-graph', 'figure')],
    prevent_initial_call=True
)
def cb_render_graph(n_clicks, relayout_data, table_store,
                    selected_indices, cfg, current_rows_state,
                    axis_defs, current_fig):

    if not selected_indices or not cfg:
        return go.Figure(), []

    current_rows = current_rows_state if current_rows_state is not None else []
    axis_rows = axis_defs if axis_defs is not None else []
    ctx = dash.callback_context
    trigger = ctx.triggered[0]['prop_id'].split('.')[0]  # ← use component id now
    today = datetime.now().date()

    # --- [1. DATA LOADING] ---
    with open(cfg['path'], 'rb') as f:
        f.seek(cfg['data_offset'])
        first_record = f.read(cfg['block_size'])
    h0, m0, s0 = first_record[4], first_record[5], first_record[6]
    start_dt = datetime(today.year, today.month, today.day, h0, m0, s0)

    start_block, end_block = 0, cfg['total_blocks'] - 1

    # --- [2. TRIGGER HANDLING] ---
    if trigger == 'relayoutData' and relayout_data:
        keys = set(relayout_data.keys())

        # Pure y-axis or autosize interaction — skip redraw entirely
        y_only_patterns = ('yaxis', 'autosize')
        if all(any(k.startswith(p) for p in y_only_patterns) for k in keys):
            return dash.no_update, dash.no_update

        # X range changed — recalculate block range
        if 'xaxis.range[0]' in relayout_data:
            try:
                x_start = datetime.fromisoformat(relayout_data['xaxis.range[0]'].replace('Z', ''))
                x_end = datetime.fromisoformat(relayout_data['xaxis.range[1]'].replace('Z', ''))
                start_block = max(0, int((x_start - start_dt).total_seconds()))
                end_block = min(cfg['total_blocks'] - 1, int((x_end - start_dt).total_seconds()))
            except:
                pass

    elif trigger == 'wbin-info-table-store' and current_fig:
        # Recover x range from current figure so zoom is preserved
        try:
            xrange = current_fig['layout']['xaxis'].get('range')
            if xrange:
                x_start = datetime.fromisoformat(str(xrange[0]).replace('Z', ''))
                x_end = datetime.fromisoformat(str(xrange[1]).replace('Z', ''))
                start_block = max(0, int((x_start - start_dt).total_seconds()))
                end_block = min(cfg['total_blocks'] - 1, int((x_end - start_dt).total_seconds()))
        except:
            pass

    # --- [3. ROW SYNC] ---
    colors = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3', '#FF6692', '#B6E880']
    new_rows = []
    for i, sid in enumerate(selected_indices):
        existing = next((r for r in current_rows if r.get('sid') == sid), None)
        if existing:
            existing['axis_id'] = int(existing.get('axis_id', 1))
            new_rows.append(existing)
        else:
            v_type, v_idx = sid.split('_')
            idx = int(v_idx)
            ch_info = cfg['analog_channels'][idx] if v_type == 'A' else cfg['digital_channels'][idx]
            new_rows.append({
                "sid": sid,
                "tag": ch_info['tag'],
                "desc": ch_info.get('desc', 'N/A'),   # ← fill description
                "axis_sel": "1",                        # ← default dropdown value
                "color": colors[i % len(colors)],
                "axis_id": 1,
                "delete-row": "✘"
            })
    current_rows = new_rows

    # Build axis map from config grid
    used_ids = set(int(r['axis_id']) for r in current_rows)
    existing_config_ids = set(int(a['id']) for a in axis_rows)
    for aid in used_ids:
        if aid not in existing_config_ids:
            axis_rows.append({"id": aid, "name": f"Asse {aid}", "rangeMIN": "", "rangeMAX": ""})
    axis_rows = sorted(axis_rows, key=lambda x: int(x['id']))
    ax_map = {str(a['id']): a for a in axis_rows}

    # --- [4. DATA READING] ---
    actual_range = end_block - start_block
    block_indices = np.linspace(start_block, end_block, min(n_pts, actual_range + 1)).astype(int)
    data_dict = {sid: [] for sid in selected_indices}
    time_axis = []

    with open(cfg['path'], 'rb') as f:
        for b_idx in block_indices:
            f.seek(cfg['data_offset'] + (int(b_idx) * cfg['block_size']))
            record = f.read(cfg['block_size'])
            if len(record) < cfg['block_size']: break
            time_axis.append(start_dt + timedelta(seconds=int(b_idx)))
            for sid in selected_indices:
                v_type, v_idx = sid.split('_')
                idx = int(v_idx)
                if v_type == 'A':
                    val = struct.unpack('>f', record[13+(idx*4):13+(idx*4)+4])[0]
                    data_dict[sid].append(val if abs(val) < 1e15 else 0.0)
                else:
                    ch = cfg['digital_channels'][idx]
                    raw_word = record[13+(cfg['n_analog']*4)+(ch['group']*4):13+(cfg['n_analog']*4)+(ch['group']*4)+4]
                    data_dict[sid].append((struct.unpack('<I', raw_word)[0] >> ch['bit']) & 1)

    # --- [5. PLOT CONSTRUCTION] ---
    fig = go.Figure()
    used_ids_int = sorted(list(used_ids))
    num_subplots = len(used_ids_int)

    for row in current_rows:
        aid = str(row['axis_id'])
        fig.add_trace(go.Scattergl(
            x=time_axis, y=data_dict[row['sid']], name=row['tag'],
            yaxis=f"y{aid}" if aid != '1' else "y",
            line=dict(color=row['color'], width=1.5),
            showlegend=False,
            hovertemplate="<b>" + row['tag'] + "</b>: %{y:.3f}<extra></extra>"
        ))

    # --- [6. LAYOUT CONSTRUCTION] ---
    spacing = 0.08
    p_height = (1.0 - (spacing * (max(1, num_subplots - 1)))) / max(1, num_subplots)

    layout = {
        "template": "plotly_white", "hovermode": "x unified", "hoverdistance": -1,
        "autosize": True,
        "margin": dict(t=30, b=50, l=100, r=200),
        "uirevision": True,
        "showlegend": False,
        "annotations": [],
        "xaxis": {"title": "Orario", "tickformat": "%H:%M:%S", "gridcolor": "#eee", "showspikes": True}
    }

    for i, aid_int in enumerate(used_ids_int):
        aid = str(aid_int)
        ax_key = f"yaxis{aid}" if aid != '1' else "yaxis"
        ref_key = f"y{aid}" if aid != '1' else "y"

        start_y = max(0, 1.0 - ((i + 1) * p_height) - (i * spacing))
        end_y = min(1.0, start_y + p_height)
        mid_y = start_y + (p_height / 2)

        subplot_rows = [r for r in current_rows if int(r['axis_id']) == aid_int]
        for j, row in enumerate(subplot_rows):
            y_offset = (len(subplot_rows) / 2 - j) * 0.035
            layout["annotations"].append(dict(
                x=1.02, y=mid_y + y_offset,
                xref="paper", yref="paper",
                text=f"<b>{row['tag']}</b>",
                showarrow=False,
                font=dict(color=row['color'], size=11),
                xanchor="left"
            ))

        conf = ax_map.get(aid, {})
        layout[ax_key] = {
            "domain": [start_y, end_y],
            "title": {"text": conf.get('name', f'Asse {aid}'), "font": {"size": 12}},
            "showgrid": True, "showticklabels": True, "matches": "x"
        }

        if i == num_subplots - 1:
            layout["xaxis"]["anchor"] = ref_key

    # --- [7. PRESERVE Y RANGES on cellValueChanged] ---
    if trigger == 'cellValueChanged' and current_fig:
        old_layout = current_fig.get('layout', {})
        for aid_int in used_ids_int:
            aid = str(aid_int)
            ax_key = "yaxis" if aid == '1' else f"yaxis{aid}"
            old_ax = old_layout.get(ax_key, {})
            old_range = old_ax.get('range')
            autorange = old_ax.get('autorange', True)

            if old_range and not autorange:
                # Axis existed before with manual range — preserve it
                layout[ax_key]['range'] = old_range
                layout[ax_key]['autorange'] = False
            # Brand new axis — leave to autoscale

    fig.update_layout(layout)
    fig.update_traces(xaxis="x")

    return fig, current_rows

# cb_info_table_axis_sel writes to the store instead of rowData directly
@callback(
    [Output('wbin-info-table', 'rowData', allow_duplicate=True),
     Output('wbin-axis-config-grid', 'rowData', allow_duplicate=True),
     Output('wbin-info-table-store', 'data')],  # ← trigger for graph redraw
    Input('wbin-info-table', 'cellValueChanged'),
    [State('wbin-info-table', 'rowData'),
     State('wbin-axis-config-grid', 'rowData')],
    prevent_initial_call=True
)
def cb_info_table_axis_sel(cell_changed, info_rows, axis_rows):
    if not cell_changed or not info_rows:
        return no_update, no_update, no_update

    changed = cell_changed[0]
    if changed.get('colId') != 'axis_sel':
        return no_update, no_update, no_update

    selected = changed['value']
    row_sid = changed['data']['sid']
    axis_rows = [dict(r) for r in (axis_rows or [])]
    info_rows = [dict(r) for r in info_rows]

    if selected in AXIS_PRESETS and selected != 'Custom':
        preset = AXIS_PRESETS[selected]
        existing_axis = next(
            (a for a in axis_rows if a.get('preset') == selected), None
        )
        if existing_axis:
            target_id = int(existing_axis['id'])
        else:
            existing_ids = [int(a['id']) for a in axis_rows]
            target_id = max(existing_ids) + 1 if existing_ids else 1
            axis_rows.append({
                "id": target_id,
                "preset": selected,
                "name": preset['name'],
                "rangeMIN": preset['rangeMIN'],
                "rangeMAX": preset['rangeMAX'],
            })
    else:
        target_id = int(selected)
        existing_ids = [int(a['id']) for a in axis_rows]
        if target_id not in existing_ids:
            axis_rows.append({
                "id": target_id,
                "preset": "Custom",
                "name": f"Asse {target_id}",
                "rangeMIN": "",
                "rangeMAX": "",
            })

    for row in info_rows:
        if row['sid'] == row_sid:
            row['axis_id'] = target_id
            row['axis_sel'] = selected
            break

    axis_rows = sorted(axis_rows, key=lambda x: int(x['id']))
    return info_rows, axis_rows, {"ts": datetime.now().isoformat()}  # ← ping store


@callback(
    Output("wbin-axis-modal", "is_open"),
    [Input("wbin-btn-axis-modal", "n_clicks"), Input("wbin-close-axis-modal", "n_clicks")],
    State("wbin-axis-modal", "is_open")
)
def toggle_axis_modal(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    return is_open

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
    """Salva i tag nel formato richiesto."""
    with open(PRESETS_FILE, "a") as f:
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


@callback(
    [
        Output('wbin-info-table', 'rowData', allow_duplicate=True),
        Output('wbin-main-graph', 'figure', allow_duplicate=True),
        Output('wbin-tag-dropdown', 'value', allow_duplicate=True),
        Output('wbin-selected-row-store', 'data'),
        Output('wbin-color-picker-modal', 'is_open'),
        Output('wbin-color-edit-store', 'data'),
        Output('wbin-color-input', 'value'),
    ],
    Input('wbin-info-table', 'cellClicked'),
    [
        State('wbin-info-table', 'rowData'),
        State('wbin-main-graph', 'figure'),
        State('wbin-tag-dropdown', 'value'),
        State('wbin-config-store', 'data'),
    ],
    prevent_initial_call=True
)
def handle_table_logic(clicked, current_rows, fig, current_tags, cfg):

    if not clicked or not current_rows:
        return no_update, no_update, no_update, no_update, False, no_update, no_update

    row_idx = clicked.get("rowIndex")
    col_id = clicked.get("colId")

# --- ADD THIS: If user clicks an editable column, do nothing and let them type ---
    if col_id in ['axis_id', 'axis_range', 'axis_sel']:  # ← add 'axis_sel'
        return no_update, no_update, no_update, no_update, False, no_update, no_update

    if row_idx is None or row_idx >= len(current_rows):
        return no_update, no_update, no_update, None, False, no_update, no_update

    selected_tag = current_rows[row_idx]['tag']

    # ─────────────────────────────
    # CASE A: DELETE COLUMN
    # ─────────────────────────────
    if col_id == 'delete-row':

        new_table = [r for i, r in enumerate(current_rows) if i != row_idx]

        if fig and 'data' in fig:
            fig['data'] = [
                t for t in fig['data']
                if selected_tag not in t.get('name', '')
            ]

        new_tags = []
        if current_tags:
            for sid in current_tags:
                if get_tagname_from_sid(sid, cfg) != selected_tag:
                    new_tags.append(sid)

        return new_table, fig, new_tags, None, False, None, None

    # ─────────────────────────────
    # CASE B: COLOR COLUMN
    # ─────────────────────────────
    elif col_id == 'color':

        current_color = current_rows[row_idx].get('color', '#0000FF')

        return (
            no_update,
            no_update,
            no_update,
            selected_tag,
            True,
            row_idx,
            {"hex": current_color}
        )

    # ─────────────────────────────
    # CASE C: OTHER CELLS (HIGHLIGHT)
    # ─────────────────────────────
    else:
        # update figure traces
        if fig and 'data' in fig:
            for trace in fig['data']:
                if selected_tag in trace.get('name', ''):
                    trace['line']['width'] = 4
                else:
                    trace['line']['width'] = 1.5
            fig['layout']['uirevision'] = 'constant'
        
        new_rows = []
        for r in current_rows:
            r = dict(r)
            r['_selected'] = (r['tag'] == selected_tag)
            new_rows.append(r)
        
        return new_rows, fig, no_update, selected_tag, False, None, None
     
# CALLBACK PER SALVARE IL NUOVO COLORE SELEZIONATO
@callback(
    [Output('wbin-info-table', 'rowData', allow_duplicate=True),
     Output('wbin-color-picker-modal', 'is_open', allow_duplicate=True)],
    Input('wbin-color-confirm', 'n_clicks'),
    [State('wbin-color-input', 'value'),
     State('wbin-color-edit-store', 'data'),
     State('wbin-info-table', 'rowData')],
    prevent_initial_call=True
)
def update_row_color(n_clicks, color_value, row_idx, current_rows):
    if n_clicks is None or row_idx is None:
        return no_update, False
    
    # ESTRAZIONE CORRETTA: color_value è un dizionario {'hex': '#...', 'rgb': {...}, 'hsv': {...}}
    # Dobbiamo passare alla DataTable solo la stringa HEX
    new_hex = "#0000FF" # Default di sicurezza
    if isinstance(color_value, dict) and 'hex' in color_value:
        new_hex = color_value['hex']
    elif isinstance(color_value, str):
        new_hex = color_value
    
    if row_idx < len(current_rows):
        # Cloniamo i dati per sicurezza prima di modificare
        new_rows = [row.copy() for row in current_rows]
        new_rows[row_idx]['color'] = new_hex
        return new_rows, False
    
    return no_update, False

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