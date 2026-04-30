import dash
from dash import html, dcc, callback, Input, Output, State, dash_table, no_update
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import io
import base64

dash.register_page(__name__, path="/pysr-regressor")

layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H4("Symbolic Regression (PySR)", className="mb-3"),
            dbc.Card([
                dbc.CardBody([
                    html.Label("1. Carica Dataset"),
                    dcc.Upload(
                        id='pysr-upload-data',
                        children=html.Div(['Trascina o ', html.A('Scegli CSV')]),
                        style={'width': '100%', 'height': '60px', 'lineHeight': '60px', 'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px', 'textAlign': 'center', 'marginBottom': '15px'}
                    ),
                    
                    html.Div(id='pysr-mapping-container', children=[
                        html.Label("2. Mappatura Canali:"),
                        html.Div(id='pysr-radio-grid', className="mb-3", style={"maxHeight": "300px", "overflowY": "auto", "border": "1px solid #ddd", "padding": "10px", "borderRadius": "5px"}),
                        
                        html.Label("Campioni Random:"),
                        dbc.Input(id="pysr-sample-size", type="number", value=100, step=1, className="mb-3"),
                    ], style={'display': 'none'}),

                    html.Hr(),
                    html.Label("Parametri Evoluzione:"),
                    dbc.InputGroup([
                        dbc.InputGroupText("Iterazioni"),
                        dbc.Input(id="pysr-iters", type="number", value=20),
                    ], className="mb-2", size="sm"),
                    
                    dbc.Button("Normalizza e Avvia PySR", id="pysr-run-btn", color="primary", className="w-100 mt-2"),
                ])
            ], className="shadow-sm"),
            
            html.Div(id='pysr-status', className="mt-3")
        ], width=5),

        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Risultati Regressione Simbolica"),
                dbc.CardBody([
                    dcc.Loading(
                        id="pysr-loading",
                        children=html.Div(id="pysr-output-area")
                    )
                ])
            ], className="shadow-sm")
        ], width=7),
    ], className="mt-4"),
    dcc.Store(id='pysr-stored-df')
], fluid=True)

# --- CALLBACK: GENERAZIONE GRIGLIA RADIO BUTTONS ---
@callback(
    [Output('pysr-radio-grid', 'children'),
     Output('pysr-mapping-container', 'style'),
     Output('pysr-stored-df', 'data')],
    Input('pysr-upload-data', 'contents'),
    prevent_initial_call=True
)
def create_radio_grid(contents):
    if not contents:
        return no_update, no_update, no_update
    
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    df = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
    
    # Intestazione della griglia
    header = dbc.Row([
        dbc.Col(html.B("Colonna"), width=6),
        dbc.Col(html.B("X"), width=2, className="text-center"),
        dbc.Col(html.B("Y"), width=2, className="text-center"),
        dbc.Col(html.B("Ignora"), width=2, className="text-center"),
    ], className="mb-2 pb-2 border-bottom")

    rows = [header]
    for col in df.columns:
        rows.append(dbc.Row([
            dbc.Col(html.Span(col, style={"fontSize": "0.9rem"}), width=6),
            dbc.Col(
                dcc.RadioItems(
                    id={'type': 'pysr-col-role', 'index': col},
                    options=[
                        {'label': '', 'value': 'X'},
                        {'label': '', 'value': 'Y'},
                        {'label': '', 'value': 'Ignore'},
                    ],
                    value='Ignore',
                    inline=True,
                    inputStyle={"margin-right": "5px", "margin-left": "5px"},
                    labelStyle={"display": "inline-block"}
                ), width=6, className="text-center"
            ),
        ], className="align-items-center mb-1"))

    return rows, {'display': 'block'}, df.to_dict('records')

# --- CALLBACK: ESECUZIONE PYSR ---
@callback(
    [Output("pysr-output-area", "children"),
     Output("pysr-status", "children")],
    Input("pysr-run-btn", "n_clicks"),
    [State("pysr-stored-df", "data"),
     State({'type': 'pysr-col-role', 'index': dash.ALL}, 'value'),
     State({'type': 'pysr-col-role', 'index': dash.ALL}, 'id'),
     State("pysr-iters", "value"),
     State("pysr-sample-size", "value")],
    prevent_initial_call=True
)
def execute_pysr(n_clicks, data, roles, ids, iters, sample_n):
    from pysr import PySRRegressor
    # Identifica quali colonne sono X e quale è Y
    cols_x = [id['index'] for id, role in zip(ids, roles) if role == 'X']
    cols_y = [id['index'] for id, role in zip(ids, roles) if role == 'Y']

    if not data or not cols_x or len(cols_y) != 1:
        return "", dbc.Alert("Seleziona almeno una X e esattamente una Y!", color="warning")

    col_y = cols_y[0]

    try:
        full_df = pd.DataFrame(data).dropna(subset=cols_x + [col_y])
        n_points = min(int(sample_n), len(full_df))
        df = full_df.sample(n=n_points, random_state=42)

        # Estrazione e Normalizzazione
        X_raw = df[cols_x].values
        y_raw = df[col_y].values.reshape(-1, 1)

        X_mean, X_std = X_raw.mean(axis=0), X_raw.std(axis=0)
        y_mean, y_std = y_raw.mean(), y_raw.std()

        # Evitiamo divisioni per zero
        X_std[X_std == 0] = 1.0
        y_std = 1.0 if y_std == 0 else y_std

        X_norm = (X_raw - X_mean) / X_std
        y_norm = ((y_raw - y_mean) / y_std).ravel()

        # Debug Terminale
        print(f"\n--- AVVIO PYSR (Sample: {n_points}) ---")
        print(f"Features: {cols_x} | Target: {col_y}")
        print(f"X_mean: {X_mean} | y_mean: {y_mean:.4f}")

        model = PySRRegressor(
            niterations=iters,
            binary_operators=["+", "*", "-", "/"],
            unary_operators=["cos", "exp", "sin", "inv(x) = 1/x"],
            extra_sympy_mappings={"inv": lambda x: 1 / x},
            verbosity=0
        )

        model.fit(X_norm, y_norm)

        res_df = model.equations_[['complexity', 'loss', 'equation']]
        
        table = dash_table.DataTable(
            data=res_df.to_dict('records'),
            columns=[{"name": i.capitalize(), "id": i} for i in res_df.columns],
            style_cell={'textAlign': 'left', 'fontFamily': 'monospace', 'fontSize': '0.85rem'},
            page_size=10
        )

        return html.Div([
            dbc.Alert(f"Modello normalizzato completato su {n_points} campioni.", color="info"),
            table
        ]), dbc.Alert("Esecuzione terminata con successo!", color="success")

    except Exception as e:
        return "", dbc.Alert(f"Errore: {str(e)}", color="danger")