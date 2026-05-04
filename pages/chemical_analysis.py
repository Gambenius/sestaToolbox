import dash
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import io
import base64

dash.register_page(__name__, path="/chem")

# --- COSTANTI CHIMICHE ---
CHEM_DATA = {
    "CH4":  {"C": 1, "O2": 2}, "C2H6": {"C": 2, "O2": 3.5},
    "C3H8": {"C": 3, "O2": 5}, "C4H10":{"C": 4, "O2": 6.5},
    "C5H12":{"C": 5, "O2": 8}, "C6H14":{"C": 6, "O2": 9.5},
    "CO":   {"C": 1, "O2": 0.5}, "H2":  {"C": 0, "O2": 0.5}
}
GAS_COLS = {
    "XCH4":"CH4","XC2H6":"C2H6","XC3H8":"C3H8","XC4H10":"C4H10",
    "XC5H12":"C5H12","XC6H14":"C6H14","XCO":"CO","XH2":"H2"
}

layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H4("Analisi Chimiche", className="mb-3"),
            dbc.Card([
                dbc.CardBody([
                    html.Label("1. Carica CSV"),
                    dcc.Upload(id='up-chem', children=html.Div(['Trascina o ', html.A('Seleziona')]),
                               style={'width': '100%', 'height': '50px', 'lineHeight': '50px', 'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px', 'textAlign': 'center', 'marginBottom': '15px'}),
                    html.Label("2. Range Temporale"),
                    dbc.Input(id="t-start", type="text", value="00:00:00", className="mb-1"),
                    dbc.Input(id="t-end", type="text", value="23:59:00", className="mb-4"),
                    dbc.Button("Aggiorna Analisi", id="btn-chem", color="primary", className="w-100"),
                ])
            ], className="shadow-sm"),
            html.Div(id='msg-chem', className="mt-3")
        ], width=3),

        dbc.Col([
            dbc.Tabs([
                dbc.Tab(label="Trend Temporali", tab_id="tab-time"),
                dbc.Tab(label="Ostwald & CO2eq", tab_id="tab-ostwald"),
                dbc.Tab(label="Frazioni & CO2max", tab_id="tab-frac"),
            ], id="tabs-chem", active_tab="tab-time"),
            dcc.Loading(html.Div(id="tab-content", className="mt-3"))
        ], width=9),
    ], className="mt-4")
], fluid=True)

@callback(
    [Output("tab-content", "children"), Output("msg-chem", "children")],
    [Input("btn-chem", "n_clicks"), Input("tabs-chem", "active_tab")],
    [State("up-chem", "contents"), State("t-start", "value"), State("t-end", "value")],
    prevent_initial_call=True
)
def update_all_plots(n, active_tab, contents, t1_str, t2_str):
    if not contents:
        return "", dbc.Alert("Carica un file per visualizzare i grafici.", color="info")

    try:
        _, s = contents.split(',')
        df = pd.read_csv(io.StringIO(base64.b64decode(s).decode('utf-8')))
        df.columns = [c.strip() for c in df.columns]
        
        df['TIME_dt'] = pd.to_datetime(df['Time'], format='%H:%M:%S')
        t1 = datetime.strptime(t1_str, '%H:%M:%S').time()
        t2 = datetime.strptime(t2_str, '%H:%M:%S').time()
        mask = (df['TIME_dt'].dt.time >= t1) & (df['TIME_dt'].dt.time <= t2)
        df_f = df.loc[mask].reset_index(drop=True)

        if active_tab == "tab-time":
            # Creazione di 3 subplot verticali con asse X comune
            fig = make_subplots(
                rows=3, cols=1, 
                shared_xaxes=True, 
                vertical_spacing=0.05,
                subplot_titles=(
                    "Ossidi di Azoto (NO, NOx) [ppm]", 
                    "Gas Principali (CO2, O2) [%]", 
                    "Incombusti e Carbonio (CO, THC) [ppm]"
                )
            )
            
            # --- SUBPLOT 1: AZOTO (ppm) ---
            n2_tags = {
                'CHIMICHE.ARM1.NOCHEMI': 'NO A1', 'CHIMICHE.ARM1.NOXCHEMI': 'NOx A1',
                'CHIMICHE.ARM2.NOCHEMI': 'NO A2', 'CHIMICHE.ARM2.NOXCHEMI': 'NOx A2'
            }
            for tag, label in n2_tags.items():
                if tag in df_f.columns:
                    fig.add_trace(go.Scatter(x=df_f['TIME_dt'], y=df_f[tag], name=label, legend="legend1"), row=1, col=1)

            # --- SUBPLOT 2: CO2 e O2 (%) ---
            perc_tags = {
                'CHIMICHE.ARM1.PB.CO2': 'CO2 A1', 'CHIMICHE.ARM1.PB.O2': 'O2 A1',
                'CHIMICHE.ARM2.PB.CO2': 'CO2 A2', 'CHIMICHE.ARM2.PB.O2': 'O2 A2'
            }
            for tag, label in perc_tags.items():
                if tag in df_f.columns:
                    fig.add_trace(go.Scatter(x=df_f['TIME_dt'], y=df_f[tag], name=label, legend="legend2"), row=2, col=1)

            # --- SUBPLOT 3: THC e CO (ppm) ---
            ppm_tags = {
                'CHIMICHE.ARM1.PB.CO': 'CO A1', 'CHIMICHE.ARM1.PB.HC': 'THC A1',
                'CHIMICHE.ARM2.PB.CO': 'CO A2', 'CHIMICHE.ARM2.PB.HC': 'THC A2'
            }
            for tag, label in ppm_tags.items():
                if tag in df_f.columns:
                    fig.add_trace(go.Scatter(x=df_f['TIME_dt'], y=df_f[tag], name=label, legend="legend3"), row=3, col=1)
            
            # Formattazione assi e posizionamento legende INTERNE
            fig.update_layout(
                height=1000, 
                template="plotly_white",
                # Legenda 1 (Top)
                legend1=dict(x=0.01, y=0.98, bgcolor="rgba(255,255,255,0.5)", bordercolor="Black", borderwidth=1),
                # Legenda 2 (Middle)
                legend2=dict(x=0.01, y=0.65, bgcolor="rgba(255,255,255,0.5)", bordercolor="Black", borderwidth=1),
                # Legenda 3 (Bottom)
                legend3=dict(x=0.01, y=0.32, bgcolor="rgba(255,255,255,0.5)", bordercolor="Black", borderwidth=1),
            )
            
            # Fix finale asse X per rimuovere la data 1900
            fig.update_xaxes(tickformat="%H:%M:%S")
            fig.update_yaxes(title_text="ppm", row=1, col=1)
            fig.update_yaxes(title_text="%", row=2, col=1)
            fig.update_yaxes(title_text="ppm", row=3, col=1)
            
            return dcc.Graph(figure=fig), ""

        elif active_tab == "tab-ostwald":
            fig = make_subplots(rows=1, cols=2, subplot_titles=("ARM 1", "ARM 2"))
            for i, arm in enumerate(["ARM1", "ARM2"]):
                o2, co2, co = f'CHIMICHE.{arm}.PB.O2', f'CHIMICHE.{arm}.PB.CO2', f'CHIMICHE.{arm}.PB.CO'
                if o2 in df_f.columns and co2 in df_f.columns:
                    co2eq = df_f[co2] + df_f[co]/10000
                    fig.add_trace(go.Scatter(x=df_f[o2], y=df_f[co2], name=f"CO2 {arm}", mode='lines', line=dict(color='black')), row=1, col=i+1)
                    fig.add_trace(go.Scatter(x=df_f[o2], y=co2eq, name=f"CO2eq {arm}", mode='lines', line=dict(color='blue')), row=1, col=i+1)
            
            fig.update_layout(height=500, template="plotly_white", xaxis_title="O2 [%]", yaxis_title="CO2 [%]")
            return dcc.Graph(figure=fig), ""

        elif active_tab == "tab-frac":
            avail_gas = [c for c in GAS_COLS if c in df_f.columns]
            if not avail_gas: return "", dbc.Alert("Colonne gas non trovate.", color="danger")
            
            fuel_sum = df_f[avail_gas].sum(axis=1).replace(0, 1)
            num, den = 0, 0
            for c, f in GAS_COLS.items():
                if c in df_f.columns:
                    x = df_f[c] / fuel_sum
                    num += x * CHEM_DATA[f]["C"]
                    den += x * (CHEM_DATA[f]["C"] + 3.76 * CHEM_DATA[f]["O2"])
            
            avg_co2max = (100 * num / den).mean()

            fig = make_subplots(rows=1, cols=2, subplot_titles=("Teorico ARM1", "Teorico ARM2"))
            for i, arm in enumerate(["ARM1", "ARM2"]):
                o2, co2, co = f'CHIMICHE.{arm}.PB.O2', f'CHIMICHE.{arm}.PB.CO2', f'CHIMICHE.{arm}.PB.CO'
                if o2 in df_f.columns:
                    co2eq = df_f[co2] + df_f[co]/10000
                    fig.add_trace(go.Scatter(x=df_f[o2], y=co2eq, mode='markers', name=f"Reale {arm}", marker=dict(size=3, opacity=0.4)), row=1, col=i+1)
                    fig.add_trace(go.Scatter(x=[20.95, 0], y=[0, avg_co2max], mode='lines', name=f"Teorico ({avg_co2max:.2f}%)", line=dict(color='red', width=3)), row=1, col=i+1)

            fig.update_layout(height=500, template="plotly_white", xaxis_title="O2 [%]", yaxis_title="CO2eq [%]")
            return dcc.Graph(figure=fig), ""

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return "", dbc.Alert(f"Errore: {str(e)}", color="danger")