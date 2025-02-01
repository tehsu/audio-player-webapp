import os
from flask import Flask, request, render_template, jsonify, send_from_directory
import vlc
import threading
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
player = None
current_media = None

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def init_player():
    global player
    if player is None:
        instance = vlc.Instance()
        player = instance.media_player_new()

def cleanup_old_files():
    """Remove files older than 24 hours from the uploads directory"""
    cutoff_time = datetime.now() - timedelta(hours=24)
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
        if file_modified < cutoff_time:
            try:
                os.remove(file_path)
                print(f"Removed old file: {filename}")
            except Exception as e:
                print(f"Error removing file {filename}: {e}")

# Initialize the scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=cleanup_old_files, trigger="interval", hours=1)
scheduler.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    global current_media
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not file.filename.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a')):
        return jsonify({'error': 'Invalid file type'}), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(filepath)
    
    init_player()
    
    # Create a new media instance
    instance = vlc.Instance()
    current_media = instance.media_new(filepath)
    player.set_media(current_media)
    
    return jsonify({'message': 'File uploaded successfully', 'filename': file.filename})

@app.route('/play', methods=['POST'])
def play():
    if player is None or current_media is None:
        return jsonify({'error': 'No audio loaded'}), 400
    
    player.play()
    return jsonify({'message': 'Playing audio'})

@app.route('/pause', methods=['POST'])
def pause():
    if player is None:
        return jsonify({'error': 'No audio loaded'}), 400
    
    player.pause()
    return jsonify({'message': 'Paused audio'})

@app.route('/stop', methods=['POST'])
def stop():
    if player is None:
        return jsonify({'error': 'No audio loaded'}), 400
    
    player.stop()
    return jsonify({'message': 'Stopped audio'})

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000)
    finally:
        # Shut down the scheduler when the app is closing
        scheduler.shutdown()
