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
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('media_player.log')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    logger.info(f"Creating uploads directory: {app.config['UPLOAD_FOLDER']}")
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
    logger.debug(f"Getting duration for file: {filepath}")
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
        duration = float(data['format']['duration'])
        logger.debug(f"Duration: {duration} seconds")
        return duration
    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
        return 0

def monitor_ffmpeg_progress(process):
    """Monitor FFmpeg progress output"""
    global player_state
    logger.debug("Starting FFmpeg progress monitoring")
    
    progress_pattern = re.compile(r'(frame|fps|speed)=\s*([\d.]+)')
    last_update = time.time()
    update_interval = 0.1  # Update UI every 100ms
    
    while process.poll() is None:
        line = process.stderr.readline()
        if not line:
            continue
            
        matches = progress_pattern.finditer(line)
        state_changed = False
        for match in matches:
            key, value = match.groups()
            if key == 'frame':
                if player_state['fps'] > 0:
                    new_pos = float(value) / player_state['fps']
                    if abs(new_pos - player_state['position']) > 0.1:  # Only log significant changes
                        logger.debug(f"Position updated: {new_pos:.2f}s")
                        player_state['position'] = new_pos
                        state_changed = True
            elif key == 'fps':
                new_fps = float(value)
                if abs(new_fps - player_state['fps']) > 1:  # Only log significant changes
                    logger.debug(f"FPS updated: {new_fps:.1f}")
                    player_state['fps'] = new_fps
                    state_changed = True
            elif key == 'speed':
                new_speed = value + 'x'
                if new_speed != player_state['speed']:
                    logger.debug(f"Speed updated: {new_speed}")
                    player_state['speed'] = new_speed
                    state_changed = True
        
        # Throttle UI updates
        current_time = time.time()
        if state_changed and (current_time - last_update) >= update_interval:
            socketio.emit('player_state_update', player_state)
            last_update = current_time
    
    # Process has ended
    if process.poll() is not None:
        logger.info("FFmpeg process ended")
        player_state['is_playing'] = False
        player_state['position'] = 0
        player_state['fps'] = 0
        player_state['speed'] = '0x'
        update_player_state()

def play_media(filepath, seek_position=0):
    """Play media file using FFmpeg"""
    global ffmpeg_process, player_state
    logger.info(f"Starting playback: {filepath} at position {seek_position}s")
    
    # Stop any existing playback
    stop_playback()
    
    try:
        # Start FFmpeg process with video output to SDL window
        cmd = [
            'ffplay',  # Use ffplay instead of ffmpeg
            '-i', filepath,  # Input file
            '-ss', str(seek_position),  # Seek position
            '-x', '800',  # Window width
            '-y', '600',  # Window height
            '-window_title', 'Media Player',  # Window title
            '-stats',  # Show stats
            '-vf', 'format=yuv420p',  # Video format
            '-sync', 'audio',  # Sync to audio
            '-noborder'  # No window border
        ]
        logger.debug(f"FFplay command: {' '.join(cmd)}")
        
        # Start the process
        ffmpeg_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1
        )
        logger.debug(f"FFplay process started with PID: {ffmpeg_process.pid}")
        
        # Start progress monitoring thread
        progress_thread = threading.Thread(
            target=monitor_ffmpeg_progress,
            args=(ffmpeg_process,),
            daemon=True
        )
        progress_thread.start()
        logger.debug("Progress monitoring thread started")
        
        player_state['is_playing'] = True
        player_state['position'] = seek_position
        update_player_state()
        
        return True
    except Exception as e:
        logger.error(f"Error starting playback: {e}", exc_info=True)
        return False

def stop_playback():
    """Stop media playback"""
    global ffmpeg_process, player_state
    if ffmpeg_process:
        logger.info(f"Stopping playback (PID: {ffmpeg_process.pid})")
        try:
            # First try SIGTERM
            logger.debug("Sending SIGTERM to FFmpeg process")
            ffmpeg_process.terminate()
            try:
                ffmpeg_process.wait(timeout=5)
                logger.debug("FFmpeg process terminated gracefully")
            except subprocess.TimeoutExpired:
                # If SIGTERM doesn't work, use SIGKILL
                logger.warning("FFmpeg process did not terminate, sending SIGKILL")
                ffmpeg_process.kill()
                ffmpeg_process.wait()
                logger.debug("FFmpeg process killed")
        except Exception as e:
            logger.error(f"Error stopping FFmpeg process: {e}", exc_info=True)
        finally:
            ffmpeg_process = None
            
    player_state['is_playing'] = False
    player_state['position'] = 0
    player_state['fps'] = 0
    player_state['speed'] = '0x'
    update_player_state()

def pause_playback():
    """Pause/resume playback by sending SIGSTOP/SIGCONT"""
    global ffmpeg_process, player_state
    if ffmpeg_process:
        try:
            if player_state['is_playing']:
                # Send SIGSTOP to pause
                logger.info(f"Pausing playback (PID: {ffmpeg_process.pid})")
                os.kill(ffmpeg_process.pid, signal.SIGSTOP)
                player_state['is_playing'] = False
            else:
                # Send SIGCONT to resume
                logger.info(f"Resuming playback (PID: {ffmpeg_process.pid})")
                os.kill(ffmpeg_process.pid, signal.SIGCONT)
                player_state['is_playing'] = True
            update_player_state()
            return True
        except Exception as e:
            logger.error(f"Error pausing/resuming FFmpeg process: {e}", exc_info=True)
            return False
    logger.warning("No FFmpeg process to pause/resume")
    return False

def update_player_state():
    """Update and broadcast player state to all clients"""
    logger.debug(f"Broadcasting player state: {player_state}")
    socketio.emit('player_state_update', player_state)

def cleanup_old_files():
    """Remove files older than 24 hours from the uploads directory"""
    logger.info("Starting cleanup of old files")
    try:
        current_time = datetime.now()
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            if current_time - file_modified > timedelta(hours=24):
                logger.info(f"Removing old file: {filename}")
                os.remove(filepath)
    except Exception as e:
        logger.error(f"Error cleaning up old files: {e}", exc_info=True)

# Initialize the scheduler for cleanup
scheduler = BackgroundScheduler()
scheduler.add_job(func=cleanup_old_files, trigger="interval", hours=1)
scheduler.start()
logger.info("Cleanup scheduler started")

@app.route('/')
def index():
    logger.debug("Serving index page")
    return render_template('index.html')

@app.route('/files', methods=['GET'])
def list_files():
    """List all files in the uploads directory"""
    logger.debug("Listing uploaded files")
    files = []
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        files.append({
            'name': filename,
            'size': os.path.getsize(filepath),
            'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
        })
    logger.debug(f"Found {len(files)} files")
    return jsonify({'files': files})

@app.route('/select', methods=['POST'])
def select_file():
    """Select a file for playback"""
    try:
        data = request.get_json()
        if not data or 'filename' not in data:
            logger.warning("No filename provided in request")
            return jsonify({'error': 'No filename provided'}), 400

        filename = data['filename']
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        logger.info(f"Selecting file: {filename}")
        
        if not os.path.exists(filepath):
            logger.warning(f"File not found: {filepath}")
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
        logger.info(f"File selected successfully: {filename}")
        return jsonify({'message': 'File selected successfully'})
    except Exception as e:
        logger.error(f"Error selecting file: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    """Upload a file"""
    try:
        if 'file' not in request.files:
            logger.warning("No file in request")
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            logger.warning("Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        logger.info(f"Uploading file: {filename}")
        
        # Save file in chunks
        chunk_size = 8192
        total_size = 0
        with open(filepath, 'wb') as f:
            while True:
                chunk = file.stream.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                total_size += len(chunk)
        
        logger.info(f"File uploaded successfully: {filename} ({total_size} bytes)")
        
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
        logger.error(f"Error uploading file: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/play', methods=['POST'])
def play():
    """Start playback"""
    try:
        if not current_media:
            logger.warning("Attempted to play with no media selected")
            return jsonify({'status': 'error', 'message': 'No media selected'}), 400
        
        logger.info(f"Starting playback of: {current_media}")
        if play_media(current_media, player_state['position']):
            return jsonify({'status': 'success', 'message': 'Playback started'})
        else:
            logger.error("Failed to start playback")
            return jsonify({'status': 'error', 'message': 'Failed to start playback'}), 500
    except Exception as e:
        logger.error(f"Error in play route: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/pause', methods=['POST'])
def pause():
    """Pause/resume playback"""
    try:
        if pause_playback():
            action = 'paused' if not player_state['is_playing'] else 'resumed'
            logger.info(f"Playback {action}")
            return jsonify({'status': 'success', 'message': f'Playback {action}'})
        else:
            logger.warning("Attempted to pause with no media playing")
            return jsonify({'status': 'error', 'message': 'No media playing'}), 400
    except Exception as e:
        logger.error(f"Error in pause route: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/stop', methods=['POST'])
def stop():
    """Stop playback"""
    try:
        if not ffmpeg_process:
            logger.warning("Attempted to stop with no media playing")
            return jsonify({'status': 'error', 'message': 'No media playing'}), 400
        
        logger.info("Stopping playback")
        stop_playback()
        return jsonify({'status': 'success', 'message': 'Playback stopped'})
    except Exception as e:
        logger.error(f"Error in stop route: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info("Client connected")
    emit('player_state_update', player_state)

@socketio.on('seek')
def handle_seek(data):
    """Handle seek request"""
    try:
        position = data.get('position', 0)
        logger.info(f"Seek request to position: {position}s")
        if current_media and position >= 0:
            play_media(current_media, position)
    except Exception as e:
        logger.error(f"Error handling seek: {e}", exc_info=True)

if __name__ == '__main__':
    try:
        logger.info("Starting Flask application")
        socketio.run(app, host='0.0.0.0', port=5000)
    finally:
        logger.info("Shutting down scheduler")
        scheduler.shutdown()
