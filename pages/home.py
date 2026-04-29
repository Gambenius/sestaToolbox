import dash
from dash import html

dash.register_page(__name__, path='/')

layout = html.Div([
    html.H3("Benvenuti in sto schifo vibecodato. Se non funziona ditemelo"),
    html.P("Scegli un tool da sinistra, non è detto che gnihosa funzioni ."),
    html.P("Attualmente collehato al mio portatile, siate clementi che non è sto gran PC.")
])