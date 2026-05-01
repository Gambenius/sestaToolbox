import os, re, struct
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import plotly.graph_objects as go

import dash
from dash import html, dcc, dash_table, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc

# Registrazione della pagina
dash.register_page(__name__, path="/wbin")

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
    dbc.Row([
        # Sidebar
        dbc.Col([
            html.Div([
                html.H4("Lettore archiviazioni binarie", className="text-primary mb-4"),
                
                dbc.Button(
                    "📂 SELEZIONA BINARIO",
                    id="wbin-btn-open-modal",
                    color="primary",
                    outline=True,
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
            dash_table.DataTable(
                id='wbin-info-table',
                columns=[
                    {"name": "Rimuovi", "id": "delete-row", "editable": False},
                    {"name": "Tag", "id": "tag", "editable": False},
                    {"name": "Descrizione", "id": "desc", "editable": False},
                    {"name": "Colore", "id": "color", "editable": False},
                    {"name": "Valore al cursore", "id": "cur_val", "editable": False}
                ],
                data=[],
                # Unica occorrenza di style_data_conditional
                style_data_conditional=[
                    # Stile per la colonna elimina (X)
                    {
                        'if': {'column_id': 'delete-row'},
                        'cursor': 'pointer',
                        'textAlign': 'center',
                        'color': 'red',
                        'fontWeight': 'bold'
                    },
                    # Stile per la colonna Valore (Testo nero regular)
                    {
                        'if': {'column_id': 'cur_val'},
                        'color': 'black',
                        'fontWeight': 'normal'
                    },
                    # Rimuove l'evidenziazione blu della cella attiva
                    {
                        'if': {'state': 'active'},
                        'backgroundColor': 'inherit',
                        'border': '1px solid #dee2e6'
                    }
                ],
                style_header={
                    'backgroundColor': '#f8f9fa',
                    'color': '#2c3e50',
                    'fontWeight': 'bold',
                    'border': '1px solid #dee2e6'
                },
                style_data={
                    'backgroundColor': 'white',
                    'color': '#495057',
                    'border': '1px solid #dee2e6'
                },
                style_cell={
                    'textAlign': 'left',
                    'padding': '10px',
                    'fontFamily': 'Segoe UI, sans-serif',
                    'fontSize': '13px'
                }
            )
        ], width=9)
    ], className="mt-3")
], fluid=True, style={'backgroundColor': '#f8f9fa', 'minHeight': '100vh'})

# ─────────────────────────────────────────────────────────────────
# 3. CALLBACKS
# ─────────────────────────────────────────────────────────────────

NETWORK_BASE_PATH = r"\\10.33.126.101\archivi\TOTALE\PROVE"

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
    [Output('wbin-main-graph', 'figure'),
     Output('wbin-info-table', 'data')], 
    [Input('wbin-btn-plot', 'n_clicks'),
     Input('wbin-main-graph', 'relayoutData')],
    [State('wbin-tag-dropdown', 'value'), 
     State('wbin-config-store', 'data')],
    prevent_initial_call=True
)

def cb_render_graph(n_clicks, relayout_data, selected_indices, cfg):
    if not selected_indices or not cfg: 
        return no_update, []
    
    ctx = dash.callback_context
    trigger = ctx.triggered[0]['prop_id'].split('.')[1]

    # Gestione Range blocchi
    start_block = 0
    end_block = cfg['total_blocks'] - 1

    if trigger == 'relayoutData' and relayout_data:
        if 'xaxis.range[0]' in relayout_data:
            start_block = max(0, int(float(relayout_data['xaxis.range[0]'])))
            end_block = min(cfg['total_blocks'] - 1, int(float(relayout_data['xaxis.range[1]'])))
        elif 'xaxis.autorange' in relayout_data:
            start_block = 0
            end_block = cfg['total_blocks'] - 1
        else: 
            return no_update, no_update

    # Campionamento dinamico (max 1200 punti per fluidità)
    n_pts = 1200
    actual_range = end_block - start_block
    block_indices = np.linspace(start_block, end_block, min(n_pts, actual_range + 1)).astype(int)

    data_dict = {sid: [] for sid in selected_indices}
    time_axis = []
    time_labels = []

    # Lettura Binaria
    with open(cfg['path'], 'rb') as f:
        for b_idx in block_indices:
            f.seek(cfg['data_offset'] + (int(b_idx) * cfg['block_size']))
            record = f.read(cfg['block_size'])
            if len(record) < cfg['block_size']: break
            
            time_axis.append(b_idx)
            time_labels.append(f"{record[4]:02d}:{record[5]:02d}:{record[6]:02d}")

            for sid in selected_indices:
                v_type, v_idx = sid.split('_')
                idx = int(v_idx)
                
                if v_type == 'A':
                    offset = 13 + (idx * 4)
                    val = struct.unpack('>f', record[offset:offset+4])[0]
                    data_dict[sid].append(val if abs(val) < 1e15 else 0.0)
                else:
                    ch = cfg['digital_channels'][idx]
                    dig_base = 13 + (cfg['n_analog'] * 4)
                    group_offset = dig_base + (ch['group'] * 4)
                    raw_word = record[group_offset : group_offset+4]
                    if len(raw_word) == 4:
                        full_word = struct.unpack('<I', raw_word)[0]
                        data_dict[sid].append((full_word >> ch['bit']) & 1)
                    else:
                        data_dict[sid].append(0)

    # Creazione Figura
    fig = go.Figure()
    colors = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3', '#FF6692', '#B6E880']
    table_rows = []

    for i, sid in enumerate(selected_indices):
        v_type, v_idx = sid.split('_')
        idx = int(v_idx)
        ch_info = cfg['analog_channels'][idx] if v_type == 'A' else cfg['digital_channels'][idx]
        color = colors[i % len(colors)]

        # Aggiunta traccia al grafico
        fig.add_trace(go.Scattergl(
            x=time_axis, 
            y=data_dict[sid], 
            name=ch_info['tag'],
            # Questo è fondamentale: permette a %{text} di funzionare nell'hover
            customdata=time_labels, 
            line=dict(color=color, width=1.5),
            # Rimuoviamo l'orario dalla riga singola (lo abbiamo già nel titolo sopra)
            hovertemplate="<span style='color:inherit'></span> %{y:.3f}<extra></extra>"
        ))
        fig.update_traces(
            customdata=time_labels,
            hovertemplate="<span style='color:inherit'></span> %{y:.3f}<extra></extra>"
        )
        table_rows.append({
            "delete-row": "✘",  # Aggiungi questa riga
            "tag": ch_info['tag'],
            "desc": ch_info.get('desc', 'N/A'),
            "color": color,
            "cur_val": "---"
        })

    # Layout Grafico
    tick_indices = np.linspace(0, len(time_axis)-1, 10).astype(int)

    fig.update_layout(
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(255, 255, 255, 0.9)",
            font_size=13,
        ),
        xaxis=dict(
            title="Orario", tickmode='array',
            tickvals=[time_axis[i] for i in tick_indices],
            ticktext=[time_labels[i] for i in tick_indices],
            tickangle=45,
            unifiedhovertitle=dict(
                # Usiamo %{text} perché lì abbiamo salvato HH:MM:SS nel Scattergl

                text='<b>Ora: %{customdata}</b>'
            ),
        ),
        yaxis=dict(gridcolor='#f0f0f0')
    )
    return fig, table_rows

# ─────────────────────────────────────────────────────────────────
# CALLBACK CLICK: POSIZIONA CURSORE + AGGIORNA VALORI TABELLA
# ─────────────────────────────────────────────────────────────────
@callback(
    [Output('wbin-info-table', 'data', allow_duplicate=True),
     Output('wbin-main-graph', 'figure', allow_duplicate=True)],
    Input('wbin-main-graph', 'clickData'),
    [State('wbin-info-table', 'data'),
     State('wbin-main-graph', 'figure')],
    prevent_initial_call=True
)
def update_on_click(clickData, current_table, fig):
    if not clickData or not current_table or not fig:
        return no_update, no_update

    # 1. Recupera la coordinata X del click
    clicked_x = clickData['points'][0]['x']

    # 2. Aggiorna i valori "Valore al Cursore" nella tabella
    for row in current_table:
        tag = row['tag']
        val = "---"
        # Cerchiamo tra le tracce del grafico quella corrispondente al tag
        for trace in fig['data']:
            if tag in trace['name']:
                try:
                    x_vals = list(trace['x'])
                    if clicked_x in x_vals:
                        idx = x_vals.index(clicked_x)
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

PRESETS_FILE = "utils/binrev_presets.txt"

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
        if 'xaxis.range[0]' in relayout_data and fig and fig['data']:
            try:
                idx_start = float(relayout_data['xaxis.range[0]'])
                idx_end = float(relayout_data['xaxis.range[1]'])
                
                # MODIFICA QUI: Cerchiamo in customdata, se vuoto cerchiamo in text
                times = fig['data'][0].get('customdata', [])
                if not times:
                    times = fig['data'][0].get('text', [])
                
                x_axis = fig['data'][0].get('x', [])
                
                if not times or not x_axis: 
                    return no_update, no_update
                
                # Cerchiamo l'orario corrispondente agli indici zoomati
                # Usiamo indici interi per sicurezza
                t_s = next((times[i] for i, v in enumerate(x_axis) if v >= idx_start), times[0])
                t_e = next((times[i] for i, v in reversed(list(enumerate(x_axis))) if v <= idx_end), times[-1])
                
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

    with open(cfg['path'], 'rb') as f:
        for b_idx in range(cfg['total_blocks']):
            f.seek(cfg['data_offset'] + (b_idx * cfg['block_size']))
            record = f.read(cfg['block_size'])
            if len(record) < cfg['block_size']: break
            
            # Orario del blocco corrente (Byte 4, 5, 6)
            h, m, s = record[4], record[5], record[6]
            curr_sec = h * 3600 + m * 60 + s
            
            # Filtro temporale
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
                    full_word = struct.unpack('<I', record[group_offset : group_offset+4])[0]
                    row.append((full_word >> ch['bit']) & 1)
            rows.append(row)

    if not rows:
        return no_update, "Nessun dato trovato nel range."

    # 3. Creazione DataFrame e Invio
    df = pd.DataFrame(rows, columns=headers)
    return dcc.send_data_frame(df.to_csv, "export_data.csv", index=False), f"Esportati {len(rows)} record."

# --- TABELLE E GRAFICA

@callback(
    Output('wbin-info-table', 'style_data_conditional', allow_duplicate=True),
    Input('wbin-info-table', 'data'),
    prevent_initial_call=True
)
def update_table_colors(data):
    if not data:
        return no_update
    
    # Stili base (quelli che abbiamo scritto sopra nel layout)
    base_styles = [
        {'if': {'column_id': 'delete-row'}, 'cursor': 'pointer', 'textAlign': 'center', 'color': 'red', 'fontWeight': 'bold'},
        {'if': {'column_id': 'cur_val'}, 'color': 'black', 'fontWeight': 'normal'},
        {'if': {'state': 'active'}, 'backgroundColor': 'inherit', 'border': '1px solid #dee2e6'}
    ]
    
    # Aggiungiamo i colori di sfondo per ogni riga basandoci sul valore HEX in row['color']
    for i, row in enumerate(data):
        base_styles.append({
            'if': {
                'column_id': 'color',
                'row_index': i
            },
            'backgroundColor': row['color'],
            'color': row['color'] # Rende il testo invisibile (stesso colore dello sfondo)
        })
    
    return base_styles

@callback(
    [Output('wbin-info-table', 'data', allow_duplicate=True),
     Output('wbin-main-graph', 'figure', allow_duplicate=True),
     Output('wbin-tag-dropdown', 'value', allow_duplicate=True),
     Output('wbin-info-table', 'active_cell')],
    [Input('wbin-info-table', 'active_cell'),
     Input('wbin-info-table', 'data')],
    [State('wbin-info-table', 'data'),
     State('wbin-main-graph', 'figure'),
     State('wbin-tag-dropdown', 'value'),
     State('wbin-config-store', 'data')],
    prevent_initial_call=True
)
def handle_table_logic(active_cell, table_data_input, current_rows, fig, current_tags, cfg):
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update, no_update
    
    trigger_id = ctx.triggered[0]['prop_id']

    # --- 1. GESTIONE CLICK SU CELLA (ELIMINA O BOLD) ---
    if "active_cell" in trigger_id and active_cell:
        row_idx = active_cell['row']
        col_id = active_cell['column_id']
        selected_tag = current_rows[row_idx]['tag']

        # CASO A: CLICK SU CESTINO (ELIMINA)
        if col_id == 'delete-row':
            new_table = [r for i, r in enumerate(current_rows) if i != row_idx]
            fig['data'] = [t for t in fig['data'] if selected_tag not in t['name']]
            
            # Sincronizza Dropdown
            new_tags = []
            if current_tags:
                for sid in current_tags:
                    if get_tagname_from_sid(sid, cfg) != selected_tag:
                        new_tags.append(sid)
            
            return new_table, fig, new_tags, None

        # CASO B: CLICK SU ALTRA CELLA (HIGHLIGHT BOLD)
        else:
            for trace in fig['data']:
                if selected_tag in trace['name']:
                    trace['line']['width'] = 4   # Bold
                else:
                    trace['line']['width'] = 1.5 # Normal
            
            fig['layout']['uirevision'] = 'constant'
            return no_update, fig, no_update, no_update

    # --- 2. GESTIONE CAMBIO DATI (ES. COLORE SE AVESSI MANTENUTO IL DROPDOWN) ---
    if "wbin-info-table.data" in trigger_id:
        # Qui potresti gestire modifiche manuali ai dati se necessario
        return no_update, no_update, no_update, no_update

    return no_update, no_update, no_update, no_update








