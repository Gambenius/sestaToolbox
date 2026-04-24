import dash
from dash import html, callback, Input, Output

dash.register_page(__name__, name="Valve Modeling")

layout = html.Div([
    html.H3("Valve Performance Modeling"),
    html.Button("Test Valve Model", id="run-valve"),
    html.Div(id="valve-status")
])

@callback(
    Output("valve-status", "children"),
    Input("run-valve", "n_clicks"),
    prevent_initial_call=True
)
def run_logic(n):
    print("Executing: Valve Modeling")
    return "Valve Model Logic Executed in Terminal."