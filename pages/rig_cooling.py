import dash
from dash import html, callback, Input, Output

dash.register_page(__name__, name="Rig Cooling")

layout = html.Div([
    html.H3("Rig Cooling Analysis"),
    html.Button("Analyze Cooling", id="run-cooling"),
    html.Div(id="cooling-status")
])

@callback(
    Output("cooling-status", "children"),
    Input("run-cooling", "n_clicks"),
    prevent_initial_call=True
)
def run_logic(n):
    print("Executing: Rig Cooling Analysis")
    return "Cooling Analysis Logic Executed in Terminal."