import os
import json
import time
import csv
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import paho.mqtt.client as mqtt
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
import requests
import base64

# --- Application Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-super-secret-key')  # Change this in production
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'signin'

# --- Flask-Mail Configuration (Improved) ---
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])

# Configure upload folder for email attachments
UPLOAD_FOLDER = 'temp_attachments'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create the upload folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Initialize Mail with validation
def init_mail_config():
    """Check if email configuration is available."""
    required_vars = ['MAIL_USERNAME', 'MAIL_PASSWORD']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"Warning: Missing email configuration: {missing_vars}")
        print("Email functionality will be limited")
        return False
    return True

mail_configured = init_mail_config()
if mail_configured:
    mail = Mail(app)
    print("✅ Email system initialized successfully")
else:
    mail = None
    print("⚠️ Email system disabled due to missing configuration")

def allowed_file(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

# --- Improved Email Sending Logic ---
def send_detection_email_sync(recipient, subject, body, image_data=None):
    """
    Send email synchronously with proper error handling.
    Returns (success: bool, message: str)
    """
    if not mail:
        return False, "Email system not configured. Please set MAIL_USERNAME and MAIL_PASSWORD environment variables."
    
    try:
        # Basic validation
        if not recipient or not subject or not body:
            return False, "Recipient, subject, and body are required!"
        
        print(f"Preparing to send email to {recipient}...")
        
        # Create message
        msg = Message(
            subject=subject,
            recipients=[recipient],
            sender=app.config['MAIL_DEFAULT_SENDER']
        )
        msg.html = body
        
        # Handle image attachment if provided
        if image_data:
            try:
                # Handle base64 image data
                if isinstance(image_data, str) and image_data.startswith('data:image'):
                    # Extract image format and data
                    header, encoded = image_data.split(',', 1)
                    image_format = header.split('/')[1].split(';')[0]  # e.g., 'png'
                    image_binary = base64.b64decode(encoded)
                    
                    # Create a temporary file
                    filename = f"detection_alert_{int(time.time())}.{image_format}"
                    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    with open(temp_path, 'wb') as f:
                        f.write(image_binary)
                    
                    # Attach the file
                    with app.open_resource(temp_path) as fp:
                        msg.attach(filename, f"image/{image_format}", fp.read(), 'inline', 
                                 headers=[('Content-ID', '<detection_image>')])
                    
                    # Clean up the temporary file
                    os.remove(temp_path)
                    
                elif isinstance(image_data, str):
                    # Handle raw base64 without data URL prefix
                    image_binary = base64.b64decode(image_data)
                    msg.attach("detection_alert.png", "image/png", image_binary, 'inline', 
                             headers=[('Content-ID', '<detection_image>')])
                
            except Exception as img_error:
                print(f"Warning: Error processing image attachment: {img_error}")
                # Continue without attachment if image processing fails
        
        # Send the email
        mail.send(msg)
        success_msg = f"Email sent successfully to {recipient}!"
        print(f"✅ {success_msg}")
        return True, success_msg
        
    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        print(f"❌ {error_msg}")
        return False, error_msg

def send_detection_email_thread(recipient, subject, body, image_data=None):
    """Send email in a separate thread to prevent blocking."""
    def send_email():
        with app.app_context():
            success, message = send_detection_email_sync(recipient, subject, body, image_data)
            if success:
                print(f"Email thread completed successfully: {message}")
            else:
                print(f"Email thread failed: {message}")
    
    # Start email sending in a separate thread
    email_thread = threading.Thread(target=send_email)
    email_thread.daemon = True
    email_thread.start()

# --- Test Email Endpoint ---
@app.route('/api/test-email', methods=['POST'])
@login_required
def test_email():
    """Test email functionality with current user's email."""
    try:
        if not mail:
            return jsonify({
                "status": "error", 
                "message": "Email system not configured. Please set MAIL_USERNAME and MAIL_PASSWORD environment variables."
            }), 500
        
        user_data = get_user_data()
        test_recipient = user_data['user_settings'].get('email')
        
        if not test_recipient:
            return jsonify({
                "status": "error", 
                "message": "No email address found in user settings. Please set your email address first."
            }), 400
        
        subject = "Luminous System - Email Test"
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #4CAF50;">Email Test Successful! ✅</h2>
                <p>Hello {current_user.username},</p>
                <p>This is a test email from your Luminous Home System to verify that email functionality is working correctly.</p>
                <p><strong>Test sent at:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <hr>
                <p style="font-size: 12px; color: #666;">
                    If you received this email, your email configuration is working properly.
                </p>
            </body>
        </html>
        """
        
        success, message = send_detection_email_sync(test_recipient, subject, body)
        
        if success:
            return jsonify({"status": "success", "message": message}), 200
        else:
            return jsonify({"status": "error", "message": message}), 500
            
    except Exception as e:
        return jsonify({"status": "error", "message": f"Test email failed: {str(e)}"}), 500

# --- Frontend Routes (unchanged) ---
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

# --- Backend API Endpoints (keeping all your existing endpoints) ---
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

@app.route('/api/get-rooms-and-appliances', methods=['GET'])
@login_required
def get_rooms_and_appliances():
    try:
        user_data = get_user_data()
        return jsonify(user_data['rooms']), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# [Continue with all your existing API endpoints - they remain unchanged]
# I'll just show the modified send_detection_email endpoint:

@app.route('/api/send-detection-email', methods=['POST'])
@login_required
def send_detection_email():
    try:
        data_from_request = request.json
        room_name = data_from_request['room_name']
        image_data = data_from_request.get('image_data')
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        user_data = get_user_data()
        recipient_email = user_data['user_settings']['email']

        if not recipient_email:
            return jsonify({
                "status": "error", 
                "message": "User email not set for notifications. Please update your email in settings."
            }), 400

        subject = "Luminous Home System Alert: Motion Detected!"
        body_html = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
                    <h2 style="color: #d9534f;">🚨 Luminous Home System Alert!</h2>
                    <hr style="border: 1px solid #ddd;">
                    <p>Dear {current_user.username},</p>
                    <p>This is an automated alert from your Luminous Home System.</p>
                    <p><strong>Motion detected in room:</strong> {room_name}</p>
                    <p><strong>Time of detection:</strong> {timestamp}</p>
                    {f'<p>Please find the captured image attached below:</p><img src="cid:detection_image" alt="Motion Detection Alert" style="max-width: 100%; height: auto; border-radius: 5px; margin-top: 10px;">' if image_data else '<p>No image captured with this alert.</p>'}
                    <hr style="margin-top: 20px;">
                    <p style="font-size: 12px; color: #666;">
                        This is an automated message from your Luminous Home System.
                    </p>
                </div>
            </body>
        </html>
        """
        
        # Send email using the improved function
        success, message = send_detection_email_sync(recipient_email, subject, body_html, image_data)
        
        if success:
            return jsonify({"status": "success", "message": message}), 200
        else:
            return jsonify({"status": "error", "message": message}), 500

    except Exception as e:
        print(f"Error in send_detection_email endpoint: {e}")
        return jsonify({"status": "error", "message": f"Unexpected error: {str(e)}"}), 500

if __name__ == '__main__':
    generate_analytics_data()
    run_mqtt_thread()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
