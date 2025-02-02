from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_socketio import SocketIO, emit
import os
import threading
import time
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.utils import secure_filename
import subprocess
import json
import signal
import re

# Configure logging
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
        
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Global state
ffmpeg_process = None
current_media = None
player_state = {
    'current_file': None,
    'duration': 0,
    'position': 0,
    'fps': 0,
    'speed': '0x',
    'is_playing': False
}

def get_video_duration(filepath):
    """Get video duration using FFprobe"""
    cmd = [
        'ffprobe', 
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'json',
        filepath
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except:
        return 0

def monitor_ffmpeg_progress(process):
    """Monitor FFmpeg progress output"""
    global player_state
    
    progress_pattern = re.compile(r'(frame|fps|speed)=\s*([\d.]+)')
    
    while process.poll() is None:
        line = process.stderr.readline()
        if not line:
            continue
            
        matches = progress_pattern.finditer(line)
        for match in matches:
            key, value = match.groups()
            if key == 'frame':
                # Calculate position based on frame number and fps
                if player_state['fps'] > 0:
                    player_state['position'] = float(value) / player_state['fps']
            elif key == 'fps':
                player_state['fps'] = float(value)
            elif key == 'speed':
                player_state['speed'] = value + 'x'
        
        socketio.emit('player_state_update', player_state)
        time.sleep(0.1)  # Don't update too frequently

def play_media(filepath, seek_position=0):
    """Play media file using FFmpeg"""
    global ffmpeg_process, player_state
    
    # Stop any existing playback
    stop_playback()
    
    cmd = [
        'ffmpeg',
        '-re',  # Read input at native framerate
        '-ss', str(seek_position),  # Seek position
        '-i', filepath,  # Input file
        '-vf', 'format=yuv420p',  # Video format
        '-f', 'matroska',  # Output format
        '-c:v', 'h264',  # Video codec
        '-c:a', 'aac',  # Audio codec
        '-progress', 'pipe:2',  # Output progress to stderr
        'pipe:1'  # Output to pipe
    ]
    
    ffmpeg_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1
    )
    
    # Start progress monitoring thread
    progress_thread = threading.Thread(
        target=monitor_ffmpeg_progress,
        args=(ffmpeg_process,),
        daemon=True
    )
    progress_thread.start()
    
    player_state['is_playing'] = True
    player_state['position'] = seek_position
    update_player_state()

def stop_playback():
    """Stop media playback"""
    global ffmpeg_process, player_state
    if ffmpeg_process:
        try:
            ffmpeg_process.terminate()
            try:
                ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ffmpeg_process.kill()
                ffmpeg_process.wait()
        except Exception as e:
            logger.error(f"Error stopping FFmpeg process: {e}")
        finally:
            ffmpeg_process = None
    
    player_state['is_playing'] = False
    player_state['position'] = 0
    update_player_state()

def pause_playback():
    """Pause media playback using SIGSTOP/SIGCONT"""
    global ffmpeg_process, player_state
    if ffmpeg_process:
        try:
            if player_state['is_playing']:
                os.kill(ffmpeg_process.pid, signal.SIGSTOP)
                player_state['is_playing'] = False
            else:
                os.kill(ffmpeg_process.pid, signal.SIGCONT)
                player_state['is_playing'] = True
            update_player_state()
            return True
        except Exception as e:
            logger.error(f"Error pausing/resuming FFmpeg process: {e}")
            return False
    return False

def update_player_state():
    """Update and broadcast player state to all clients"""
    socketio.emit('player_state_update', player_state)

def cleanup_old_files():
    """Remove files older than 24 hours from the uploads directory"""
    try:
        current_time = datetime.now()
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            if current_time - file_modified > timedelta(hours=24):
                os.remove(filepath)
                logger.info(f"Removed old file: {filename}")
    except Exception as e:
        logger.error(f"Error cleaning up old files: {e}")

# Initialize the scheduler for cleanup
scheduler = BackgroundScheduler()
scheduler.add_job(func=cleanup_old_files, trigger="interval", hours=1)
scheduler.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/files', methods=['GET'])
def list_files():
    """List all files in the uploads directory"""
    files = []
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        files.append({
            'name': filename,
            'size': os.path.getsize(filepath),
            'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
        })
    return jsonify({'files': files})

@app.route('/select', methods=['POST'])
def select_file():
    """Select a file for playback"""
    try:
        data = request.get_json()
        if not data or 'filename' not in data:
            return jsonify({'error': 'No filename provided'}), 400

        filename = data['filename']
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404

        global current_media, player_state
        current_media = filepath
        player_state['current_file'] = filename
        player_state['duration'] = get_video_duration(filepath)
        player_state['position'] = 0
        player_state['is_playing'] = False
        player_state['fps'] = 0
        player_state['speed'] = '0x'
        
        update_player_state()
        return jsonify({'message': 'File selected successfully'})
    except Exception as e:
        logger.error(f"Error selecting file: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    """Upload a file"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Save file in chunks
        chunk_size = 8192
        with open(filepath, 'wb') as f:
            while True:
                chunk = file.stream.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
        
        global current_media, player_state
        current_media = filepath
        player_state['current_file'] = filename
        player_state['duration'] = get_video_duration(filepath)
        player_state['position'] = 0
        player_state['is_playing'] = False
        player_state['fps'] = 0
        player_state['speed'] = '0x'
        
        update_player_state()
        return jsonify({
            'status': 'success',
            'message': 'File uploaded successfully',
            'filename': filename
        })
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/play', methods=['POST'])
def play():
    """Start playback"""
    if current_media:
        play_media(current_media, player_state['position'])
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'No media selected'})

@app.route('/pause', methods=['POST'])
def pause():
    """Pause/resume playback"""
    if pause_playback():
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'No media playing'})

@app.route('/stop', methods=['POST'])
def stop():
    """Stop playback"""
    global current_media
    stop_playback()
    return jsonify({'status': 'success'})

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    emit('player_state_update', player_state)

@socketio.on('seek')
def handle_seek(data):
    """Handle seek request"""
    position = data.get('position', 0)
    if current_media:
        play_media(current_media, position)

if __name__ == '__main__':
    try:
        logger.info("Starting Flask application")
        socketio.run(app, host='0.0.0.0', port=5000)
    finally:
        logger.info("Shutting down scheduler")
        scheduler.shutdown()
