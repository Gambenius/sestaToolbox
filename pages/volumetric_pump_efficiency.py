import dash
from dash import dcc, html, Input, Output, State, callback, no_update
import pandas as pd
import plotly.graph_objects as go
import io
import base64

dash.register_page(__name__, name="Analisi pompe", path='/analisi_pompe')

def render_pump_config(id_prefix, title, color):
    """Genera il box di configurazione per una pompa con colonne separate per Giorno 1 e 2"""
    return html.Div([
        html.H4(title, style={'color': color, 'textAlign': 'center', 'borderBottom': f'2px solid {color}', 'paddingBottom': '10px'}),
        
        html.Div([
            html.Label("Nome Visualizzato:"),
            dcc.Input(id=f'{id_prefix}-name', value=title, style={'width': '100%', 'marginBottom': '15px'}),
        ]),
        
        html.Div([
            # COLONNA GIORNO 1
            html.Div([
                html.B("FILE 1 (Giorno 1)", style={'fontSize': '0.8em', 'display': 'block', 'marginBottom': '5px'}),
                html.Label("Portata (Q):"), dcc.Dropdown(id=f'{id_prefix}-q-f1'),
                html.Label("RPM:"), dcc.Dropdown(id=f'{id_prefix}-rpm-f1', style={'marginBottom': '10px'}),
                html.Label("P1 (In):"), dcc.Dropdown(id=f'{id_prefix}-p1-f1'),
                html.Label("P2 (Out):"), dcc.Dropdown(id=f'{id_prefix}-p2-f1'),
            ], style={'width': '48%', 'padding': '5px', 'backgroundColor': '#fff', 'borderRadius': '5px'}),
            
            # COLONNA GIORNO 2
            html.Div([
                html.B("FILE 2 (Giorno 2)", style={'fontSize': '0.8em', 'display': 'block', 'marginBottom': '5px'}),
                html.Label("Portata (Q):"), dcc.Dropdown(id=f'{id_prefix}-q-f2'),
                html.Label("RPM:"), dcc.Dropdown(id=f'{id_prefix}-rpm-f2', style={'marginBottom': '10px'}),
                html.Label("P1 (In):"), dcc.Dropdown(id=f'{id_prefix}-p1-f2'),
                html.Label("P2 (Out):"), dcc.Dropdown(id=f'{id_prefix}-p2-f2'),
            ], style={'width': '48%', 'padding': '5px', 'backgroundColor': '#fff', 'borderRadius': '5px'}),
        ], style={'display': 'flex', 'justifyContent': 'space-between'})
        
    ], style={
        'flex': '1', 'minWidth': '400px', 'margin': '10px', 'padding': '20px',
        'border': f'2px solid {color}', 'borderRadius': '15px', 'backgroundColor': '#f3f4f6'
    })

layout = html.Div([
    html.H2("Analisi Comparativa cilindrata effettiva", style={'textAlign': 'center', 'marginBottom': '30px'}),
    html.P(
        "Carica due file CSV contenenti le pressioni di aspirazione, mandata, il numero di giri e la portata massica di almeno una pompa.\n"
        "È necessario caricare entrambi i CSV per poter plottare il confronto.",
        style={
            'textAlign': 'justify',   # Testo giustificato
            'color': '#555555',       # Grigio scuro per miglior leggibilità
            'padding': '10px',        # Spazio interno
            'fontSize': '16px'        # Dimensione del font
        }
    ),
    # Sezione Upload e Densità
    html.Div([
        html.Div([
            html.B("File Giorno 1:"),
            dcc.Upload(id='upload-f1', children=html.Div(id='text-f1', children='Carica File 1'), 
                       style={'height': '45px', 'lineHeight': '45px', 'border': '2px dashed #999', 'textAlign': 'center', 'borderRadius': '10px', 'marginBottom': '10px'}),
            html.Label("Densità (G1):"),
            dcc.Input(id='dens-f1', type='number', value=1.0, step=0.001, style={'width': '100%'})
        ], style={'width': '45%'}),
        
        html.Div([
            html.B("File Giorno 2:"),
            dcc.Upload(id='upload-f2', children=html.Div(id='text-f2', children='Carica File 2'), 
                       style={'height': '45px', 'lineHeight': '45px', 'border': '2px dashed #999', 'textAlign': 'center', 'borderRadius': '10px', 'marginBottom': '10px'}),
            html.Label("Densità (G2):"),
            dcc.Input(id='dens-f2', type='number', value=1.0, step=0.001, style={'width': '100%'})
        ], style={'width': '45%'}),
    ], style={'display': 'flex', 'justifyContent': 'space-around', 'marginBottom': '30px'}),

    # Slider Alpha
    html.Div([
        html.Label("Trasparenza Punti (Alpha):", style={'fontWeight': 'bold'}),
        dcc.Slider(id='alpha-slider', min=0.1, max=1, step=0.1, value=0.6, 
                   marks={i/10: str(i/10) for i in range(1, 11)})
    ], style={'width': '70%', 'margin': 'auto', 'marginBottom': '30px'}),

    # Container Selezioni
    html.Div(id='selection-container', children=[
        html.Div([
            render_pump_config('p1', 'Pompa 1', '#FF4136'),
            render_pump_config('p2', 'Pompa 2', '#0074D9'),
        ], style={'display': 'flex', 'flexWrap': 'wrap', 'justifyContent': 'center'}),

        html.Button('GENERA ANALISI GRAFICA', id='btn-plot-comp', n_clicks=0, 
                    style={'width': '100%', 'marginTop': '25px', 'height': '50px', 
                           'backgroundColor': '#2c3e50', 'color': 'white', 'fontSize': '16px', 
                           'borderRadius': '10px', 'cursor': 'pointer'})
    ], style={'display': 'none'}),

    # Risultati
    html.Hr(style={'marginTop': '40px'}),
    dcc.Loading(dcc.Graph(id='efficiency-comp-graph', style={'height': '55vh'})),
    dcc.Loading(dcc.Graph(id='time-series-graph', style={'height': '55vh', 'marginTop': '30px'})),

    dcc.Store(id='store-f1'),
    dcc.Store(id='store-f2')
], style={'padding': '40px', 'fontFamily': 'Arial, sans-serif'})

# --- CALLBACK: CARICAMENTO FILE ---
@callback(
    [Output('store-f1', 'data'), Output('store-f2', 'data'),
     Output('selection-container', 'style'),
     Output('text-f1', 'children'), Output('text-f2', 'children')] +
    [Output(f'{p}-{v}-{f}', 'options') for p in ['p1', 'p2'] for v in ['q', 'rpm', 'p1', 'p2'] for f in ['f1', 'f2']],
    [Input('upload-f1', 'contents'), Input('upload-f2', 'contents')],
    [State('upload-f1', 'filename'), State('upload-f2', 'filename')]
)
def handle_files(c1, c2, n1, n2):
    if not c1 or not c2: return [no_update]*21
    
    def decode_df(c):
        decoded = base64.b64decode(c.split(',')[1])
        return pd.read_csv(io.StringIO(decoded.decode('utf-8')), sep=None, engine='python')

    df1, df2 = decode_df(c1), decode_df(c2)
    cols1 = [{'label': c, 'value': c} for c in df1.columns]
    cols2 = [{'label': c, 'value': c} for c in df2.columns]
    
    opts = []
    for p in range(2): 
        for v in range(4): 
            opts.append(cols1) 
            opts.append(cols2) 

    return (df1.to_dict('records'), df2.to_dict('records'), {'display': 'block'}, 
            html.B(f"✅ {n1}"), html.B(f"✅ {n2}"), *opts)

# --- CALLBACK: GENERAZIONE GRAFICI ---
@callback(
    [Output('efficiency-comp-graph', 'figure'),
     Output('time-series-graph', 'figure')],
    Input('btn-plot-comp', 'n_clicks'),
    Input('alpha-slider', 'value'),
    [State('store-f1', 'data'), State('store-f2', 'data'),
     State('dens-f1', 'value'), State('dens-f2', 'value')] +
    [State(f'{p}-{v}-{f}', 'value') for p in ['p1', 'p2'] for v in ['q', 'rpm', 'p1', 'p2'] for f in ['f1', 'f2']] +
    [State('p1-name', 'value'), State('p2-name', 'value')]
)
def update_all_plots(n, alpha, data1, data2, dens1, dens2,
                    p1_q_f1, p1_q_f2, p1_rpm_f1, p1_rpm_f2, p1_p1_f1, p1_p1_f2, p1_p2_f1, p1_p2_f2,
                    p2_q_f1, p2_q_f2, p2_rpm_f1, p2_rpm_f2, p2_p1_f1, p2_p1_f2, p2_p2_f1, p2_p2_f2,
                    n1, n2):
    if not data1 or not data2 or n == 0: 
        return go.Figure(), go.Figure()
    
    df1, df2 = pd.DataFrame(data1), pd.DataFrame(data2)
    
    # Sicurezza sui valori di densità
    d1 = dens1 if dens1 and dens1 != 0 else 1.0
    d2 = dens2 if dens2 and dens2 != 0 else 1.0

    fig_eff = go.Figure()
    fig_time = go.Figure()

    def add_pump_traces(df, q, rpm, p_in, p_out, density, name, color, is_f2):
        required = [q, rpm, p_in, p_out]
        if all(required) and all(c in df.columns for c in required):
            dp = df[p_out] - df[p_in]
            
            # Formula aggiornata: Q / (RPM * Densità)
            q_norm = df[q] / (df[rpm].replace(0, float('nan')) * density)
            
            time_col = 'Time' if 'Time' in df.columns else df.columns[0]
            
            # Grafico 1: Efficienza vs Delta P
            fig_eff.add_trace(go.Scattergl(
                x=dp, y=q_norm, mode='markers', name=name,
                marker=dict(color=color, opacity=alpha, size=6),
                hovertemplate=f"<b>{name}</b><br>ΔP: %{{x:.3f}}<br>Q/(RPM*ρ): %{{y:.6f}}<extra></extra>"
            ))

            # Grafico 2: Serie Temporale
            fig_time.add_trace(go.Scattergl(
                x=df[time_col], y=q_norm, mode='markers' if is_f2 else 'lines', 
                name=name, line=dict(color=color, width=1.5),
                marker=dict(size=4, opacity=alpha),
                hovertemplate=f"<b>{name}</b><br>Ora: %{{x}}<br>Q/(RPM*ρ): %{{y:.6f}}<extra></extra>"
            ))

    # Definizione set dati e colori (Passiamo d1 o d2 a seconda del file)
    configs = [
        # Pompa 1
        (df1, p1_q_f1, p1_rpm_f1, p1_p1_f1, p1_p2_f1, d1, f"{n1} (G1)", '#FF4136', False),
        (df2, p1_q_f2, p1_rpm_f2, p1_p1_f2, p1_p2_f2, d2, f"{n1} (G2)", '#85144B', True),
        # Pompa 2
        (df1, p2_q_f1, p2_rpm_f1, p2_p1_f1, p2_p2_f1, d1, f"{n2} (G1)", '#0074D9', False),
        (df2, p2_q_f2, p2_rpm_f2, p2_p1_f2, p2_p2_f2, d2, f"{n2} (G2)", '#001F3F', True),
    ]

    for conf in configs:
        add_pump_traces(*conf)

    fig_eff.update_layout(
        title="Cilindrata effettiva (Q / (RPM * ρ)) [cm³/giro] vs ΔP [bar]",
        xaxis_title="ΔP [P_out - P_in] [bar]", yaxis_title="Q / (RPM * ρ) [cm³/giro]",
        template="seaborn", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    fig_time.update_layout(
        title="Andamento temporale cilindrata effettiva [cm³/giro]",
        xaxis_title="Orario", 
        yaxis_title="Q / (RPM * ρ) [cm³/giro]",
        template="seaborn",
        xaxis=dict(
            tickangle=45, 
            type='category',
            nticks=10, 
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    return fig_eff, fig_time