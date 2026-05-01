import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import os
from datetime import datetime

# Registrazione della pagina
dash.register_page(__name__, path="/feedback")

layout = dbc.Container([
    html.H2("Richieste e Segnalazioni", className="mb-4"),
    html.P("Utilizza questo modulo per richiedere nuove funzionalità, modifiche o segnalare bug."),
    
    dbc.Card(
        dbc.CardBody([
            dbc.Label("Oggetto"),
            dbc.Input(id="feedback-subject", placeholder="Sto codice è lezzo!", type="text", className="mb-3"),
            
            dbc.Label("Contenuto della richiesta"),
            dbc.Textarea(
                id="feedback-content",
                placeholder="s'è trovato un baho, vedrai",
                style={'height': '200px'},
                className="mb-3"
            ),
            
            dbc.Button("Invia Segnalazione", id="btn-send-feedback", color="primary", n_clicks=0),
            
            html.Div(id="feedback-output", className="mt-3")
        ]),
        className="shadow-sm"
    )
], fluid=True)

@callback(
    Output("feedback-output", "children"),
    Input("btn-send-feedback", "n_clicks"),
    State("feedback-subject", "value"),
    State("feedback-content", "value"),
    prevent_initial_call=True
)
def save_feedback(n_clicks, subject, content):
    if not subject or not content:
        return dbc.Alert("Per favore, compila entrambi i campi prima di inviare.", color="warning")
    
    # Percorso del file (cartella utils relativa alla root del progetto)
    file_path = os.path.join("utils", "complaints.txt")
    
    # Assicurati che la cartella utils esista
    if not os.path.exists("utils"):
        os.makedirs("utils")
        
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"{'='*50}\n")
            f.write(f"DATA: {timestamp}\n")
            f.write(f"OGGETTO: {subject.upper()}\n")
            f.write(f"CONTENUTO:\n{content}\n")
            f.write(f"{'='*50}\n\n")
            
        return dbc.Alert("Segnalazione salvata con successo nel file utils/complaints.txt!", color="success")
    
    except Exception as e:
        return dbc.Alert(f"Errore durante il salvataggio: {str(e)}", color="danger")