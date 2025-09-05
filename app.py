import os
import json
import time
import csv
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import paho.mqtt.client as mqtt
from werkzeug.security import generate_password_hash, check_password_hash

# --- Application Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key' # Change this in production
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'signin'

# --- Data File Paths ---
USERS_FILE = 'users.json'
DATA_FILE = 'data.json'
ANALYTICS_FILE = 'analytics_data.csv'

# --- MQTT Setup ---
MQTT_BROKER = "mqtt.eclipse.org"
MQTT_PORT = 1883
MQTT_TOPIC_COMMAND = "lumino_us/commands"
MQTT_TOPIC_STATUS = "lumino_us/status"

mqtt_client = None

def connect_mqtt():
    """Connects to the MQTT broker."""
    global mqtt_client
    try:
        mqtt_client = mqtt.Client()
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print("Connected to MQTT Broker successfully!")
            else:
                print(f"Failed to connect to MQTT Broker, return code {rc}")
        mqtt_client.on_connect = on_connect
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"Error connecting to MQTT: {e}")

def run_mqtt_thread():
    # Use a separate thread for the MQTT loop to prevent blocking
    mqtt_thread = threading.Thread(target=connect_mqtt)
    mqtt_thread.daemon = True
    mqtt_thread.start()


# --- User Management ---
class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password_hash = password

@login_manager.user_loader
def load_user(user_id):
    users = load_users()
    for user in users:
        if user['id'] == user_id:
            return User(user['id'], user['username'], user['password_hash'])
    return None

def load_users():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f:
            json.dump([], f)
    with open(USERS_FILE, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

# --- Data Persistence Functions ---
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump({}, f)
    with open(DATA_FILE, 'r') as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_user_data():
    data = load_data()
    return data.get(current_user.id, {
        "user_settings": {
            "name": current_user.username,
            "email": "", "mobile": "", "channel": "email", "theme": "dark"
        },
        "rooms": []
    })

def save_user_data(user_data):
    data = load_data()
    data[current_user.id] = user_data
    save_data(data)

# --- Analytics Data ---
def generate_analytics_data():
    if os.path.exists(ANALYTICS_FILE):
        return
    start_date = datetime.now() - timedelta(days=365)
    with open(ANALYTICS_FILE, 'w', newline='') as csvfile:
        fieldnames = ['date', 'hour', 'consumption']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for i in range(365 * 24):
            current_datetime = start_date + timedelta(hours=i)
            consumption = 50 + (i % 24) * 2 + (i % 7) * 5 + os.urandom(1)[0] % 10
            writer.writerow({
                'date': current_datetime.strftime('%Y-%m-%d'),
                'hour': current_datetime.hour,
                'consumption': round(consumption, 2)
            })

def load_analytics_data():
    data = []
    with open(ANALYTICS_FILE, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if 'hour' in row and 'consumption' in row and row['hour'] is not None and row['consumption'] is not None:
                try:
                    data.append({
                        'date': row['date'],
                        'hour': int(row['hour']),
                        'consumption': float(row['consumption'])
                    })
                except (ValueError, TypeError):
                    continue
    return data

# --- Frontend Routes ---
@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()
        for user_data in users:
            if user_data['username'] == username and check_password_hash(user_data['password_hash'], password):
                user = User(user_data['id'], user_data['username'], user_data['password_hash'])
                login_user(user)
                return redirect(url_for('home'))
        return render_template('signin.html', error='Invalid username or password.')
    return render_template('signin.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()
        if any(u['username'] == username for u in users):
            return render_template('signup.html', error='Username already exists.')
        
        new_user_id = str(len(users) + 1)
        new_user = {
            'id': new_user_id,
            'username': username,
            'password_hash': generate_password_hash(password)
        }
        users.append(new_user)
        save_users(users)

        # Create a new entry for the user in data.json
        data = load_data()
        data[new_user_id] = {
            "user_settings": {
                "name": username,
                "email": "", "mobile": "", "channel": "email", "theme": "dark"
            },
            "rooms": [{
                "id": "1",
                "name": "Hall",
                "appliances": [
                    {"id": "1", "name": "Main Light", "state": False, "locked": False, "timer": None, "relay_number": 1},
                    {"id": "2", "name": "Fan", "state": False, "locked": False, "timer": None, "relay_number": 2},
                    {"id": "3", "name": "Night Lamp", "state": False, "locked": False, "timer": None, "relay_number": 3},
                    {"id": "4", "name": "A/C", "state": False, "locked": False, "timer": None, "relay_number": 4}
                ]
            }]
        }
        save_data(data)

        # Log the new user in and redirect to home
        user = User(new_user['id'], new_user['username'], new_user['password_hash'])
        login_user(user)
        return redirect(url_for('home'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('signin'))

@app.route('/')
@login_required
def home():
    user_data = get_user_data()
    theme = user_data['user_settings']['theme']
    return render_template('home.html', theme=theme)

@app.route('/control.html')
@login_required
def control():
    user_data = get_user_data()
    theme = user_data['user_settings']['theme']
    return render_template('control.html', theme=theme)

@app.route('/analytics.html')
@login_required
def analytics():
    user_data = get_user_data()
    theme = user_data['user_settings']['theme']
    return render_template('analytics.html', theme=theme)

@app.route('/settings.html')
@login_required
def settings():
    user_data = get_user_data()
    theme = user_data['user_settings']['theme']
    return render_template('settings.html', theme=theme)

@app.route('/contact.html')
@login_required
def contact():
    user_data = get_user_data()
    theme = user_data['user_settings']['theme']
    return render_template('contact.html', theme=theme)

# --- Backend API Endpoints ---
@app.route('/api/esp/check-in', methods=['GET'])
def check_in():
    data = load_data()
    user_id = request.args.get('user_id')
    user_data = data.get(user_id, {})
    last_command = user_data.get('last_command', {})
    
    if last_command and last_command.get('timestamp', 0) > user_data.get('last_command_sent_time', 0):
        user_data['last_command_sent_time'] = last_command['timestamp']
        data[user_id] = user_data
        save_data(data)
        return jsonify(last_command), 200
    
    return jsonify({}), 200

@app.route('/api/set-appliance-state', methods=['POST'])
@login_required
def set_appliance_state():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        appliance_id = data_from_request['appliance_id']
        state = data_from_request['state']
        
        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404
        
        appliance = next((a for a in room['appliances'] if a['id'] == appliance_id), None)
        if not appliance:
            return jsonify({"status": "error", "message": "Appliance not found."}), 404
        
        if appliance.get('locked', False):
            return jsonify({"status": "error", "message": "Appliance is locked."}), 403

        appliance['state'] = state
        
        user_data['last_command'] = {
            "room_id": room_id,
            "appliance_id": appliance_id,
            "state": state,
            "relay_number": appliance['relay_number'],
            "timestamp": int(time.time())
        }
        
        save_user_data(user_data)
        
        if mqtt_client:
            mqtt_client.publish(MQTT_TOPIC_COMMAND, f"{current_user.id}:{room_id}:{appliance_id}:{appliance['relay_number']}:{int(state)}")
        
        return jsonify({"status": "success", "message": "Command sent."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/set-appliance-name', methods=['POST'])
@login_required
def set_appliance_name():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        appliance_id = data_from_request['appliance_id']
        name = data_from_request['name']
        
        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404
        
        appliance = next((a for a in room['appliances'] if a['id'] == appliance_id), None)
        if not appliance:
            return jsonify({"status": "error", "message": "Appliance not found."}), 404
        
        appliance['name'] = name
        save_user_data(user_data)
        
        return jsonify({"status": "success", "message": "Name updated."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/set-lock', methods=['POST'])
@login_required
def set_lock():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        appliance_id = data_from_request['appliance_id']
        locked = data_from_request['locked']

        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404
        
        appliance = next((a for a in room['appliances'] if a['id'] == appliance_id), None)
        if not appliance:
            return jsonify({"status": "error", "message": "Appliance not found."}), 404
        
        appliance['locked'] = locked
        save_user_data(user_data)

        if mqtt_client:
            mqtt_client.publish(MQTT_TOPIC_COMMAND, f"{current_user.id}:{room_id}:{appliance_id}:{appliance['relay_number']}:lock:{int(locked)}")

        return jsonify({"status": "success", "message": "Lock state updated."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get-rooms-and-appliances', methods=['GET'])
@login_required
def get_rooms_and_appliances():
    user_data = get_user_data()
    return jsonify(user_data['rooms']), 200

@app.route('/api/add-room', methods=['POST'])
@login_required
def add_room():
    try:
        room_name = request.json['name']
        user_data = get_user_data()
        new_room_id = str(len(user_data['rooms']) + 1)
        user_data['rooms'].append({"id": new_room_id, "name": room_name, "appliances": []})
        save_user_data(user_data)
        return jsonify({"status": "success", "room_id": new_room_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/add-appliance', methods=['POST'])
@login_required
def add_appliance():
    try:
        room_id = request.json['room_id']
        appliance_name = request.json['name']
        relay_number = request.json['relay_number']
        
        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404
            
        new_appliance_id = str(len(room['appliances']) + 1)
        room['appliances'].append({
            "id": new_appliance_id,
            "name": appliance_name,
            "state": False,
            "locked": False,
            "timer": None,
            "relay_number": int(relay_number)
        })
        save_user_data(user_data)
        
        return jsonify({"status": "success", "appliance_id": new_appliance_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/update-appliance-settings', methods=['POST'])
@login_required
def update_appliance_settings():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        appliance_id = data_from_request['appliance_id']
        new_name = data_from_request['name']
        new_relay_number = data_from_request['relay_number']
        new_room_id = data_from_request['new_room_id'] # New field
        
        user_data = get_user_data()
        
        # Find the appliance
        original_room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not original_room:
            return jsonify({"status": "error", "message": "Original room not found."}), 404
        appliance = next((a for a in original_room['appliances'] if a['id'] == appliance_id), None)
        if not appliance:
            return jsonify({"status": "error", "message": "Appliance not found."}), 404
        
        # If room is changing, move the appliance
        if new_room_id and new_room_id != room_id:
            target_room = next((r for r in user_data['rooms'] if r['id'] == new_room_id), None)
            if not target_room:
                return jsonify({"status": "error", "message": "Target room not found."}), 404
            
            # Remove from original room
            original_room['appliances'].remove(appliance)
            # Add to new room
            target_room['appliances'].append(appliance)
        
        # Update appliance details
        appliance['name'] = new_name
        appliance['relay_number'] = new_relay_number
        save_user_data(user_data)
        
        return jsonify({"status": "success", "message": "Appliance settings updated."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/set-timer', methods=['POST'])
@login_required
def set_timer():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        appliance_id = data_from_request['appliance_id']
        duration_minutes = data_from_request['duration_minutes']
        
        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404
        
        appliance = next((a for a in room['appliances'] if a['id'] == appliance_id), None)
        if not appliance:
            return jsonify({"status": "error", "message": "Appliance not found."}), 404
        
        if appliance.get('locked', False):
            return jsonify({"status": "error", "message": "Appliance is locked."}), 403
        
        if duration_minutes > 0:
            appliance['state'] = True
            appliance['timer'] = time.time() + duration_minutes * 60
            user_data['last_command'] = {
                "room_id": room_id,
                "appliance_id": appliance_id,
                "state": True,
                "relay_number": appliance['relay_number'],
                "timestamp": int(time.time())
            }
            if mqtt_client:
                mqtt_client.publish(MQTT_TOPIC_COMMAND, f"{current_user.id}:{room_id}:{appliance_id}:{appliance['relay_number']}:on")
        else:
            appliance['timer'] = None

        save_user_data(user_data)
        
        return jsonify({"status": "success", "message": "Timer set."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route('/api/save-room-order', methods=['POST'])
@login_required
def save_room_order():
    try:
        new_order_ids = request.json['order']
        user_data = get_user_data()
        room_map = {room['id']: room for room in user_data['rooms']}
        user_data['rooms'] = [room_map[id] for id in new_order_ids]
        save_user_data(user_data)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route('/api/save-appliance-order', methods=['POST'])
@login_required
def save_appliance_order():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        new_order_ids = data_from_request['order']
        
        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404
            
        appliance_map = {appliance['id']: appliance for appliance in room['appliances']}
        room['appliances'] = [appliance_map[id] for id in new_order_ids]
        save_user_data(user_data)
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get-rooms-and-appliances', methods=['GET'])
@login_required
def get_rooms_and_appliances():
    user_data = get_user_data()
    return jsonify(user_data['rooms']), 200

@app.route('/api/add-room', methods=['POST'])
@login_required
def add_room():
    try:
        room_name = request.json['name']
        user_data = get_user_data()
        new_room_id = str(len(user_data['rooms']) + 1)
        user_data['rooms'].append({"id": new_room_id, "name": room_name, "appliances": []})
        save_user_data(user_data)
        return jsonify({"status": "success", "room_id": new_room_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/add-appliance', methods=['POST'])
@login_required
def add_appliance():
    try:
        room_id = request.json['room_id']
        appliance_name = request.json['name']
        relay_number = request.json['relay_number']
        
        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404
            
        new_appliance_id = str(len(room['appliances']) + 1)
        room['appliances'].append({
            "id": new_appliance_id,
            "name": appliance_name,
            "state": False,
            "locked": False,
            "timer": None,
            "relay_number": int(relay_number)
        })
        save_user_data(user_data)
        
        return jsonify({"status": "success", "appliance_id": new_appliance_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get-analytics', methods=['GET'])
@login_required
def get_analytics():
    data = load_analytics_data()
    
    # Calculate different time ranges for the chart data
    now = datetime.now()
    last_day = [entry for entry in data if datetime.strptime(entry['date'], '%Y-%m-%d') >= now - timedelta(days=1)]
    last_month = [entry for entry in data if datetime.strptime(entry['date'], '%Y-%m-%d') >= now - timedelta(days=30)]
    last_year = [entry for entry in data]

    # Process data for different time views
    hourly_data = {f"{entry['date']} {entry['hour']:02d}:00": entry['consumption'] for entry in last_day}
    
    daily_data = {}
    for entry in last_month:
        daily_data.setdefault(entry['date'], 0)
        daily_data[entry['date']] += entry['consumption']
    
    monthly_data = {}
    for entry in last_year:
        month = entry['date'][:7]
        monthly_data.setdefault(month, 0)
        monthly_data[month] += entry['consumption']

    all_consumptions = [entry['consumption'] for entry in data]
    total_consumption = sum(all_consumptions)
    average_consumption = total_consumption / len(all_consumptions) if all_consumptions else 0
    highest_usage = max(all_consumptions) if all_consumptions else 0
    savings = 0.25 * total_consumption
    
    return jsonify({
        "hourly": hourly_data, "daily": daily_data, "monthly": monthly_data,
        "stats": {"highest_usage": highest_usage, "average_usage": average_consumption, "savings": savings}
    }), 200

@app.route('/api/get-user-settings', methods=['GET'])
@login_required
def get_user_settings():
    user_data = get_user_data()
    return jsonify(user_data['user_settings']), 200

@app.route('/api/set-user-settings', methods=['POST'])
@login_required
def set_user_settings():
    try:
        settings = request.json
        user_data = get_user_data()
        user_data['user_settings'].update(settings)
        save_user_data(user_data)
        return jsonify({"status": "success", "message": "Settings updated."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    generate_analytics_data()
    run_mqtt_thread()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
