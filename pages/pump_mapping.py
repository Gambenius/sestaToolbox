import dash
from dash import html, dcc, callback, Input, Output, State, clientside_callback
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy.optimize import curve_fit
from sklearn.metrics import r2_score
from CoolProp.CoolProp import PropsSI
import io
import base64

from utils.ui_components import create_tag_copy_section

dash.register_page(__name__, name="Mappa Gasolio 09CA004")

# --- DATABASE CONFIGURATION ---
PUMP_CONFIG = {
    "CA004": {
        "F023MIS1": "portata_pompa [g/s]",
        "F024MIS2": "pressione_pompa [bar]",
        "F025MIS3": "corrente_inverter [A]",
        "T001MIS1": "temperatura_olio [°C]"
    },
    "CA550": {
        "P055MIS1": "pressione_mandata [bar]",
        "T055MIS1": "temperatura_aspirazione [°C]",
        "F055MIS2": "portata_massa [g/s]"
    }
}

# --- FUNZIONI FISICHE ---
def pump_physics_model(X, k_hyd, k_leak, k_fric, offset):
    Q_mass, P, mu = X
    # Modello: I = k_hyd·P·Q + k_leak·P/μ + k_fric·μ·Q + offset
    return (k_hyd * P * Q_mass) + (k_leak * P / mu) + (k_fric * mu * Q_mass) + offset

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
            html.H4("Parametri Modello", className="mb-3"),
            dbc.Card([
                dbc.CardBody([
                    create_tag_copy_section(PUMP_CONFIG),
                    html.Hr(),
                    html.Label("1. Carica dati da archiviazione binaria"),
                    dcc.Upload(
                        id='upload-data',
                        children=html.Div(['Trascina o ', html.A('scegli CSV')]),
                        style={'width': '100%', 'height': '60px', 'lineHeight': '60px', 'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px', 'textAlign': 'center', 'marginBottom': '15px'}
                    ),
                    html.Label("2. Soglia Trip Inverter [A]"),
                    dbc.Input(id="trip-limit", type="number", value=30, step=1, className="mb-4"),
                    dbc.Button("Genera mappa", id="process-btn", color="danger", className="w-100"),
                ])
            ], className="shadow-sm"),
            
            html.Div(id='status-message', className="mt-3"),

            html.Div([
                html.H5("Info Debug", className="mt-4"),
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
    ], className="mt-4")
], fluid=True)

# --- CALLBACKS UI ---
@callback(
    [Output("tag-box", "value"),
     Output("hidden-copy-storage", "data")],
    Input("pump-selector", "value")
)
def update_tag_display(selected_pump):
    tags_dict = PUMP_CONFIG.get(selected_pump, {})
    display_text = "\n".join([f"{tag}  <-- {desc}" for tag, desc in tags_dict.items()])
    copy_text = "\n".join(tags_dict.keys())
    return display_text, copy_text

dash.clientside_callback(
    """
    function(n_clicks, text_to_copy) {
        if (n_clicks > 0 && text_to_copy) {
            navigator.clipboard.writeText(text_to_copy);
            return "Copiato!";
        }
        return "Copia Nomi Punti";
    }
    """,
    Output("copy-btn", "children"),
    Input("copy-btn", "n_clicks"),
    State("hidden-copy-storage", "data"),
    prevent_initial_call=True
)

# --- CALLBACK PRINCIPALE ---
@callback(
    [Output('trip-map-plot', 'figure'),
     Output('status-message', 'children'),
     Output('debug-info', 'children')],
    Input('process-btn', 'n_clicks'),
    [State('upload-data', 'contents'),
     State('trip-limit', 'value')],
    prevent_initial_call=True
)
def update_graph(n_clicks, contents, trip_limit):
    if not contents:
        return go.Figure(), dbc.Alert("Attenzione: Caricare un file CSV.", color="warning"), ""

    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
        df.columns = [c.strip().lower() for c in df.columns]
        
        required_cols = ['time', 'oil_temp', 'pump_massflow', 'pressure_jump', 'pump_current']
        if not all(c in df.columns for c in required_cols):
            return go.Figure(), dbc.Alert("Errore: colonne mancanti nel CSV.", color="danger"), ""

        # Fitting del modello
        df['mu'] = df.apply(lambda row: get_fluid_props(row['oil_temp'], row['pressure_jump']), axis=1)
        X_data = (df['pump_massflow'].values, df['pressure_jump'].values, df['mu'].values)
        I_measured = df['pump_current'].values
        
        popt, _ = curve_fit(pump_physics_model, X_data, I_measured, bounds=(0, np.inf))
        k_hyd, k_leak, k_fric, offset = popt
        r2_val = r2_score(I_measured, pump_physics_model(X_data, *popt))

        # --- ANALISI AFFIDABILITÀ ---
        warnings = []
        if offset > 15:
            warnings.append(html.Li("🚩 OFFSET ELEVATO: Assorbimento a vuoto stimato >15A. Possibili attriti fissi o dati mancanti a basso carico.", style={"color": "#d9534f"}))
        if k_leak < 1e-10 or k_fric < 1e-10:
            warnings.append(html.Li("🚩 COEFFICIENTI DEBOLI: I termini viscosi/perdite sono quasi nulli. Il modello è ipersemplificato.", style={"color": "#f0ad4e"}))
        if r2_val < 0.85:
            warnings.append(html.Li(f"🚩 FIT INCERTO (R²={r2_val:.2f}): Scostamento elevato tra modello e realtà.", style={"color": "#d9534f"}))

        # Generazione Mappa
        p_max, m_max = df['pressure_jump'].max() * 1.2, df['pump_massflow'].max() * 1.1
        m_range, p_range = np.linspace(0, m_max, 50), np.linspace(0, p_max, 50)
        M_GRID, P_GRID = np.meshgrid(m_range, p_range)
        avg_temp = df['oil_temp'].mean()
        
        I_EXTRAP = np.zeros_like(M_GRID)
        for i in range(len(p_range)):
            mu = get_fluid_props(avg_temp, p_range[i])
            for j in range(len(m_range)):
                I_EXTRAP[i, j] = pump_physics_model((m_range[j], p_range[i], mu), *popt)

        fig = go.Figure()
        fig.add_trace(go.Contour(
            z=I_EXTRAP, x=m_range, y=p_range, colorscale='Viridis', 
            colorbar=dict(title="Corrente [A]")
        ))
        fig.add_trace(go.Contour(
            z=I_EXTRAP, x=m_range, y=p_range, showscale=False, 
            contours=dict(start=trip_limit, end=trip_limit, coloring='none'), 
            line=dict(color='red', width=4), name=f"Soglia Trip ({trip_limit}A)"
        ))
        fig.add_trace(go.Scatter(
            x=df['pump_massflow'], y=df['pressure_jump'], mode='markers', 
            marker=dict(color='white', size=5, opacity=0.6, line=dict(color='black', width=1)),
            name='Punti Misurati'
        ))

        fig.update_layout(
            xaxis_title="Portata Massa [g/s]", yaxis_title="Salto di Pressione [bar]",
            template="plotly_white",
            legend=dict(yanchor="top", y=0.98, xanchor="left", x=0.02, bgcolor="rgba(255, 255, 255, 0.7)")
        )

        debug_content = html.Div([
            html.B("MODELLO RISULTANTI:"),
            html.Ul([
                html.Li(f"k_hyd: {k_hyd:.2e}"),
                html.Li(f"k_leak: {k_leak:.2e}"),
                html.Li(f"k_fric: {k_fric:.2e}"),
                html.Li(f"Offset: {offset:.2f} [A]"),
                html.Li(f"R² Fit: {r2_val:.4f}"),
            ]),
            html.Div([
                html.B("ANALISI TECNICA:"),
                html.Ul(warnings if warnings else [html.Li("✅ Modello coerente con i dati.", style={"color": "green"})])
            ], style={"marginTop": "10px", "borderTop": "1px solid #ddd", "paddingTop": "10px"})
        ])

        return fig, dbc.Alert("Mappa aggiornata", color="success"), debug_content

    except Exception as e:
        return go.Figure(), dbc.Alert(f"Errore: {str(e)}", color="danger"), html.P("Errore calcolo.")