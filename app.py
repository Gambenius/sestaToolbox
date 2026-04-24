import dash
import dash_bootstrap_components as dbc
from dash import html, dcc

# We use the 'FLATLY' or 'LUX' theme for a clean, modern look
app = dash.Dash(
    __name__, 
    use_pages=True, 
    external_stylesheets=[dbc.themes.FLATLY] 
)

# Define the sidebar style
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "18rem",
    "padding": "2rem 1rem",
    "backgroundColor": "#f8f9fa",
}

# Define the content area style
CONTENT_STYLE = {
    "marginLeft": "20rem",
    "marginRight": "2rem",
    "padding": "2rem 1rem",
}

sidebar = html.Div(
    [
        html.H2("Sesta Lab", className="display-6"),
        html.Hr(),
        html.P("Engineering Toolbox", className="lead"),
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
    style=SIDEBAR_STYLE,
)

content = html.Div(dash.page_container, style=CONTENT_STYLE)

app.layout = html.Div([dcc.Location(id="url"), sidebar, content])

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8050, debug=True)