import dash
from dash import dcc, html, Input, Output, callback_context
import requests

# Konfiguration
BOT_IP = "192.168.1.108" # IP deiner ESP32-CAM

app = dash.Dash(__name__)

def send_cmd(cmd, timeout=0.25, retries=3):
    for _ in range(retries):
        try:
            r = requests.get(f"http://{BOT_IP}/cmd?p={cmd}", timeout=timeout)
            if r.ok:
                return True
        except requests.RequestException:
            pass
    return False

# --- STYLES ---
button_style = {
    'width': '80px', 'height': '80px', 'fontSize': '24px', 
    'margin': '5px', 'backgroundColor': '#333', 'color': 'white', 'border': 'none', 'borderRadius': '10px'
}
stop_style = {**button_style, 'backgroundColor': '#ff1744'}

# --- LAYOUT ---
app.layout = html.Div(style={'backgroundColor': '#121212', 'color': 'white', 'fontFamily': 'sans-serif', 'textAlign': 'center', 'padding': '20px'}, children=[
    html.Div(BOT_IP, id='bot-ip', style={'display': 'none'}),
    html.Div('150', id='speed-value', style={'display': 'none'}),
    html.H1("ALPHABOT MISSION CONTROL", style={'borderBottom': '2px solid #00e676', 'paddingBottom': '10px'}),
    
    # Live-Stream der Kamera
    html.Img(id='camera-feed', src=f"http://{BOT_IP}:81/stream", style={'width': '100%', 'maxWidth': '500px', 'borderRadius': '10px', 'border': '2px solid #00e676'}),
    html.Div(
        id='camera-status',
        children='Kamera: stream wird initialisiert...',
        style={'fontSize': '13px', 'color': '#90caf9', 'marginTop': '8px', 'fontFamily': 'monospace'}
    ),
    
    html.Div(id='telemetry-display', children="Warte auf Sensordaten...", 
             style={'fontSize': '18px', 'color': '#00e676', 'margin': '20px', 'fontFamily': 'monospace'}),
    html.Div(
        id='hardware-status',
        children='Hardware: bereit',
        style={'fontSize': '14px', 'color': '#b0bec5', 'marginTop': '6px'}
    ),

    # --- DAS CONTROLLFELD (STEUERKREUZ) ---
    html.Div(style={'display': 'inline-block', 'marginTop': '20px'}, children=[
        html.Div([html.Button("▲", id="btn-f", style=button_style)]),
        html.Div([
            html.Button("◀", id="btn-l", style=button_style),
            html.Button("■", id="btn-s", style=stop_style),
            html.Button("▶", id="btn-r", style=button_style)
        ]),
        html.Div([html.Button("▼", id="btn-b", style=button_style)])
    ]),
    html.Div(
        "Keyboard: WASD / Pfeiltasten fahren · Shift = langsam · Leertaste oder X = STOP",
        style={'marginTop': '10px', 'color': '#90caf9', 'fontSize': '13px'}
    ),

    # --- SLIDER & OPTIONEN ---
    html.Div(style={'maxWidth': '400px', 'margin': '30px auto'}, children=[
        html.Label("Motor-Geschwindigkeit (PWM)", style={'color': '#f5f5f5', 'fontWeight': '600'}),
        dcc.Slider(
            58,
            255,
            1,
            value=150,
            id='speed-slider',
            marks={
                58: {'label': '58', 'style': {'color': '#cfd8dc'}},
                255: {'label': '255', 'style': {'color': '#cfd8dc'}}
            }
        ),
        html.Div(
            id='pwm-display',
            children='Aktuell eingestellte PWM: 150',
            style={'marginTop': '8px', 'fontSize': '14px', 'color': '#90caf9', 'fontWeight': '600'}
        ),
        
        html.Br(),
        html.Label("Kamera-Winkel (Servo)", style={'color': '#f5f5f5', 'fontWeight': '600'}),
        dcc.Slider(
            0,
            180,
            1,
            value=90,
            id='servo-slider',
            marks={
                0: {'label': '0', 'style': {'color': '#cfd8dc'}},
                180: {'label': '180', 'style': {'color': '#cfd8dc'}}
            }
        ),
        
        html.Br(),
        dcc.Checklist(
            options=[{'label': ' Kamera-Licht AN', 'value': 'ON'}],
            id='light-check',
            style={'fontSize': '20px', 'color': '#f5f5f5'},
            labelStyle={'color': '#f5f5f5'}
        )
    ]),

        # Hidden interval timer for telemetry and hardware resync
    dcc.Interval(id='interval-component', interval=1000, n_intervals=0)
])

# --- CALLBACKS (LOGIK) ---

@app.callback(
    Output('speed-value', 'children'),
    Output('pwm-display', 'children'),
    Input('speed-slider', 'value')
)
def sync_speed_value(speed):
    return str(speed), f"Aktuell eingestellte PWM: {speed}"

# 1. Servo & Licht Updates
@app.callback(
    Output('hardware-status', 'children'),
    Input('servo-slider', 'value'),
    Input('light-check', 'value'),
    Input('interval-component', 'n_intervals')
)
def update_hardware(servo_angle, light_val, _tick):
    light_cmd = "L1" if light_val and 'ON' in light_val else "L0"

    servo_ok = send_cmd(f"V{servo_angle}")
    light_ok = send_cmd(light_cmd)

    servo_text = f"{servo_angle}°"
    light_text = 'AN' if light_cmd == 'L1' else 'AUS'
    if servo_ok and light_ok:
        return f"Hardware: online | Servo {servo_text} | Licht {light_text}"
    return f"Hardware: Verbindung instabil | Ziel Servo {servo_text} | Ziel-Licht {light_text} (Retry aktiv)"

# 2. Telemetrie-Daten abrufen (Distanz & Rad-RPS)
@app.callback(
    Output('telemetry-display', 'children'),
    Input('interval-component', 'n_intervals')
)
def update_telemetry(n):
    try:
        r = requests.get(f"http://{BOT_IP}/status", timeout=0.25)
        # Format vom Arduino: D:15.5|L:2.4|R:2.5
        parts = r.text.replace("|", "  |  ")
        return f"SENSORDATEN: {parts}"
    except:
        return "Verbindung zum AlphaBot wird aufgebaut..."

if __name__ == '__main__':
    app.run(debug=True, port=8050)