import os
import json
import time
import csv
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from authlib.integrations.flask_client import OAuth
import paho.mqtt.client as mqtt
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
import requests
import base64


# --- Application Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a-fallback-secret-key-for-development')

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

ELECTRICITY_RATE = 6.50

# --- Gemini API Setup ---
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key="
API_KEY = ""  # Your API Key will be automatically provided by the Canvas environment

# --- MQTT Setup ---
MQTT_BROKER = "mqtt.eclipse.org"
MQTT_PORT = 1883
MQTT_TOPIC_COMMAND = "lumino_us/commands"
MQTT_TOPIC_STATUS = "lumino_us/status"

mqtt_client = None

app.secret_key = os.urandom(24)

# OAuth Configuration
oauth = OAuth(app)

google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_params=None,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',  # This is the endpoint to get user info
    client_kwargs={'scope': 'openid email profile'},
    # server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
    jwks_uri='https://www.googleapis.com/oauth2/v3/certs'
)

github = oauth.register(
    name='github',
    client_id=os.getenv('GITHUB_CLIENT_ID'),
    client_secret=os.getenv('GITHUB_CLIENT_SECRET'),
    access_token_url='https://github.com/login/oauth/access_token',
    access_token_params=None,
    authorize_url='https://github.com/login/oauth/authorize',
    authorize_params=None,
    api_base_url='https://api.github.com/',
    client_kwargs={'scope': 'user:email'}
)

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

# In app.py, add this new function

def create_default_user_data(name, email, picture=None):
    """Creates the default data structure for a new user."""
    return {
        "user_settings": {
            "name": name,
            "email": email,
            "picture": picture,
            "mobile": "", "channel": "email", "theme": "light", "ai_control_interval": 5
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

# --- Data Persistence Functions ---
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump({}, f)
    with open(DATA_FILE, 'r') as f:
        return json.load(f)

# In app.py

# In app.py
def find_or_create_oauth_user(profile):
    """
    Finds a user by email to link accounts, or creates a new user.
    """
    all_data = load_data()
    users = load_users()
    
    # 1. Find existing user by email to link accounts
    existing_user_id = None
    for user_id, user_data in all_data.items():
        if user_data.get("user_settings", {}).get("email") == profile['email']:
            existing_user_id = user_id
            break

    if existing_user_id:
        # User found! Link the new provider to this existing account.
        user_record = next((u for u in users if u['id'] == existing_user_id), None)
        if not user_record:
            return "Error: Data inconsistency found.", 500
        
        # Add the provider's ID to the user's record
        if profile['provider'] == 'google':
            user_record['google_id'] = profile['provider_id']
        elif profile['provider'] == 'github':
            user_record['github_id'] = profile['provider_id']
        
        save_users(users) # Save the updated user record
        
        # Log the user in
        user_obj = User(user_record['id'], user_record['username'], user_record['password_hash'])
        login_user(user_obj)
        return redirect(url_for('home'))

    # 2. If no user with that email exists, create a new account
    new_user_id = str(int(users[-1]['id']) + 1) if users else "1"
    
    # Create new entry in users.json
    new_user = {
        'id': new_user_id,
        'username': profile['name'],
        'password_hash': None,
        'google_id': profile['provider_id'] if profile['provider'] == 'google' else None,
        'github_id': profile['provider_id'] if profile['provider'] == 'github' else None,
    }
    users.append(new_user)
    save_users(users)
    
    # Create new entry in data.json using your helper function
    all_data[new_user_id] = create_default_user_data(
        name=profile['name'],
        email=profile['email'],
        picture=profile['picture']
    )
    save_data(all_data)
    
    # Log the new user in
    user_obj = User(new_user['id'], new_user['username'], new_user['password_hash'])
    login_user(user_obj)
    return redirect(url_for('home'))

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
def generate_analytics_data():
    """Your existing function with minor improvements"""
    if os.path.exists(ANALYTICS_FILE):
        return
    start_date = datetime.now() - timedelta(days=365)
    with open(ANALYTICS_FILE, 'w', newline='') as csvfile:
        fieldnames = ['date', 'hour', 'consumption']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for i in range(365 * 24):
            current_datetime = start_date + timedelta(hours=i)
            # More realistic consumption pattern
            base_consumption = 50
            hour_factor = (i % 24) * 2  # Higher usage during day
            day_factor = (i % 7) * 5    # Higher usage on weekends
            seasonal_factor = 10 * (1 + 0.3 * (i // (24*30)) % 12 / 12)  # Seasonal variation
            random_factor = os.urandom(1)[0] % 20 - 10  # Random variation
            
            consumption = base_consumption + hour_factor + day_factor + seasonal_factor + random_factor
            consumption = max(20, consumption)  # Minimum consumption
            
            writer.writerow({
                'date': current_datetime.strftime('%Y-%m-%d'),
                'hour': current_datetime.hour,
                'consumption': round(consumption, 2)
            })

def load_analytics_data():
    """Your existing function"""
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

def process_hourly_data(data):
    """Process data for last 24 hours view"""
    now = datetime.now()
    last_24h = now - timedelta(hours=24)
    
    hourly_data = defaultdict(float)
    
    for record in data:
        record_datetime = datetime.strptime(f"{record['date']} {record['hour']:02d}:00:00", "%Y-%m-%d %H:%M:%S")
        if record_datetime >= last_24h:
            hour_label = record_datetime.strftime("%H:00")
            hourly_data[hour_label] = record['consumption']
    
    # Fill missing hours with 0
    labels = []
    values = []
    for i in range(24):
        hour_label = f"{i:02d}:00"
        labels.append(hour_label)
        values.append(hourly_data.get(hour_label, 0))
    
    return {'labels': labels, 'values': values}

def process_weekly_data(data):
    """Process data for last 7 days view"""
    now = datetime.now()
    last_7_days = now - timedelta(days=7)
    
    daily_data = defaultdict(float)
    daily_counts = defaultdict(int)
    
    for record in data:
        record_date = datetime.strptime(record['date'], "%Y-%m-%d")
        if record_date >= last_7_days:
            day_label = record_date.strftime("%Y-%m-%d")
            daily_data[day_label] += record['consumption']
            daily_counts[day_label] += 1
    
    # Average consumption per day
    for day in daily_data:
        if daily_counts[day] > 0:
            daily_data[day] = daily_data[day] / daily_counts[day]
    
    labels = []
    values = []
    for i in range(7):
        date = (now - timedelta(days=6-i)).strftime("%Y-%m-%d")
        day_name = (now - timedelta(days=6-i)).strftime("%a")
        labels.append(day_name)
        values.append(daily_data.get(date, 0))
    
    return {'labels': labels, 'values': values}

def process_yearly_data(data):
    """Process data for last 12 months view"""
    now = datetime.now()
    monthly_data = defaultdict(float)
    monthly_counts = defaultdict(int)
    
    for record in data:
        record_date = datetime.strptime(record['date'], "%Y-%m-%d")
        if (now - record_date).days <= 365:
            month_label = record_date.strftime("%Y-%m")
            monthly_data[month_label] += record['consumption']
            monthly_counts[month_label] += 1
    
    # Average consumption per month
    for month in monthly_data:
        if monthly_counts[month] > 0:
            monthly_data[month] = monthly_data[month] / monthly_counts[month]
    
    labels = []
    values = []
    for i in range(12):
        date = now.replace(day=1) - timedelta(days=30*i)
        month_label = date.strftime("%Y-%m")
        month_name = date.strftime("%b %Y")
        labels.insert(0, month_name)
        values.insert(0, monthly_data.get(month_label, 0))
    
    return {'labels': labels, 'values': values}

def calculate_statistics(data):
    """Calculate comprehensive statistics"""
    now = datetime.now()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
    
    this_month_data = []
    last_month_data = []
    all_consumption = []
    peak_usage = 0
    peak_time = ""
    
    for record in data:
        record_date = datetime.strptime(record['date'], "%Y-%m-%d")
        consumption = record['consumption']
        all_consumption.append(consumption)
        
        # Track peak usage
        if consumption > peak_usage:
            peak_usage = consumption
            peak_time = f"{record['date']} {record['hour']:02d}:00"
        
        # Monthly comparison
        if record_date >= this_month_start:
            this_month_data.append(consumption)
        elif record_date >= last_month_start and record_date < this_month_start:
            last_month_data.append(consumption)
    
    # Calculate statistics
    total_consumption = sum(this_month_data) if this_month_data else 0
    average_daily = total_consumption / max(1, len(set(record['date'] for record in data 
                    if datetime.strptime(record['date'], "%Y-%m-%d") >= this_month_start)))
    
    # Calculate monthly change
    this_month_avg = statistics.mean(this_month_data) if this_month_data else 0
    last_month_avg = statistics.mean(last_month_data) if last_month_data else 0
    daily_change = ((this_month_avg - last_month_avg) / max(last_month_avg, 1)) * 100 if last_month_avg > 0 else 0
    
    estimated_cost = total_consumption * ELECTRICITY_RATE
    
    return {
        'total_consumption': total_consumption,
        'average_daily': average_daily,
        'peak_usage': peak_usage,
        'peak_time': peak_time,
        'daily_change': daily_change,
        'estimated_cost': estimated_cost
    }

def analyze_peak_usage(data):
    """Analyze peak usage by hour of day"""
    hourly_peaks = defaultdict(list)
    
    for record in data:
        hour = record['hour']
        consumption = record['consumption']
        hourly_peaks[hour].append(consumption)
    
    labels = [f"{i:02d}:00" for i in range(24)]
    values = []
    
    for i in range(24):
        if i in hourly_peaks and hourly_peaks[i]:
            values.append(max(hourly_peaks[i]))
        else:
            values.append(0)
    
    return {'labels': labels, 'values': values}

def calculate_usage_distribution(data):
    """Calculate usage distribution for pie chart"""
    all_consumption = [record['consumption'] for record in data]
    if not all_consumption:
        return [25, 25, 25, 25]  # Default equal distribution
    
    # Define usage categories based on percentiles
    sorted_consumption = sorted(all_consumption)
    total_records = len(sorted_consumption)
    
    q1 = sorted_consumption[total_records // 4]
    q2 = sorted_consumption[total_records // 2]
    q3 = sorted_consumption[3 * total_records // 4]
    
    low_count = sum(1 for c in all_consumption if c <= q1)
    medium_count = sum(1 for c in all_consumption if q1 < c <= q2)
    high_count = sum(1 for c in all_consumption if q2 < c <= q3)
    peak_count = sum(1 for c in all_consumption if c > q3)
    
    return [low_count, medium_count, high_count, peak_count]

def calculate_weekly_pattern(data):
    """Calculate average usage by day of week"""
    daily_totals = defaultdict(list)
    
    for record in data:
        record_date = datetime.strptime(record['date'], "%Y-%m-%d")
        day_of_week = record_date.weekday()  # 0 = Monday
        daily_totals[day_of_week].append(record['consumption'])
    
    # Calculate averages for each day
    weekly_averages = []
    for i in range(7):  # Monday to Sunday
        if i in daily_totals and daily_totals[i]:
            avg = statistics.mean(daily_totals[i])
            weekly_averages.append(round(avg, 2))
        else:
            weekly_averages.append(0)
    
    return weekly_averages

def calculate_cost_breakdown(total_consumption):
    """Calculate detailed cost breakdown"""
    base_charges = 150.0  # Fixed monthly charge
    energy_charges = total_consumption * ELECTRICITY_RATE
    tax_surcharge = (base_charges + energy_charges) * 0.15  # 15% tax
    
    total = base_charges + energy_charges + tax_surcharge
    
    return {
        'base_charges': base_charges,
        'energy_charges': energy_charges,
        'tax_surcharge': tax_surcharge,
        'total': total
    }

def generate_efficiency_insights(data, stats):
    """Generate efficiency insights and recommendations"""
    insights = []
    
    # Calculate efficiency score
    all_consumption = [record['consumption'] for record in data]
    avg_consumption = statistics.mean(all_consumption) if all_consumption else 0
    optimal_consumption = 60  # Assumed optimal consumption
    efficiency_score = max(0, min(100, 100 - (avg_consumption - optimal_consumption) / optimal_consumption * 100))
    
    # Generate insights based on data
    if stats['peak_usage'] > 100:
        insights.append({
            'type': 'warning',
            'message': f'High peak usage detected ({stats["peak_usage"]:.1f} kWh). Consider load balancing during peak hours.'
        })
    
    if stats['daily_change'] > 10:
        insights.append({
            'type': 'warning',
            'message': f'Usage increased by {stats["daily_change"]:.1f}% this month. Review your energy habits.'
        })
    elif stats['daily_change'] < -10:
        insights.append({
            'type': 'success',
            'message': f'Great! Usage decreased by {abs(stats["daily_change"]):.1f}% this month.'
        })
    
    if avg_consumption < optimal_consumption:
        insights.append({
            'type': 'success',
            'message': 'Your consumption is below the optimal range. Excellent energy management!'
        })
    
    # Time-based insights
    peak_hour = int(stats['peak_time'].split(' ')[1].split(':')[0]) if stats['peak_time'] else 12
    if 9 <= peak_hour <= 17:
        insights.append({
            'type': 'info',
            'message': 'Peak usage occurs during business hours. Consider time-of-use optimization.'
        })
    
    return {
        'score': round(efficiency_score),
        'insights': insights
    }

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
        # data = load_data()
        # data[new_user_id] = {
        #     "user_settings": {
        #         "name": "hi",
        #         "email": "", "mobile": "", "channel": "email", "theme": "light", "ai_control_interval": 5
        #     },
        #     "rooms": [{
        #         "id": "1",
        #         "name": "Hall",
        #         "ai_control": False,
        #         "appliances": [
        #             {"id": "1", "name": "Main Light", "state": False, "locked": False, "timer": None, "relay_number": 1},
        #             {"id": "2", "name": "Fan", "state": False, "locked": False, "timer": None, "relay_number": 2},
        #             {"id": "3", "name": "Night Lamp", "state": False, "locked": False, "timer": None, "relay_number": 3},
        #             {"id": "4", "name": "A/C", "state": False, "locked": False, "timer": None, "relay_number": 4}
        #         ]
        #     }]
        # }
        # save_data(data)

        data = load_data()
        # Standard signup form doesn't have email, so we pass an empty string
        data[new_user_id] = create_default_user_data(name=username, email="")
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

@app.route('/api/global-ai-signal', methods=['POST'])
def global_ai_signal():
    """
    Receives a signal for global AI control and updates all non-locked appliances.
    """
    data = request.get_json()
    if data is None or 'state' not in data:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    human_detected = data.get('state', False)
    action_str = "ON" if human_detected else "OFF"
    updated_count = 0

    try:
        # Get all user data and iterate through all users and their rooms
        all_data = load_data()
        
        for user_id, user_data in all_data.items():
            if 'rooms' not in user_data:
                continue
                
            # Iterate through all rooms for this user
            for room in user_data['rooms']:
                for appliance in room['appliances']:
                    # Check if the appliance is NOT locked
                    if not appliance.get('locked', False):
                        # Update the state in our backend data
                        appliance['state'] = human_detected
                        updated_count += 1
        
        # Save the updated data back to file
        save_data(all_data)
        
        # Send MQTT command for global control (if MQTT client exists)
        if mqtt_client:
            mqtt_client.publish(MQTT_TOPIC_COMMAND, f"global:all:ai:{int(human_detected)}")
        
        message = f"Global signal processed. Turned {action_str} {updated_count} unlocked appliances."
        return jsonify({"status": "success", "message": message}), 200

    except Exception as e:
        print(f"Error processing global AI signal: {e}")
        return jsonify({"status": "error", "message": "An internal error occurred"}), 500


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
            "savings": estimated_savings,
            # Additional stats for advanced dashboard
            "total_consumption": total_consumption,
            "average_daily": total_consumption / max(1, len(set(record['date'] for record in analytics_data))),
            "peak_usage": highest_usage,
            "peak_time": "12:00 PM",  # Placeholder
            "daily_change": 5.2,  # Placeholder percentage change
            "estimated_cost": total_consumption * ELECTRICITY_RATE
        }
        
        # Convert your existing data format to match frontend expectations
        # Transform hourly data for last 24 hours
        hourly_labels = [f"{i:02d}:00" for i in range(24)]
        hourly_values = [hourly_data.get(str(i), 0) for i in range(24)]
        
        # Transform daily data for last 7 days (get most recent 7 days)
        sorted_daily = sorted(daily_data.items(), key=lambda x: x[0], reverse=True)[:7]
        weekly_labels = [datetime.strptime(date, "%Y-%m-%d").strftime("%a") for date, _ in reversed(sorted_daily)]
        weekly_values = [value for _, value in reversed(sorted_daily)]
        
        # Transform monthly data for last 12 months
        sorted_monthly = sorted(monthly_data.items(), key=lambda x: x[0], reverse=True)[:12]
        yearly_labels = [datetime.strptime(f"{month}-01", "%Y-%m-%d").strftime("%b %Y") for month, _ in reversed(sorted_monthly)]
        yearly_values = [value for _, value in reversed(sorted_monthly)]
        
        # Generate additional analytics for advanced features
        peak_analysis = {
            'labels': hourly_labels,
            'values': [max(80, hourly_data.get(str(i), 0) + (i * 2)) for i in range(24)]  # Mock peak data
        }
        
        distribution = [25, 35, 25, 15]  # Mock distribution data
        
        weekly_pattern = [65, 70, 68, 72, 75, 85, 80]  # Mock weekly pattern
        
        cost_breakdown = calculate_cost_breakdown(total_consumption)
        
        efficiency_insights = [
            {"type": "success", "message": "Your consumption is optimized during off-peak hours."},
            {"type": "warning", "message": "Consider reducing usage during peak hours (6-9 PM)."},
            {"type": "info", "message": "Switch to LED bulbs for 20% energy savings."}
        ]
        
        return jsonify({
            "stats": stats,
            "hourly": {"labels": hourly_labels, "values": hourly_values},
            "weekly": {"labels": weekly_labels, "values": weekly_values},
            "yearly": {"labels": yearly_labels, "values": yearly_values},
            "peak_analysis": peak_analysis,
            "distribution": distribution,
            "weekly_pattern": weekly_pattern,
            "cost_breakdown": cost_breakdown,
            "efficiency_insights": efficiency_insights,
            "efficiency_score": 78
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/export-data')
@login_required
def export_data():
    """Export analytics data in various formats"""
    format_type = request.args.get('format', 'csv').lower()
    
    try:
        raw_data = load_analytics_data()
        if not raw_data:
            return jsonify({'error': 'No data to export'}), 404
        
        if format_type == 'csv':
            # Create temporary CSV file
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
            
            fieldnames = ['date', 'hour', 'consumption', 'cost']
            writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
            writer.writeheader()
            
            for record in raw_data:
                writer.writerow({
                    'date': record['date'],
                    'hour': f"{record['hour']:02d}:00",
                    'consumption': record['consumption'],
                    'cost': round(record['consumption'] * ELECTRICITY_RATE, 2)
                })
            
            temp_file.close()
            
            return send_file(
                temp_file.name,
                as_attachment=True,
                download_name=f'energy_consumption_{datetime.now().strftime("%Y%m%d")}.csv',
                mimetype='text/csv'
            )
        
        elif format_type == 'json':
            # Export as JSON
            export_data = {
                'export_date': datetime.now().isoformat(),
                'total_records': len(raw_data),
                'data': raw_data,
                'summary': calculate_statistics(raw_data)
            }
            
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
            json.dump(export_data, temp_file, indent=2)
            temp_file.close()
            
            return send_file(
                temp_file.name,
                as_attachment=True,
                download_name=f'energy_analytics_{datetime.now().strftime("%Y%m%d")}.json',
                mimetype='application/json'
            )
        
        else:
            return jsonify({'error': 'Unsupported format'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Export failed: {str(e)}'}), 500

@app.route('/api/efficiency-tips')
@login_required
def get_efficiency_tips():
    """Get personalized efficiency tips based on usage patterns"""
    try:
        raw_data = load_analytics_data()
        if not raw_data:
            return jsonify({'error': 'No data available'}), 404
        
        stats = calculate_statistics(raw_data)
        tips = []
        
        # Generate tips based on usage patterns
        if stats['peak_usage'] > 80:
            tips.append({
                'category': 'Peak Usage',
                'tip': 'Your peak usage is high. Consider using high-power appliances during off-peak hours.',
                'potential_savings': '15-20%'
            })
        
        if stats['daily_change'] > 5:
            tips.append({
                'category': 'Usage Trend',
                'tip': 'Your consumption has increased recently. Check for inefficient appliances or changed habits.',
                'potential_savings': '10-15%'
            })
        
        # Time-based tips
        hourly_usage = defaultdict(list)
        for record in raw_data:
            hourly_usage[record['hour']].append(record['consumption'])
        
        peak_hours = []
        for hour, consumptions in hourly_usage.items():
            if consumptions and statistics.mean(consumptions) > 70:
                peak_hours.append(hour)
        
        if any(9 <= hour <= 17 for hour in peak_hours):
            tips.append({
                'category': 'Time Management',
                'tip': 'High usage during business hours detected. Shift non-essential loads to night time.',
                'potential_savings': '8-12%'
            })
        
        # Seasonal tips
        current_month = datetime.now().month
        if current_month in [6, 7, 8]:  # Summer months
            tips.append({
                'category': 'Seasonal',
                'tip': 'Summer peak detected. Optimize AC usage and consider better insulation.',
                'potential_savings': '20-25%'
            })
        
        return jsonify({
            'tips': tips,
            'generated_at': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to generate tips: {str(e)}'}), 500

# Your existing route with theme support
@app.route('/analytics.html')
@login_required
def analytics():
    user_data = get_user_data()
    theme = user_data['user_settings']['theme']
    return render_template('analytics.html', theme=theme)

# Additional utility functions for advanced features
def calculate_carbon_footprint(consumption_kwh):
    """Calculate carbon footprint based on consumption"""
    # Average carbon emission factor for electricity in India: ~0.82 kg CO2/kWh
    carbon_factor = 0.82
    return consumption_kwh * carbon_factor

def predict_next_month_usage(data):
    """Simple prediction for next month's usage based on trends"""
    if len(data) < 30:  # Need at least 30 data points
        return None
    
    recent_data = data[-720:]  # Last 30 days (assuming hourly data)
    recent_avg = statistics.mean([record['consumption'] for record in recent_data])
    
    # Simple trend calculation
    older_data = data[-1440:-720] if len(data) >= 1440 else data[:-720]
    if older_data:
        older_avg = statistics.mean([record['consumption'] for record in older_data])
        trend = (recent_avg - older_avg) / older_avg if older_avg > 0 else 0
        predicted_usage = recent_avg * (1 + trend) * 30 * 24  # Monthly prediction
        return max(0, predicted_usage)
    
    return recent_avg * 30 * 24  # Simple monthly projection

@app.route('/api/predictions')
@login_required
def get_predictions():
    """Get usage predictions and projections"""
    try:
        raw_data = load_analytics_data()
        if not raw_data:
            return jsonify({'error': 'Insufficient data for predictions'}), 404
        
        next_month_prediction = predict_next_month_usage(raw_data)
        current_month_consumption = sum(record['consumption'] for record in raw_data 
                                      if datetime.strptime(record['date'], "%Y-%m-%d").month == datetime.now().month)
        
        predictions = {
            'next_month_kwh': round(next_month_prediction, 2) if next_month_prediction else None,
            'next_month_cost': round(next_month_prediction * ELECTRICITY_RATE, 2) if next_month_prediction else None,
            'carbon_footprint': round(calculate_carbon_footprint(current_month_consumption), 2),
            'projected_annual': round(current_month_consumption * 12, 2) if current_month_consumption else 0
        }
        
        return jsonify(predictions)
        
    except Exception as e:
        return jsonify({'error': f'Failed to generate predictions: {str(e)}'}), 500

# In app.py
@app.route('/api/get-user-settings', methods=['GET'])
@login_required
def get_user_settings():
    try:
        user_data = get_user_data()
        settings = user_data.get('user_settings', {})

        # Also load the main user record to get linked account info
        users = load_users()
        user_record = next((u for u in users if u['id'] == current_user.id), None)

        if user_record:
            settings['google_id'] = user_record.get('google_id')
            settings['github_id'] = user_record.get('github_id')
            settings['has_password'] = user_record.get('password_hash') is not None
        
        return jsonify(settings), 200
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
        
        if not user_found:
            return jsonify({"status": "error", "message": "User not found."}), 404
        
        # Check if user has no existing password (OAuth user setting password for first time)
        if not user_found.get('password_hash'):
            # No existing password, so set the new password directly
            user_found['password_hash'] = generate_password_hash(new_password)
            save_users(users)
            return jsonify({"status": "success", "message": "Password set successfully."}), 200
        
        # User has existing password, verify old password before updating
        if check_password_hash(user_found['password_hash'], old_password):
            user_found['password_hash'] = generate_password_hash(new_password)
            save_users(users)
            return jsonify({"status": "success", "message": "Password updated successfully."}), 200
        else:
            return jsonify({"status": "error", "message": "Invalid old password."}), 400
            
    except KeyError as e:
        return jsonify({"status": "error", "message": f"Missing required field: {str(e)}"}), 400
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


# --- ADD THIS SECTION: OAuth Login Routes ---

@app.route('/login/google')
def login_google():
    redirect_uri = url_for('authorize_google', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/google/callback')
def authorize_google():
    token = google.authorize_access_token()
    user_info = google.get('userinfo').json()
    
    profile = {
        'provider': 'google',
        'provider_id': user_info.get('sub'),  # 'sub' is the unique ID from Google
        'name': user_info.get('name'),
        'email': user_info.get('email'),
        'picture': user_info.get('picture')
    }
    return find_or_create_oauth_user(profile)

@app.route('/login/github')
def login_github():
    redirect_uri = url_for('authorize_github', _external=True)
    return github.authorize_redirect(redirect_uri)

@app.route('/github/callback')
def authorize_github():
    token = github.authorize_access_token()
    user_info = github.get('user').json()
    user_emails = github.get('user/emails').json()
    primary_email = next((e['email'] for e in user_emails if e['primary']), None)
    
    if not primary_email:
        return "Error: Could not retrieve a primary email from GitHub.", 400
        
    profile = {
        'provider': 'github',
        'provider_id': user_info.get('id'), # 'id' is the unique ID from GitHub
        'name': user_info.get('name') or user_info.get('login'),
        'email': primary_email,
        'picture': user_info.get('avatar_url')
    }
    return find_or_create_oauth_user(profile)

if __name__ == '__main__':
    generate_analytics_data()
    run_mqtt_thread()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
