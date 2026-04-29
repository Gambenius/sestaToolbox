import dash
from dash import html, dcc, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy.optimize import curve_fit
from sklearn.metrics import r2_score
from CoolProp.CoolProp import PropsSI
import io
import base64

dash.register_page(__name__, path="/pump-map")

def pump_physics_model(X, k_hyd, k_leak, k_fric, offset):
    Q_vol, P_pa, mu_pas = X
    
    # Termine Idraulico: Lavoro utile
    term_hyd = k_hyd * (P_pa * Q_vol)
    
    # Termine Leakage: Perdite per trafilamento (P / mu)
    term_leak = k_leak * (P_pa / mu_pas)
    
    # Termine Friction: Attriti viscosi (mu * Q)
    term_fric = k_fric * (mu_pas * Q_vol)
    
    return term_hyd + term_leak + term_fric + offset

def get_fluid_props(temp_c, pres_bar):
    tk = temp_c + 273.15
    pa = (pres_bar + 1.01325) * 1e5
    try:
        visc = PropsSI('V', 'n-Dodecane', 'T', tk, 'P', pa)
    except:
        visc = 0.002  
    return visc

# --- LAYOUT ---
layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H4("Configurazione Mappa", className="mb-3"),
            dbc.Card([
                dbc.CardBody([
                    html.Label("1. Carica file CSV dati pompa"),
                    dcc.Upload(
                        id='upload-data',
                        children=html.Div(['Trascina o ', html.A('scegli CSV')]),
                        style={'width': '100%', 'height': '60px', 'lineHeight': '60px', 'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px', 'textAlign': 'center', 'marginBottom': '15px'}
                    ),
                    
                    html.Div(id='column-selectors', children=[
                        html.Label("Corrente:"),
                        dbc.Row([
                            dbc.Col(dcc.Dropdown(id='col-current'), width=8),
                            dbc.Col(dbc.Checkbox(id="curr-is-deci", label="Valori in [dA]", value=False, style={"fontSize": "0.8rem"}), width=4),
                        ], className="mb-2 align-items-center"),
                        
                        html.Label("Giri [RPM]:"), dcc.Dropdown(id='col-rpm', className="mb-2"),
                        html.Label("Portata Massica [kg/s]:"), dcc.Dropdown(id='col-massflow', className="mb-2"),
                        html.Label("Pressione Ingresso [bar]:"), dcc.Dropdown(id='col-p-in', className="mb-2"),
                        html.Label("Pressione Uscita [bar]:"), dcc.Dropdown(id='col-p-out', className="mb-3"),
                    ], style={'display': 'none'}),

                    html.Hr(),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Densità [kg/m³]"),
                            dbc.Input(id="density-val", type="number", value=1.0, step=0.001, className="mb-3"),
                        ]),
                        dbc.Col([
                            html.Label("Soglia Trip [A]"),
                            dbc.Input(id="trip-limit", type="number", value=30, step=1, className="mb-3"),
                        ])
                    ]),
                    
                    dbc.Button("Genera mappa", id="process-btn", color="danger", className="w-100 mt-2"),
                ])
            ], className="shadow-sm"),
            
            html.Div(id='status-message', className="mt-3"),

            html.Div([
                html.H5("Analisi Modello", className="mt-4"),
                dbc.Card([
                    dbc.CardBody(id="debug-info", style={"fontSize": "0.8rem", "fontFamily": "Courier New"})
                ], color="light", className="shadow-sm")
            ])
        ], width=4),

        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Mappa Prestazioni: Previsione Trip e Dati Reali"),
                dbc.CardBody([
                    dcc.Loading(children=dcc.Graph(id='trip-map-plot', style={'height': '75vh'}))
                ])
            ], className="shadow-sm")
        ], width=8),
    ], className="mt-4"),
    dcc.Store(id='stored-df')
], fluid=True)

# --- CALLBACK: POPOLAMENTO DROPDOWN ---
@callback(
    [Output('col-current', 'options'), Output('col-rpm', 'options'),
     Output('col-massflow', 'options'), Output('col-p-in', 'options'),
     Output('col-p-out', 'options'), Output('column-selectors', 'style'),
     Output('stored-df', 'data'), Output('status-message', 'children')],
    Input('upload-data', 'contents'),
    State('upload-data', 'filename'),
    prevent_initial_call=True
)
def load_csv_columns(contents, filename):
    if not contents:
        return [no_update]*7 + [""]
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
        cols = [{'label': c, 'value': c} for c in df.columns]
        return cols, cols, cols, cols, cols, {'display': 'block'}, df.to_dict('records'), dbc.Alert(f"File caricato: {filename}", color="info")
    except Exception as e:
        return [no_update]*7 + [dbc.Alert(f"Errore: {str(e)}", color="danger")]
    
    
@callback(
    [Output('trip-map-plot', 'figure'),
     Output('status-message', 'children', allow_duplicate=True),
     Output('debug-info', 'children')],
    Input('process-btn', 'n_clicks'),
    [State('stored-df', 'data'),
     State('col-current', 'value'), State('curr-is-deci', 'value'),
     State('col-rpm', 'value'), State('col-massflow', 'value'), 
     State('col-p-in', 'value'), State('col-p-out', 'value'), 
     State('density-val', 'value'), State('trip-limit', 'value')],
    prevent_initial_call=True
)
def update_graph(n_clicks, data, col_i, is_deci, col_rpm, col_q, col_pin, col_pout, rho, trip_limit):
    if not data or not all([col_i, col_rpm, col_q, col_pin, col_pout]):
        return go.Figure(), dbc.Alert("Seleziona tutte le colonne.", color="warning"), ""

    try:
        df = pd.DataFrame(data)
        dens = float(rho) if rho else 1000.0

        # --- 1. PREPARAZIONE DATI (UNITÀ ORIGINALI PER IL PLOT) ---
        df['I_A'] = pd.to_numeric(df[col_i], errors='coerce') / (10.0 if is_deci else 1.0)
        df['P_bar'] = pd.to_numeric(df[col_pout]) - pd.to_numeric(df[col_pin])
        df['Q_kgs'] = pd.to_numeric(df[col_q])
        
        # Pulizia
        df_fit = df[pd.to_numeric(df[col_rpm]) > 10].dropna(subset=['I_A', 'P_bar', 'Q_kgs']).copy()

        # --- 2. CONVERSIONE SI PER IL FITTING ---
        # Passiamo a Pascal e m3/s solo per dare "pasto" i dati al solver fisico
        q_m3s = df_fit['Q_kgs'].values / dens
        p_pa = df_fit['P_bar'].values * 1e5
        mu_si = df_fit.apply(lambda row: get_fluid_props(40, row['P_bar']), axis=1).values
        
        X_data_si = (q_m3s, p_pa, mu_si)
        I_measured = df_fit['I_A'].values

        # Fitting
        popt, _ = curve_fit(pump_physics_model, X_data_si, I_measured, bounds=(0, [1e2, 1e2, 1e9, 45]))
        k_hyd, k_leak, k_fric, offset = popt
        r2_val = r2_score(I_measured, pump_physics_model(X_data_si, *popt))

        # --- 3. GENERAZIONE MAPPA (UNITÀ PLOT: BAR e KG/S) ---
        q_plot_max = df_fit['Q_kgs'].max() * 1.1
        p_plot_max = df_fit['P_bar'].max() * 1.1
        
        q_rng_plot = np.linspace(0, q_plot_max, 50)
        p_rng_plot = np.linspace(0, p_plot_max, 50)
        Q_GRID_PLOT, P_GRID_PLOT = np.meshgrid(q_rng_plot, p_rng_plot)
        
        I_MAP = np.zeros_like(Q_GRID_PLOT)
        for i in range(len(p_rng_plot)):
            # Convertiamo i punti della griglia in SI per usare il modello
            p_pa_grid = p_rng_plot[i] * 1e5
            mu_val = get_fluid_props(40, p_rng_plot[i])
            for j in range(len(q_rng_plot)):
                q_m3s_grid = q_rng_plot[j] / dens
                I_MAP[i, j] = pump_physics_model((q_m3s_grid, p_pa_grid, mu_val), *popt)

        c_min, c_max = min(I_MAP.min(), I_measured.min()), max(I_MAP.max(), I_measured.max())

        # --- 4. PLOT IN BAR E KG/S ---
        fig = go.Figure()
        fig.add_trace(go.Contour(
            z=I_MAP, x=q_rng_plot, y=p_rng_plot, colorscale='Viridis', zmin=c_min, zmax=c_max,
            colorbar=dict(title="Corrente [A]"), opacity=0.7, hoverinfo='skip'
        ))
        fig.add_trace(go.Contour(
            z=I_MAP, x=q_rng_plot, y=p_rng_plot, showscale=False,
            contours=dict(start=trip_limit, end=trip_limit, coloring='none'),
            line=dict(color='red', width=4), name="Trip"
        ))
        fig.add_trace(go.Scattergl(
            x=df_fit['Q_kgs'], y=df_fit['P_bar'], mode='markers',
            marker=dict(color=df_fit['I_A'], colorscale='Viridis', cmin=c_min, cmax=c_max, size=8, line=dict(color='white', width=1)),
            name='Dati Misurati'
        ))

        fig.update_layout(
            xaxis=dict(title="Portata [kg/s]", range=[0, q_plot_max]),
            yaxis=dict(title="ΔP [bar]", range=[0, p_plot_max]),
            template="plotly_white"
        )

        # --- 5. INFO BOX ---
        equation_md = (
            "**Equazione del Modello (Fisica SI):**\n"
            "$$I_{th} = k_{hyd}(P_{Pa} \\cdot Q_{m^3/s}) + k_{leak}(\\frac{P_{Pa}}{\\mu}) + k_{fric}(\\mu \\cdot Q_{m^3/s}) + Offset$$\n"
        )

        debug_content = html.Div([
            dcc.Markdown(equation_md, mathjax=True),
            html.Ul([
                html.Li(f"k_hyd: {k_hyd:.2e} [A/W]"),
                html.Li(f"k_leak: {k_leak:.2e} [A·s]"),
                html.Li(f"k_fric: {k_fric:.2e} [A/(Pa·s·m³/s)]"),
                html.Li(f"Offset: {offset:.2f} [A]"),
                html.Li(f"R² Fit: {r2_val:.4f}")
            ]),
            html.P(f"Assi Grafico: P [bar], Q [kg/s]. Calcolo interno eseguito con densità {dens} kg/m³.", 
                   style={"fontSize": "0.8rem", "color": "gray"})
        ])

        return fig, dbc.Alert("Mappa aggiornata (Bar, kg/s)", color="success"), debug_content

    except Exception as e:
        return go.Figure(), dbc.Alert(f"Errore: {str(e)}", color="danger"), ""