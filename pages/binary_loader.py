import os, re, struct
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import tkinter as tk
from tkinter import filedialog
import fnmatch # Aggiungi questo import in cima al file

import dash
from dash import html, dcc, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc

# Registrazione della pagina
dash.register_page(__name__, name="Lettore Arch. Binarie", path="/wbin")

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

    # ───── DIGITAL (SAFE VERSION) ─────
    digital_channels = []
    group_idx = 0

    for line in part2.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        if MARKER_DIG in line.upper():
            continue
        
        if not line.upper().startswith('DIGITAL'):
            continue
        
        cols = line.split('\t')
        v_col = next((i for i, c in enumerate(cols) if ',' in c), 1)

        if v_col < len(cols):
            tags = [t.strip() for t in cols[v_col].split(',') if t.strip()]
            
            for bit_idx, tag in enumerate(tags[:32]):
                digital_channels.append({
                    'tag': tag.upper(),
                    'group': group_idx,
                    'bit': bit_idx,
                    'type': 'D'
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

    return {
        'path': path,
        'data_offset': data_offset,
        'block_size': block_size,
        'total_blocks': total_blocks,
        'n_analog': n_analog,
        'analog_channels': analog_channels,
        'digital_channels': digital_channels,
        'meta': campaign_info
    }

# ─────────────────────────────────────────────────────────────────
# 2. LAYOUT LIGHT MODE (Bootstrap Standard)
# ─────────────────────────────────────────────────────────────────

layout = dbc.Container([
    dcc.Store(id='wbin-config-store'),
    dcc.Store(id='wbin-zoom-store', data={'start': 0, 'end': None}),
    dbc.Row([
        # Sidebar
        dbc.Col([
            html.Div([
                html.H4("Lettore archiviazioni binarie", className="text-primary mb-4"),
                
                dbc.Button("📂 SELEZIONA BINARIO", id="wbin-btn-open", color="primary", outline=True, className="w-100 mb-3"),
                
                # Box Info File e Metadati (Sfondo chiaro, testo scuro)
                html.Div(id="wbin-file-info", children=[
                    dbc.Card([
                        dbc.CardBody([
                            html.P("Carica un file...", className="text-muted small mb-0")
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
                    # Non aggiungere altri parametri extra che potrebbero non essere supportati
                ),
                dbc.Button("Mostra grafico", id="wbin-btn-plot", color="primary", className="w-100 mb-3"),
                
                html.Div(id="wbin-status-msg"),

                dcc.Dropdown(id='preset-dropdown', placeholder="Seleziona un Preset...", className="mb-4"   ),

                dbc.Input(id='new-preset-name', placeholder="Nome nuovo preset...", type="text", className="mb-4"),

                dbc.Button("Salva selezione corrente", id='save-preset-btn', color="success",className="w-100 mb-3")
            ], style={'padding': '20px', 'borderRight': '1px solid #ddd', 'minHeight': '90vh'})
        ], width=3),
        
        # Grafico
        dbc.Col([
            dcc.Loading(
                dcc.Graph(id='wbin-main-graph', style={'height': '85vh'}),
                type="default"
            )
        ], width=9)
    ], className="mt-3")
], fluid=True, style={'backgroundColor': '#f8f9fa', 'minHeight': '100vh'})

# ─────────────────────────────────────────────────────────────────
# 3. CALLBACKS
# ─────────────────────────────────────────────────────────────────

@callback(
    [Output('wbin-config-store', 'data'), 
     Output('wbin-file-info', 'children'), 
     Output('wbin-status-msg', 'children')],
    Input('wbin-btn-open', 'n_clicks'),
    prevent_initial_call=True
)
def cb_open_file(n):
    root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
    path = filedialog.askopenfilename()
    root.destroy()
    if not path: return no_update
    
    try:
        cfg = get_wbin_metadata(path)
        n_analog = cfg.get('n_analog', 0)
        n_digital = len(cfg.get('digital_channels', []))
        m = cfg.get('meta', {'campaign': 'N/A', 'customer': 'N/A', 'coordinator': 'N/A'})

        info_content = dbc.Card([
            dbc.CardHeader("INFORMAZIONI FILE", className="fw-bold small"),
            dbc.CardBody([
                html.Div([
                    html.P([html.B("File: "), os.path.basename(path)], className="mb-1 small"),
                    html.P([html.B("Quantità dati: "), f"{cfg['total_blocks']:,}"], className="mb-1 small"),
                    # --- Canali sdoppiati ---
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

@callback(
    Output('wbin-main-graph', 'figure'),
    [Input('wbin-btn-plot', 'n_clicks'),
     Input('wbin-main-graph', 'relayoutData')],
    [State('wbin-tag-dropdown', 'value'), 
     State('wbin-config-store', 'data')],
    prevent_initial_call=True
)
def cb_render_graph(n_clicks, relayout_data, selected_indices, cfg):
    if not selected_indices or not cfg: return no_update
    
    ctx = dash.callback_context
    trigger = ctx.triggered[0]['prop_id'].split('.')[1]

    start_block = 0
    end_block = cfg['total_blocks'] - 1

    if trigger == 'relayoutData' and relayout_data:
        if 'xaxis.range[0]' in relayout_data:
            start_block = max(0, int(float(relayout_data['xaxis.range[0]'])))
            end_block = min(cfg['total_blocks'] - 1, int(float(relayout_data['xaxis.range[1]'])))
        elif 'xaxis.autorange' in relayout_data:
            start_block = 0
            end_block = cfg['total_blocks'] - 1
        else: return no_update

    # Campionamento dinamico
    n_pts = 1200
    actual_range = end_block - start_block
    block_indices = np.linspace(start_block, end_block, min(n_pts, actual_range + 1)).astype(int)

    data_dict = {sid: [] for sid in selected_indices}
    time_axis = []
    time_labels = []

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
                    # ANALOGICO: Float32 Big Endian
                    offset = 13 + (idx * 4)
                    val = struct.unpack('>f', record[offset:offset+4])[0]
                    data_dict[sid].append(val if abs(val) < 1e15 else 0.0)
                else:
                    # DIGITALE: Bitfield Word (4 byte) Little Endian
                    ch = cfg['digital_channels'][idx]
                    dig_base = 13 + (cfg['n_analog'] * 4)
                    group_offset = dig_base + (ch['group'] * 4)
                    
                    # Leggiamo l'intera Word da 4 byte
                    raw_word = record[group_offset : group_offset+4]
                    if len(raw_word) == 4:
                        # Unpack come intero 32-bit senza segno
                        full_word = struct.unpack('<I', raw_word)[0]
                        # Estrazione bit specifica
                        bit_val = (full_word >> ch['bit']) & 1
                        data_dict[sid].append(bit_val)
                    else:
                        data_dict[sid].append(0)

    # Creazione Figura
    fig = go.Figure()
    for sid in selected_indices:
        v_type, v_idx = sid.split('_')
        idx = int(v_idx)
        ch_info = cfg['analog_channels'][idx] if v_type == 'A' else cfg['digital_channels'][idx]
        
        fig.add_trace(go.Scattergl(
            x=time_axis, y=data_dict[sid], 
            name=f"[{v_type}] {ch_info['tag']}",
            text=time_labels,
            hovertemplate="<b>%{name}</b><br>Ora: %{text}<br>Val: %{y}<extra></extra>"
        ))

    # Aggiornamento assi con Tick Temporali
    tick_indices = np.linspace(0, len(time_axis)-1, 10).astype(int)
    fig.update_layout(
        template="plotly_white", margin=dict(l=20, r=20, t=30, b=80),
        hovermode="x unified", uirevision='constant',
        xaxis=dict(
            title="Orario", tickmode='array',
            tickvals=[time_axis[i] for i in tick_indices],
            ticktext=[time_labels[i] for i in tick_indices],
            tickangle=45
        )
    )
    return fig


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
    if not preset_name or not cfg:
        return no_update
    
    presets = load_presets_from_file()
    selected_tagnames = presets.get(preset_name, [])
    
    # Traduciamo i nomi reali (CA004.PV) in ID tecnici (A_5184)
    new_selection = []
    for tagname in selected_tagnames:
        sid = get_sid_from_tagname(tagname, cfg)
        if sid:
            new_selection.append(sid)
            
    return new_selection
    """Carica i tag del preset selezionato nel grafico."""
    if not preset_name:
        return no_update
    
    presets = load_presets_from_file()
    selected_tags = presets.get(preset_name, [])
    
    # Restituisce direttamente la lista dei tag caricati (es. ["A_10", "D_5"])
    return selected_tags    
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