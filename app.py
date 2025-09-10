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
from flask_mail import Mail, Message
import requests
import base64

# --- Application Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key'  # Change this in production
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'signin'

# --- Flask-Mail Configuration ---
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])
mail = Mail(app)

# --- Data File Paths ---
USERS_FILE = 'users.json'
DATA_FILE = 'data.json'
ANALYTICS_FILE = 'analytics_data.csv'

# --- Gemini API Setup ---
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key="
API_KEY = ""  # Your API Key will be automatically provided by the Canvas environment

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
            "email": "", "mobile": "", "channel": "email", "theme": "light", "ai_control_interval": 5
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
        for user in users:
            if user['username'] == username and check_password_hash(user['password_hash'], password):
                user_obj = User(user['id'], user['username'], user['password_hash'])
                login_user(user_obj)
                return redirect(url_for('home'))
        return render_template('signin.html', error='Invalid username or password.')
    return render_template('signin.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    users = load_users()
    if not users:
        # Create a new default user if the users file is empty
        new_user_id = "1"
        default_user = {
            'id': new_user_id,
            'username': 'hi',
            'password_hash': generate_password_hash('hello')
        }
        users.append(default_user)
        save_users(users)
        
        # Create a new entry for the user in data.json
        data = load_data()
        data[new_user_id] = {
            "user_settings": {
                "name": "hi",
                "email": "", "mobile": "", "channel": "email", "theme": "light", "ai_control_interval": 5
            },
            "rooms": [{
                "id": "1",
                "name": "Hall",
                "ai_control": False,
                "appliances": [
                    {"id": "1", "name": "Main Light", "state": False, "locked": False, "timer": None, "relay_number": 1},
                    {"id": "2", "name": "Fan", "state": False, "locked": False, "timer": None, "relay_number": 2},
                    {"id": "3", "name": "Night Lamp", "state": False, "locked": False, "timer": None, "relay_number": 3},
                    {"id": "4", "name": "A/C", "state": False, "locked": False, "timer": None, "relay_number": 4}
                ]
            }]
        }
        save_data(data)
        
        user_obj = User(default_user['id'], default_user['username'], default_user['password_hash'])
        login_user(user_obj)
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
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
                "email": "", "mobile": "", "channel": "email", "theme": "light", "ai_control_interval": 5
            },
            "rooms": [{
                "id": "1",
                "name": "Hall",
                "ai_control": False,
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
        user_obj = User(new_user['id'], new_user['username'], new_user['password_hash'])
        login_user(user_obj)
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
@app.route('/api/add-appliance', methods=['POST'])
@login_required
def add_appliance():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        appliance_name = data_from_request['name']
        relay_number = data_from_request['relay_number']
        
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

@app.route('/api/get-rooms-and-appliances', methods=['GET'])
@login_required
def get_rooms_and_appliances():
    try:
        user_data = get_user_data()
        return jsonify(user_data['rooms']), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/update-room-settings', methods=['POST'])
@login_required
def update_room_settings():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        new_name = data_from_request.get('name')
        ai_control = data_from_request.get('ai_control')
        
        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404
        
        if new_name is not None:
            room['name'] = new_name
        if ai_control is not None:
            room['ai_control'] = ai_control
            # Additional logic to handle AI control toggle could go here

        save_user_data(user_data)
        
        return jsonify({"status": "success", "message": "Room settings updated."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route('/api/delete-room', methods=['POST'])
@login_required
def delete_room():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        user_data = get_user_data()
        user_data['rooms'] = [r for r in user_data['rooms'] if r['id'] != room_id]
        save_user_data(user_data)
        return jsonify({"status": "success", "message": "Room deleted."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/add-room', methods=['POST'])
@login_required
def add_room():
    try:
        data_from_request = request.json
        room_name = data_from_request['name']
        user_data = get_user_data()
        new_room_id = str(len(user_data['rooms']) + 1)
        user_data['rooms'].append({"id": new_room_id, "name": room_name, "ai_control": False, "appliances": []})
        save_user_data(user_data)
        return jsonify({"status": "success", "room_id": new_room_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete-appliance', methods=['POST'])
@login_required
def delete_appliance():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        appliance_id = data_from_request['appliance_id']

        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404

        room['appliances'] = [a for a in room['appliances'] if a['id'] != appliance_id]
        save_user_data(user_data)
        return jsonify({"status": "success", "message": "Appliance deleted."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
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
        
        if not state:
            appliance['timer'] = None

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
        
        action = "turned ON" if state else "turned OFF"
        message = f"Appliance '{appliance['name']}' in room '{room['name']}' has been {action}."
        
        return jsonify({"status": "success", "message": message}), 200
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

@app.route('/api/update-appliance-settings', methods=['POST'])
@login_required
def update_appliance_settings():
    try:
        data_from_request = request.json
        room_id = data_from_request['room_id']
        appliance_id = data_from_request['appliance_id']
        new_name = data_from_request['name']
        new_relay_number = data_from_request['relay_number']
        new_room_id = data_from_request['new_room_id']
        
        user_data = get_user_data()
        
        original_room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not original_room:
            return jsonify({"status": "error", "message": "Original room not found."}), 404
        appliance = next((a for a in original_room['appliances'] if a['id'] == appliance_id), None)
        if not appliance:
            return jsonify({"status": "error", "message": "Appliance not found."}), 403
        
        if new_room_id and new_room_id != room_id:
            target_room = next((r for r in user_data['rooms'] if r['id'] == new_room_id), None)
            if not target_room:
                return jsonify({"status": "error", "message": "Target room not found."}), 404
            
            original_room['appliances'].remove(appliance)
            appliance['id'] = str(len(target_room['appliances']) + 1)
            target_room['appliances'].append(appliance)
        
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
        timer_timestamp = data_from_request.get('timer')
        
        user_data = get_user_data()
        room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
        if not room:
            return jsonify({"status": "error", "message": "Room not found."}), 404
        
        appliance = next((a for a in room['appliances'] if a['id'] == appliance_id), None)
        if not appliance:
            return jsonify({"status": "error", "message": "Appliance not found."}), 403
        
        if timer_timestamp:
            appliance['state'] = True
            appliance['timer'] = timer_timestamp
            user_data['last_command'] = {
                "room_id": room_id,
                "appliance_id": appliance_id,
                "state": True,
                "relay_number": appliance['relay_number'],
                "timestamp": int(time.time())
            }
            if mqtt_client:
                mqtt_client.publish(MQTT_TOPIC_COMMAND, f"{current_user.id}:{room_id}:{appliance_id}:{appliance['relay_number']}:on")
        else: # Timer is being cancelled or turned off
            appliance['state'] = False
            appliance['timer'] = None
            user_data['last_command'] = {
                "room_id": room_id,
                "appliance_id": appliance_id,
                "state": False,
                "relay_number": appliance['relay_number'],
                "timestamp": int(time.time())
            }
            if mqtt_client:
                 mqtt_client.publish(MQTT_TOPIC_COMMAND, f"{current_user.id}:{room_id}:{appliance_id}:{appliance['relay_number']}:off")


        save_user_data(user_data)
        
        return jsonify({"status": "success", "message": "Timer set."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route('/api/save-room-order', methods=['POST'])
@login_required
def save_room_order():
    try:
        data_from_request = request.json
        new_order_ids = data_from_request['order']
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

@app.route('/api/get-analytics', methods=['GET'])
@login_required
def get_analytics():
    try:
        analytics_data = load_analytics_data()
        
        # Aggregate data by hour, day, and month
        hourly_data = {str(i): 0 for i in range(24)}
        daily_data = {}
        monthly_data = {}

        for record in analytics_data:
            # Hourly aggregation
            hour = record['hour']
            hourly_data[str(hour)] += record['consumption']
            
            # Daily aggregation
            date = record['date']
            daily_data[date] = daily_data.get(date, 0) + record['consumption']

            # Monthly aggregation
            month = date[:7] # YYYY-MM
            monthly_data[month] = monthly_data.get(month, 0) + record['consumption']

        # Calculate stats
        total_consumption = sum(d['consumption'] for d in analytics_data)
        highest_usage = max(d['consumption'] for d in analytics_data) if analytics_data else 0
        average_usage = total_consumption / len(analytics_data) if analytics_data else 0
        # Placeholder for savings calculation
        estimated_savings = total_consumption * 0.15 # 15% arbitrary saving

        stats = {
            "highest_usage": highest_usage,
            "average_usage": average_usage,
            "savings": estimated_savings
        }

        return jsonify({
            "stats": stats,
            "hourly": hourly_data,
            "daily": daily_data,
            "monthly": monthly_data
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/get-user-settings', methods=['GET'])
@login_required
def get_user_settings():
    try:
        user_data = get_user_data()
        return jsonify(user_data['user_settings']), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/set-user-settings', methods=['POST'])
@login_required
def set_user_settings():
    try:
        new_settings = request.json
        user_data = get_user_data()
        user_data['user_settings'].update(new_settings)
        save_user_data(user_data)
        return jsonify({"status": "success", "message": "Settings updated."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    try:
        data_from_request = request.json
        old_password = data_from_request['old_password']
        new_password = data_from_request['new_password']
        
        users = load_users()
        user_found = next((user for user in users if user['id'] == current_user.id), None)

        if user_found and check_password_hash(user_found['password_hash'], old_password):
            user_found['password_hash'] = generate_password_hash(new_password)
            save_users(users)
            return jsonify({"status": "success", "message": "Password updated successfully."}), 200
        else:
            return jsonify({"status": "error", "message": "Invalid old password."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/set-global-ai-control', methods=['POST'])
@login_required
def set_global_ai_control():
    try:
        data_from_request = request.json
        state = data_from_request['state']
        user_data = get_user_data()

        for room in user_data['rooms']:
            room['ai_control'] = state
        
        save_user_data(user_data)
        
        action = "enabled" if state else "disabled"
        message = f"AI control for all rooms has been {action}."
        
        return jsonify({"status": "success", "message": message}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/ai-detection-signal', methods=['POST'])
@login_required
def ai_detection_signal():
    try:
        data_from_request = request.json
        room_id = data_from_request.get('room_id') # Can be None for global
        state = data_from_request['state']
        
        user_data = get_user_data()

        if room_id:
            # Per-room control
            room = next((r for r in user_data['rooms'] if r['id'] == room_id), None)
            if not room:
                return jsonify({"status": "error", "message": "Room not found."}), 404
            
            for appliance in room['appliances']:
                if not appliance['locked']:
                    appliance['state'] = state
        else:
            # Global control
            for room in user_data['rooms']:
                for appliance in room['appliances']:
                    if not appliance['locked']:
                        appliance['state'] = state

        user_data['last_command'] = {
            "room_id": room_id,
            "state": state,
            "timestamp": int(time.time())
        }
        
        save_user_data(user_data)

        if mqtt_client:
            topic_payload = f"{current_user.id}:{room_id or 'all'}:ai:{int(state)}"
            mqtt_client.publish(MQTT_TOPIC_COMMAND, topic_payload)

        action = "activated" if state else "deactivated"
        message = f"AI control has been {action}."
        
        return jsonify({"status": "success", "message": message}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        

def send_detection_email_thread(recipient, subject, body, image_data):
    """Send email in a separate thread to prevent blocking."""
    def send_email():
        with app.app_context():
            print(f"Preparing to send email to {recipient}...")
            try:
                if not recipient or not subject or not body:
                    print("Email sending failed: Missing required fields")
                    return
                
                msg = Message(
                    subject=subject,
                    recipients=[recipient]
                )
                msg.html = body
                
                if image_data:
                    try:
                        if ',' in image_data:
                            image_binary = base64.b64decode(image_data.split(',')[1])
                        else:
                            image_binary = base64.b64decode(image_data)
                        
                        msg.attach(
                            "detection_alert.png",
                            "image/png",
                            image_binary
                        )
                    except Exception as img_error:
                        print(f"Error processing image attachment: {img_error}")
                        
                mail.send(msg)
                print(f"Email sent successfully to {recipient}!")
                
            except Exception as e:
                print(f"Error sending email: {e}")
    
    email_thread = threading.Thread(target=send_email)
    email_thread.daemon = True
    email_thread.start()


@app.route('/api/send-detection-email', methods=['POST'])
@login_required
def send_detection_email():
    try:
        data_from_request = request.json
        room_name = data_from_request.get('room_name')
        is_global = data_from_request.get('is_global', False)
        image_data = data_from_request['image_data']
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        user_data = get_user_data()
        recipient_email = user_data['user_settings']['email']
        
        if not recipient_email:
            print("No recipient email found in user settings. Email not sent.")
            return jsonify({"status": "error", "message": "User email not set for notifications."}), 400
        
        if is_global:
            subject = "Luminous Home System Alert: Human Detected at Home"
            message_text = "A human has been detected at your home. All unlocked appliances have been activated."
        else:
            subject = "Luminous Home System Alert: Motion Detected!"
            message_text = f"Motion has been detected in your room: {room_name}"

        body_html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
                    <h2 style="color: #d9534f;">Luminous Home System Alert!</h2>
                    <hr style="border: 1px solid #ddd;">
                    <p>Dear {current_user.username},</p>
                    <p>This is an automated alert from your Luminous Home System.</p>
                    <p>{message_text}</p>
                    <p>Time of detection: <strong>{timestamp}</strong></p>
                    <p>Please find the captured image attached below:</p>
                    <img src="cid:myimage" alt="Motion Detection Alert" style="max-width: 100%; height: auto; border-radius: 5px;">
                </div>
            </body>
        </html>
        """
        
        send_detection_email_thread(recipient_email, subject, body_html, image_data)
        
        print("API call to send email initiated.")
        return jsonify({"status": "success", "message": "Email alert sent."}), 200
        
    except Exception as e:
        print(f"Error in send_detection_email endpoint: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    generate_analytics_data()
    run_mqtt_thread()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
