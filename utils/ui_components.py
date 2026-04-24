import dash_bootstrap_components as dbc
from dash import dcc, html

def create_tag_copy_section(pump_database):
    """
    Genera il layout per la selezione pompa e copia dei tag.
    pump_database: dizionario { 'POMPA': { 'TAG': 'Descrizione' } }
    """
    return html.Div([
        html.Label("Seleziona Apparato"),
        dcc.Dropdown(
            id='pump-selector',
            options=[{'label': f"Pompa {k}", 'value': k} for k in pump_database.keys()],
            value=list(pump_database.keys())[0],
            className="mb-3"
        ),
        
        html.Label("Legenda e Punti (Copia solo codici)"),
        dbc.Textarea(
            id='tag-box',
            readOnly=True,
            style={
                'height': '120px', 
                'fontFamily': 'monospace', 
                'fontSize': '0.8rem', 
                'backgroundColor': '#f8f9fa',
                'marginBottom': '5px'
            }
        ),
        
        # Store invisibile per contenere solo i tag puliti per la copia
        dcc.Store(id='hidden-copy-storage'),
        
        dbc.Button("Copia Nomi Punti", id="copy-btn", color="secondary", size="sm", className="mb-4 w-100"),
        
        # Div di servizio per il callback clientside
        html.Div(id='dummy-copy-output', style={'display': 'none'})
    ])