import dash
from dash import dcc, html, Input, Output, State
import requests
from flask import request

# Configuration
# BOT_IP = "192.168.1.108"  # Niclas Meo
BOT_IP = "172.20.10.6"  # Niclas hotspot
# BOT_IP = "10.104.31.108" #Magga hotspot



app = dash.Dash(__name__)


@app.server.route('/debug/client', methods=['POST'])
def debug_client_event():
    payload = request.get_json(silent=True) or {}
    event = str(payload.get('event', 'unknown'))
    command = str(payload.get('command', '-'))
    speed = str(payload.get('speed', '-'))
    source = str(payload.get('source', '-'))
    info = str(payload.get('info', '-'))
    ts = str(payload.get('ts', '-'))
    print(f"[web-debug] ts={ts} event={event} cmd={command} speed={speed} source={source} info={info}")
    return ('', 204)


@app.server.route('/api/motor', methods=['POST'])
def motor_proxy():
    payload = request.get_json(silent=True) or {}
    command = str(payload.get('command', '')).upper()[:1]
    speed_raw = payload.get('speed', 0)

    try:
        speed = int(speed_raw)
    except (TypeError, ValueError):
        speed = 0

    speed = max(0, min(255, speed))
    if command not in {'F', 'B', 'L', 'R', 'S'}:
        return ({'ok': False, 'error': 'invalid command'}, 400)

    cmd = f"M{command}{speed}"
    url = f"http://{BOT_IP}/cmd"

    for attempt in range(3):
        try:
            response = requests.get(url, params={'p': cmd}, timeout=0.35)
            if response.ok:
                return ({'ok': True, 'cmd': cmd, 'attempt': attempt}, 200)
        except requests.RequestException:
            pass

    return ({'ok': False, 'cmd': cmd, 'error': 'bot unreachable'}, 502)

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
    html.Div('120', id='speed-value', style={'display': 'none'}),
    dcc.Store(id='telemetry-state', data={'connected': False, 'last_ok': ''}),
    html.H1("ALPHABOT MISSION CONTROL", style={'borderBottom': '2px solid #00e676', 'paddingBottom': '10px'}),
    html.Div(style={'maxWidth': '420px', 'margin': '14px auto 8px auto'}, children=[
        html.Label("Drive speed (PWM)", style={'color': '#f5f5f5', 'fontWeight': '600', 'display': 'block', 'marginBottom': '8px'}),
        dcc.Input(
            id='speed-input',
            type='number',
            step=1,
            value=50,
            debounce=False,
            style={
                'width': '140px',
                'fontSize': '20px',
                'textAlign': 'center',
                'padding': '8px',
                'borderRadius': '8px',
                'border': '1px solid #455a64',
                'backgroundColor': '#1f1f1f',
                'color': '#f5f5f5'
            }
        ),
        html.Div(
            id='pwm-display',
            children='Current PWM setting: 120',
            style={'marginTop': '8px', 'fontSize': '14px', 'color': '#90caf9', 'fontWeight': '600'}
        ),
    ]),
    
    # Live camera stream
    html.Img(id='camera-feed', src=f"http://{BOT_IP}:81/stream", style={'width': '100%', 'maxWidth': '500px', 'borderRadius': '10px', 'border': '2px solid #00e676'}),
    html.Div(
        id='camera-status',
        children='Camera: stream is initializing...',
        style={'fontSize': '13px', 'color': '#90caf9', 'marginTop': '8px', 'fontFamily': 'monospace'}
    ),
    
    html.Div(id='telemetry-display', children="Waiting for sensor data...", 
             style={'fontSize': '18px', 'color': '#00e676', 'margin': '20px', 'fontFamily': 'monospace'}),
    html.Div(
        id='hardware-status',
        children='Hardware: ready',
        style={'fontSize': '14px', 'color': '#b0bec5', 'marginTop': '6px'}
    ),

    # --- CONTROL PAD ---
    html.Div(style={'display': 'inline-block', 'marginTop': '20px'}, children=[
        html.Div([html.Button("▲", id="btn-f", style=button_style)]),
        html.Div([
            html.Button("◀", id="btn-l", style=button_style),
            html.Button("▶", id="btn-r", style=button_style)
        ]),
        html.Div([html.Button("▼", id="btn-b", style=button_style)])
    ]),
    html.Div(
        "Keyboard: WASD / Arrows drive · Shift = slower · Space or X = STOP",
        style={'marginTop': '10px', 'color': '#90caf9', 'fontSize': '13px'}
    ),

    # --- SLIDERS & OPTIONS ---
    html.Div(style={'maxWidth': '400px', 'margin': '30px auto'}, children=[
        html.Br(),
        html.Label("Camera angle (servo)", style={'color': '#f5f5f5', 'fontWeight': '600'}),
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
            options=[{'label': ' Camera light ON', 'value': 'ON'}],
            id='light-check',
            style={'fontSize': '20px', 'color': '#f5f5f5'},
            labelStyle={'color': '#f5f5f5'}
        )
    ]),

        # Hidden interval timer for telemetry polling
    dcc.Interval(id='interval-component', interval=1000, n_intervals=0)
])

    # --- CALLBACKS (LOGIC) ---

@app.callback(
    Output('speed-value', 'children'),
    Output('pwm-display', 'children'),
    Input('speed-input', 'value')
)
def sync_speed_value(speed):
    try:
        value = int(speed)
    except (TypeError, ValueError):
        value = 120

    value = max(0, min(255, value))
    return str(value), f"Current PWM setting: {value}"

# 1. Servo & light updates
@app.callback(
    Output('hardware-status', 'children'),
    Input('servo-slider', 'value'),
    Input('light-check', 'value')
)
def update_hardware(servo_angle, light_val):
    light_cmd = "L1" if light_val and 'ON' in light_val else "L0"

    servo_ok = send_cmd(f"V{servo_angle}")
    light_ok = send_cmd(light_cmd)

    servo_text = f"{servo_angle}°"
    light_text = 'ON' if light_cmd == 'L1' else 'OFF'
    if servo_ok and light_ok:
        return f"Hardware: online | Servo {servo_text} | Light {light_text}"
    return f"Hardware: unstable connection | Target servo {servo_text} | Target light {light_text} (retry active)"

# 2. Poll telemetry (distance & wheel RPS)
@app.callback(
    Output('telemetry-display', 'children'),
    Output('telemetry-state', 'data'),
    Input('interval-component', 'n_intervals'),
    State('telemetry-state', 'data')
)
def update_telemetry(n, telemetry_state):
    telemetry_state = telemetry_state or {'connected': False, 'last_ok': ''}
    try:
        r = requests.get(f"http://{BOT_IP}/status", timeout=0.55)
        r.raise_for_status()
        parts = r.text.replace("|", "  |  ")
        return (
            f"SENSOR DATA: {parts}",
            {'connected': True, 'last_ok': parts}
        )
    except requests.RequestException:
        if telemetry_state.get('connected') and telemetry_state.get('last_ok'):
            stale = telemetry_state['last_ok']
            return (
                f"SENSOR DATA: {stale}  |  link unstable",
                telemetry_state
            )
        return (
            "Connecting to AlphaBot...",
            telemetry_state
        )

if __name__ == '__main__':
    app.run(debug=True, port=8050)