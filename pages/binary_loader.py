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
    with open(path, 'rb') as f:
        blob = f.read(2048 * 1024)
    
    cuts = [m.start() for m in re.finditer(re.escape(MARKER), blob)]
    if len(cuts) < 2: 
        raise ValueError("Marker [END] non trovati.")
    
    # Decodifica l'header
    part1 = blob[:cuts[0]].decode('latin-1', errors='ignore')
    lines = part1.splitlines()
    
    campaign_info = {"campaign": "N/A", "customer": "N/A", "coordinator": "N/A"}
    
    if lines:
        # Replicazione della logica Mathematica:
        # Split sulla tabulazione e rimozione degli elementi vuoti (DeleteCases)
        raw_parts = lines[0].split('\t')
        clean_parts = [p.strip() for p in raw_parts if p.strip()]
        
        # Mathematica vede 4 pezzi e fa Drop[..., 1], quindi ne restano 3
        # Esempio: ["HeaderID", "Gas/Gasolio", "2AE94.3a", "Galgani"]
        if len(clean_parts) >= 4:
            campaign_info["campaign"]    = clean_parts[1]
            campaign_info["customer"]    = clean_parts[2]
            campaign_info["coordinator"] = clean_parts[3]
        elif len(clean_parts) == 3:
            # Caso di riserva se il primo pezzo manca
            campaign_info["campaign"]    = clean_parts[0]
            campaign_info["customer"]    = clean_parts[1]
            campaign_info["coordinator"] = clean_parts[2]

    # --- RESTO DELLA LOGICA (OFFSET E CANALI) ---
    match = re.search(r'#(\d{9})', part1)
    data_offset = int(match.group(1)) if match else 0
    
    # ... (il resto del codice per i canali analogici rimane uguale)
    analog_channels = []
    start_parsing = False
    for line in lines:
        cols = [c.strip() for c in line.split('\t')]
        if 'Tag' in cols:
            hdr_map = {col: i for i, col in enumerate(cols)}
            start_parsing = True; continue
        if start_parsing and len(cols) > 1:
            tag = cols[hdr_map.get('Tag', 0)].upper()
            if tag:
                analog_channels.append({
                    'tag': tag, 
                    'unit': cols[hdr_map.get('EU', 1)] if 'EU' in hdr_map else "",
                    'desc': cols[hdr_map.get('Comment', 2)] if 'Comment' in hdr_map else ""
                })

    # Calcolo blockSize e total_blocks
    part2 = blob[cuts[0]+len(MARKER):cuts[1]].decode('latin-1', errors='ignore')
    n_uint32 = len([l for l in part2.splitlines() if ',' in l and '\t' in l])
    n_analog = len(analog_channels)
    block_size = 13 + (n_analog * 4) + (n_uint32 * 4)
    total_blocks = (os.path.getsize(path) - data_offset) // block_size
    
    return {
        'path': path, 'data_offset': data_offset, 'block_size': block_size,
        'total_blocks': total_blocks, 'analog_channels': analog_channels,
        'n_analog': n_analog, 'meta': campaign_info
    }
# ─────────────────────────────────────────────────────────────────
# 2. LAYOUT LIGHT MODE (Bootstrap Standard)
# ─────────────────────────────────────────────────────────────────

layout = dbc.Container([
    dcc.Store(id='wbin-config-store'),
    
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
                    placeholder="Digita per cercare...",
                    className="mb-4"
                ),
                
                dbc.Button("📈 GENERA GRAFICO", id="wbin-btn-plot", color="primary", className="w-100 mb-3"),
                
                html.Div(id="wbin-status-msg")
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
        m = cfg['meta']
        
        info_content = dbc.Card([
            dbc.CardHeader("INFORMAZIONI FILE", className="fw-bold small"),
            dbc.CardBody([
                html.Div([
                    html.P([html.B("File: "), os.path.basename(path)], className="mb-1 small"),
                    html.P([html.B("Record: "), f"{cfg['total_blocks']:,}"], className="mb-1 small"),
                    html.P([html.B("Canali: "), str(cfg['n_analog'])], className="mb-3 small"),
                ]),
                html.Hr(),
                html.Div([
                    html.Label("CAMPAIGN", className="text-primary fw-bold", style={'fontSize': '10px'}),
                    html.P(m['campaign'], className="small mb-2"),
                    
                    html.Label("CUSTOMER", className="text-primary fw-bold", style={'fontSize': '10px'}),
                    html.P(m['customer'], className="small mb-2"),
                    
                    html.Label("COORDINATOR", className="text-primary fw-bold", style={'fontSize': '10px'}),
                    html.P(m['coordinator'], className="small"),
                ])
            ])
        ], className="shadow-sm")

        return cfg, info_content, dbc.Alert("✓ Caricato", color="success", className="py-1 px-2 small text-center")
    except Exception as e:
        return no_update, no_update, dbc.Alert(f"Errore: {str(e)}", color="danger", className="small")

@callback(
    Output('wbin-tag-dropdown', 'options'),
    Input('wbin-tag-dropdown', 'search_value'),
    State('wbin-config-store', 'data')
)
def cb_filter_tags(search, cfg):
    # Debug: guarda il terminale dove gira lo script per vedere cosa arriva
    print(f"DEBUG - Input ricevuto: '{search}'")
    
    if not search or not cfg: 
        return no_update
    
    # 1. Normalizzazione totale
    # Trasformiamo in maiuscolo e puliamo spazi
    s = search.upper().strip()
    
    # 2. Gestione degli Asterischi (Wildcards)
    # Creiamo una lista di "parole chiave" divise dall'asterisco
    # Se l'utente scrive 004*PV, otteniamo ["004", "PV"]
    # Se scrive **, otteniamo una lista vuota []
    chunks = [c.strip() for c in s.split('*') if c.strip()]
    
    # 3. Caso speciale: solo asterischi (es. * o **)
    # Se non ci sono pezzi di testo ma la ricerca non è vuota, l'utente vuole vedere tutto
    if not chunks and '*' in s:
        return [{'label': f"{ch['tag']} - {ch['desc'][:45]}", 'value': i} 
                for i, ch in enumerate(cfg['analog_channels'][:100])]

    # 4. Ricerca sequenziale (Simulazione Linux Globbing)
    matches = []
    for i, ch in enumerate(cfg['analog_channels']):
        tag_desc = f"{ch['tag']} {ch['desc']}".upper()
        
        # Verifichiamo se tutti i chunks sono presenti nel tag/descrizione
        # e se appaiono nell'ordine corretto
        current_pos = 0
        is_match = True
        
        for chunk in chunks:
            pos = tag_desc.find(chunk, current_pos)
            if pos == -1:
                is_match = False
                break
            # Spostiamo il puntatore dopo il pezzo trovato per il prossimo chunk
            current_pos = pos + len(chunk)
            
        if is_match:
            matches.append({
                'label': f"{ch['tag']} - {ch['desc'][:45]}", 
                'value': i
            })
            
        if len(matches) >= 100: 
            break
                
    return matches

@callback(
    Output('wbin-main-graph', 'figure'),
    Input('wbin-btn-plot', 'n_clicks'),
    [State('wbin-tag-dropdown', 'value'), State('wbin-config-store', 'data')],
    prevent_initial_call=True
)
def cb_render_graph(n, selected_indices, cfg):
    if not selected_indices or not cfg: return no_update
    
    n_pts = 1200
    block_indices = np.unique(np.linspace(0, cfg['total_blocks'] - 1, n_pts).astype(int))
    data_dict = {idx: [] for idx in selected_indices}
    time_axis = []
    
    with open(cfg['path'], 'rb') as f:
        for b_idx in block_indices:
            f.seek(cfg['data_offset'] + (int(b_idx) * cfg['block_size']))
            record = f.read(cfg['block_size'])
            if len(record) < cfg['block_size']: break
            
            time_axis.append(f"{record[4]:02d}:{record[5]:02d}:{record[6]:02d}")
            for ch_idx in selected_indices:
                offset = 13 + (ch_idx * 4)
                val = struct.unpack('>f', record[offset:offset+4])[0]
                data_dict[ch_idx].append(val if abs(val) < 1e15 else 0.0)

    fig = go.Figure()
    for ch_idx in selected_indices:
        ch = cfg['analog_channels'][ch_idx]
        fig.add_trace(go.Scattergl(x=time_axis, y=data_dict[ch_idx], name=ch['tag']))
    
    fig.update_layout(
        template="plotly_white", # Tema chiaro per il grafico
        margin=dict(l=20, r=20, t=30, b=20),
        hovermode="x unified"
    )
    return fig