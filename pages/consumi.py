import dash
from dash import dcc, html, Input, Output, State, callback, ALL, MATCH
import dash_bootstrap_components as dbc
import pandas as pd
import os

NETWORK_BASE_PATH = r"\\10.33.126.101\archivi\BinRev 3.0\TOTALE\PROVE"
dash.register_page(__name__, path="/consumi")

# --- Data Loading ---
file_path = r"\\10.33.126.101\archivi\BinRev 3.0\consumption.json"
dfCons = pd.read_json(file_path)
columns = ["Tag", "Description", "Algorithm", "Group", "ConversionFactor", "MeasurementUnit"]
dfCons = dfCons[columns].sort_values(by="Group").reset_index(drop=True)

# Initialize the 'Selected' column
dfCons['Selected'] = False

layout = html.Div([
    html.H4("Selezione Tag Consumi", className="mb-4"),
    dbc.Button(
        "📂 SELEZIONA BINARIO",
        id="cons-btn-open-modal",
        color="primary",
        className="mb-3",
    ),

    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Seleziona File Binario")),
        dbc.ModalBody([
            html.Label("Seleziona Data:", className="fw-bold mb-2"),
            html.Br(),
            dcc.DatePickerSingle(
                id="cons-date-picker",
                date=pd.Timestamp.now().date(),
                display_format='YYYY-MM-DD',
                className="mb-3"
            ),
            html.Br(),
            html.Label("File .bin disponibili:", className="fw-bold mb-2"),
            dcc.Dropdown(id="cons-file-dropdown", placeholder="Seleziona un file..."),
        ]),
        dbc.ModalFooter(
            dbc.Button("Conferma", id="cons-btn-confirm", color="success", disabled=True)
        ),
    ], id="cons-file-modal", is_open=False),

    # This store will hold the final path of the selected file
    dcc.Store(id='selected-bin-path', data=None),
    
    # MASTER SELECT ALL
    dbc.Card([
        dbc.CardBody(
            dbc.Checkbox(
                id="master-select-all",
                label="SELEZIONA TUTTI I GRUPPI",
                value=False,
                className="fw-bold text-primary"
            )
        )
    ], className="mb-4 border-primary"),
    # This container will hold our generated groups
    html.Div(id="groups-container", children=[]),
    
    # Store to keep track of ALL selected tags across all groups
    dcc.Store(id='selected-tags-store', data=[])
], className="p-4")

# ------------- render groups
@callback(
    Output("groups-container", "children"),
    Input("groups-container", "id") # Triggers once on load
)
def render_groups(_):
    cards = []
    # Loop through each unique group in your dataframe
    for group_name in dfCons['Group'].unique():
        group_df = dfCons[dfCons['Group'] == group_name]
        
        # Header with Group Title and Select All toggle
        header = dbc.Row([
            dbc.Col(html.B(group_name)),
            dbc.Col(
                dbc.Checkbox(
                    id={'type': 'select-all', 'index': group_name},
                    label="Select All",
                    value=False,
                    className="small"
                ), width="auto"
            )
        ], align="center")

        # Checklist for the tags in this group
        checklist = dbc.Checklist(
            options=[
                {"label": f"{row['Description']} - {row['Tag']}", "value": row['Tag']}
                for _, row in group_df.iterrows()
            ],
            value=[],
            id={'type': 'tag-checklist', 'index': group_name},
        )

        cards.append(dbc.Card([
            dbc.CardHeader(header),
            dbc.CardBody(checklist)
        ], className="mb-3"))
        
    return cards


# ------------- get path file from datepicker
@callback(
    Output("cons-file-modal", "is_open", allow_duplicate=True), # Match the layout ID
    Input("cons-btn-open-modal", "n_clicks"),
    Input("cons-btn-confirm", "n_clicks"),
    State("cons-file-modal", "is_open"),
    prevent_initial_call=True
)
def toggle_modal(n_open, n_confirm, is_open):
    if n_open or n_confirm:
        return not is_open
    return is_open

@callback(
    Output("cons-file-dropdown", "options", allow_duplicate=True),
    Output("cons-file-dropdown", "value", allow_duplicate=True),
    Input("cons-date-picker", "date"),
    prevent_initial_call=True
)
def update_file_list(selected_date):
    if not selected_date:
        return [], None
    
    # Format date to match folder name YYYYMMDD
    folder_name = selected_date.replace("-", "") 
    folder_path = os.path.join(NETWORK_BASE_PATH, folder_name)
    
    if not os.path.exists(folder_path):
        return [], None

    # Get .bin files
    files = [f for f in os.listdir(folder_path) if f.lower().endswith('.bin')]
    
    # Create options for dropdown
    options = [{"label": f, "value": os.path.join(folder_path, f)} for f in files]
    
    return options, None
# ---------- select all button
@callback(
    Output({'type': 'tag-checklist', 'index': MATCH}, 'value'),
    Input({'type': 'select-all', 'index': MATCH}, 'value'),
    State({'type': 'tag-checklist', 'index': MATCH}, 'options'),
    prevent_initial_call=True
)
def toggle_group_selection(is_checked, options):
    if is_checked:
        # Return all tag values in this group
        return [opt['value'] for opt in options]
    # Return empty list to deselect all
    return []

# ------------ writing in the "selected" column
@callback(
    Output("selected-tags-store", "data"), # Use a store to keep track
    Input({'type': 'tag-checklist', 'index': ALL}, 'value'),
    prevent_initial_call=True
)
def update_dataframe_selection(all_checklist_values):
    # 1. Flatten the list of lists into a single list of selected tags
    # all_checklist_values looks like: [['Tag1', 'Tag2'], [], ['Tag5']]
    selected_tags = [tag for sublist in all_checklist_values for tag in sublist]

    # 2. Update the 'Selected' column in your global dataframe
    global dfCons
    dfCons['Selected'] = dfCons['Tag'].isin(selected_tags)

    # 3. Optional: return the list to a Store so other parts of the app can use it
    return selected_tags

# -------- master select all
@callback(
    Output({'type': 'select-all', 'index': ALL}, 'value'),
    Input('master-select-all', 'value'),
    prevent_initial_call=True
)
def cb_master_toggle(master_checked):
    # This finds every 'select-all' checkbox and gives it the master value
    # We use dash.callback_context to see how many groups exist
    ctx = dash.callback_context
    num_groups = len(ctx.outputs_list)
    return [master_checked] * num_groups