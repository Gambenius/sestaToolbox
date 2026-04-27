import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, callback

app = dash.Dash(
    __name__, 
    use_pages=True, 
    external_stylesheets=[dbc.themes.ZEPHYR, dbc.icons.BOOTSTRAP]
)

# --- STILI AGGIORNATI ---
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "18rem",
    "padding": "5rem 1rem 2rem", # Aumentato il padding superiore (5rem) per non coprire il logo
    "backgroundColor": "#f8f9fa",
    "transition": "all 0.5s",
    "zIndex": 1000,
}

SIDEBAR_HIDDEN = {**SIDEBAR_STYLE, "left": "-18rem"}

CONTENT_STYLE = {
    "marginLeft": "20rem",
    "marginRight": "2rem",
    "padding": "2rem 1rem",
    "transition": "all 0.5s",
}

CONTENT_EXPANDED = {**CONTENT_STYLE, "marginLeft": "4rem"} # Lasciamo un po' di spazio per il tasto

# --- COMPONENTI ---

btn_toggle = dbc.Button(
    html.I(className="bi bi-list", style={"fontSize": "1.8rem"}),
    id="btn-toggle",
    color="dark", # Cambiato a dark per vederlo meglio sul bianco
    outline=True,
    style={
        "position": "fixed",
        "top": "1rem",
        "left": "1rem",
        "zIndex": "1002", # Più alto della sidebar
        "padding": "0rem 0.5rem",
        "borderRadius": "5px"
    }
)

sidebar = html.Div(
    [
        # Logo e Titolo
        html.H2("Sesta Lab", className="display-6", style={"fontSize": "1.8rem"}),
        html.Hr(),
        html.P("Engineering Toolbox", className="lead", style={"fontSize": "1rem"}),
        dbc.Nav(
            [
                dbc.NavLink(
                    f"{page['name']}", 
                    href=page["relative_path"], 
                    active="exact"
                ) for page in dash.page_registry.values()
            ],
            vertical=True,
            pills=True,
        ),
    ],
    id="sidebar",
    style=SIDEBAR_STYLE,
)

content = html.Div(dash.page_container, id="page-content", style=CONTENT_STYLE)

app.layout = html.Div([
    dcc.Location(id="url"), 
    dcc.Store(id="sidebar-state", data="show"),
    btn_toggle, 
    sidebar, 
    content
])

# --- CALLBACK ---
@callback(
    [Output("sidebar", "style"), 
     Output("page-content", "style"),
     Output("sidebar-state", "data")],
    [Input("btn-toggle", "n_clicks")],
    [State("sidebar-state", "data")]
)
def toggle_sidebar(n, state):
    if n:
        if state == "show":
            return SIDEBAR_HIDDEN, CONTENT_EXPANDED, "hide"
        else:
            return SIDEBAR_STYLE, CONTENT_STYLE, "show"
    return SIDEBAR_STYLE, CONTENT_STYLE, "show"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8050, debug=True)