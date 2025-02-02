from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_socketio import SocketIO, emit
import os
import threading
import time
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.utils import secure_filename
from PIL import Image
import subprocess
import cv2
import json
import signal

# Configure logging
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

ffmpeg_process = None
decklink_process = None
airplay_capture = None
current_media = None
decklink_media = None
player_state = {
    'current_file': None,
    'duration': 0,
    'position': 0,
    'is_playing': False,
    'volume': 100,
    'decklink_active': False,
    'airplay_active': False
}

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def get_video_duration(filepath):
    """Get video duration using FFprobe"""
    cmd = [
        'ffprobe', 
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'json',
        filepath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except:
        return 0

def play_media(filepath, seek_position=0):
    """Play media file using FFmpeg"""
    global ffmpeg_process, player_state
    
    if ffmpeg_process:
        ffmpeg_process.terminate()
        ffmpeg_process.wait()
        
    volume = player_state['volume'] / 100.0
    
    cmd = [
        'ffmpeg',
        '-re',  # Read input at native framerate
        '-ss', str(seek_position),  # Seek position
        '-i', filepath,  # Input file
        '-vf', 'format=yuv420p',  # Video format
        '-f', 'matroska',  # Output format
        '-c:v', 'h264',  # Video codec
        '-c:a', 'aac',  # Audio codec
        '-af', f'volume={volume}',  # Volume control
        'pipe:1'  # Output to pipe
    ]
    
    if player_state['decklink_active']:
        cmd = [
            'ffmpeg',
            '-re',
            '-ss', str(seek_position),
            '-i', filepath,
            '-vf', 'format=uyvy422',
            '-f', 'decklink',
            '-c:v', 'rawvideo',
            '-c:a', 'pcm_s16le',
            '-af', f'volume={volume}',
            'DeckLink Output'
        ]
    
    ffmpeg_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE if not player_state['decklink_active'] else None,
        stderr=subprocess.PIPE
    )
    
    player_state['is_playing'] = True
    player_state['position'] = seek_position
    update_player_state()

def stop_playback():
    """Stop media playback"""
    global ffmpeg_process, player_state
    if ffmpeg_process:
        try:
            # Send SIGTERM to FFmpeg process
            ffmpeg_process.terminate()
            # Wait up to 5 seconds for process to terminate
            try:
                ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # If FFmpeg hasn't terminated after 5 seconds, force kill it
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
                # Send SIGSTOP to pause
                os.kill(ffmpeg_process.pid, signal.SIGSTOP)
                player_state['is_playing'] = False
            else:
                # Send SIGCONT to resume
                os.kill(ffmpeg_process.pid, signal.SIGCONT)
                player_state['is_playing'] = True
            update_player_state()
            return True
        except Exception as e:
            logger.error(f"Error pausing/resuming FFmpeg process: {e}")
            return False
    return False

def set_volume(volume):
    """Set playback volume"""
    global player_state
    player_state['volume'] = max(0, min(100, volume))
    if player_state['is_playing'] and current_media:
        play_media(current_media, player_state['position'])

def seek(position):
    """Seek to position in media"""
    global player_state
    if current_media:
        player_state['position'] = position
        play_media(current_media, position)

def update_player_state():
    """Update and broadcast player state to all clients"""
    global player_state
    socketio.emit('player_state_update', player_state)

def is_video_file(filename):
    """Check if the file is a video based on its extension"""
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    return any(filename.lower().endswith(ext) for ext in video_extensions)

def is_image_file(filename):
    """Check if the file is an image based on its extension"""
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
    return any(filename.lower().endswith(ext) for ext in image_extensions)

def convert_image_to_video(image_path):
    """Convert a static image to a video file for Blackmagic output"""
    output_path = image_path + '.mp4'
    try:
        # Create a 10-second video from the image
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1',
            '-i', image_path,
            '-c:v', 'libx264',
            '-t', '10',
            '-pix_fmt', 'yuv420p',
            '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
            output_path
        ]
        subprocess.run(cmd, check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"Error converting image to video: {e}")
        return None

def get_file_info(filename):
    """Get information about a file"""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    return {
        'name': filename,
        'size': os.path.getsize(filepath),
        'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
        'is_video': is_video_file(filename),
        'is_image': is_image_file(filename)
    }

def cleanup_old_files():
    """Remove files older than 24 hours from the uploads directory"""
    cutoff_time = datetime.now() - timedelta(hours=24)
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
        if file_modified < cutoff_time:
            try:
                os.remove(file_path)
                logger.info(f"Removed old file: {filename}")
            except Exception as e:
                logger.error(f"Error removing file {filename}: {e}")

# Initialize the scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=cleanup_old_files, trigger="interval", hours=1)
scheduler.start()

def init_airplay_capture():
    """Initialize video capture from UxPlay v4l2loopback device"""
    global airplay_capture
    try:
        airplay_capture = cv2.VideoCapture('/dev/video0')
        airplay_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
        airplay_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
        airplay_capture.set(cv2.CAP_PROP_FPS, 60)
        logger.info("Initialized AirPlay video capture")
        return True
    except Exception as e:
        logger.error(f"Error initializing AirPlay capture: {e}")
        return False

def start_airplay_capture():
    """Start capturing from UxPlay and output to Blackmagic"""
    try:
        if not init_airplay_capture():
            return False

        # Create a media instance for the v4l2loopback device
        cmd = [
            'ffmpeg',
            '-re',
            '-f', 'v4l2',
            '-framerate', '60',
            '-video_size', '3840x2160',
            '-i', '/dev/video0',
            '-vf', 'format=uyvy422',
            '-f', 'decklink',
            '-c:v', 'rawvideo',
            '-c:a', 'pcm_s16le',
            'DeckLink Output'
        ]
        
        global decklink_process
        decklink_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        player_state['decklink_active'] = True
        player_state['airplay_active'] = True
        
        logger.info("Started AirPlay capture and Blackmagic output")
        return True
    except Exception as e:
        logger.error(f"Error starting AirPlay capture: {e}")
        return False

def stop_airplay_capture():
    """Stop AirPlay capture and Blackmagic output"""
    try:
        global airplay_capture, decklink_process
        if airplay_capture:
            airplay_capture.release()
            airplay_capture = None
        
        if decklink_process:
            decklink_process.terminate()
            decklink_process.wait()
        
        player_state['decklink_active'] = False
        player_state['airplay_active'] = False
        
        logger.info("Stopped AirPlay capture and Blackmagic output")
        return True
    except Exception as e:
        logger.error(f"Error stopping AirPlay capture: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/list_files')
def list_files():
    """List all uploaded files with their information"""
    try:
        logger.debug("Getting list of uploaded files")
        files = []
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            files.append(get_file_info(filename))
        logger.info(f"Found {len(files)} files")
        return jsonify({'files': files})
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/select_file', methods=['POST'])
def select_file():
    """Select an existing file for playback"""
    try:
        logger.debug("Received file selection request")
        data = request.get_json()
        if not data or 'filename' not in data:
            logger.error("No filename provided in request")
            return jsonify({'error': 'No filename provided'}), 400

        filename = data['filename']
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        logger.info(f"Selecting file: {filename}")
        
        if not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            return jsonify({'error': 'File not found'}), 404

        global current_media, player_state
        current_media = filepath
        player_state['current_file'] = filename
        player_state['duration'] = get_video_duration(filepath)
        player_state['position'] = 0
        player_state['is_playing'] = False
        
        logger.info(f"File selected successfully: {filename}")
        socketio.emit('player_state_update', player_state)
        
        return jsonify({
            'message': 'File selected successfully',
            'filename': filename,
            'is_video': is_video_file(filename)
        })
    except Exception as e:
        logger.error(f"Error selecting file: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        logger.error("No file part in request")
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        logger.error("No selected file in request")
        return jsonify({'error': 'No selected file'}), 400

    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        logger.info(f"Uploading file: {filename}")
        
        # Stream the file in chunks to handle large files
        try:
            chunk_size = 8192  # 8KB chunks
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
            
            logger.info(f"File uploaded successfully: {filename}")
            return jsonify({
                'message': 'File uploaded successfully',
                'filename': filename,
                'is_video': is_video_file(filename)
            })
        except Exception as e:
            logger.error(f"Error uploading file: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

@app.route('/play', methods=['POST'])
def play():
    global current_media, player_state
    if current_media:
        play_media(current_media, player_state['position'])
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'No media selected'})

@app.route('/pause', methods=['POST'])
def pause():
    if pause_playback():
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'No media playing'})

@app.route('/stop', methods=['POST'])
def stop():
    global current_media
    stop_playback()
    current_media = None
    return jsonify({'status': 'success'})

@app.route('/output_to_decklink', methods=['POST'])
def output_to_decklink():
    """Output current media to Blackmagic device"""
    try:
        data = request.get_json()
        if not data or 'filename' not in data:
            return jsonify({'error': 'No filename provided'}), 400

        filename = data['filename']
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404

        # Handle different file types
        if is_image_file(filename):
            logger.info(f"Converting image to video for Blackmagic output: {filename}")
            video_path = convert_image_to_video(filepath)
            if not video_path:
                return jsonify({'error': 'Failed to convert image'}), 500
            filepath = video_path

        # Create media for Decklink output
        cmd = [
            'ffmpeg',
            '-re',
            '-i', filepath,
            '-vf', 'format=uyvy422',
            '-f', 'decklink',
            '-c:v', 'rawvideo',
            '-c:a', 'pcm_s16le',
            'DeckLink Output'
        ]
        
        global decklink_process
        decklink_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        player_state['decklink_active'] = True
        
        return jsonify({
            'message': 'Started Blackmagic output',
            'filename': filename
        })
    except Exception as e:
        logger.error(f"Error starting Blackmagic output: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/stop_decklink', methods=['POST'])
def stop_decklink():
    """Stop Blackmagic output"""
    try:
        global decklink_process
        if decklink_process:
            decklink_process.terminate()
            decklink_process.wait()
            decklink_process = None
        player_state['decklink_active'] = False
        return jsonify({'message': 'Stopped Blackmagic output'})
    except Exception as e:
        logger.error(f"Error stopping Blackmagic output: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/start_airplay', methods=['POST'])
def start_airplay():
    """Start AirPlay capture and output to Blackmagic"""
    try:
        if start_airplay_capture():
            return jsonify({'message': 'Started AirPlay capture'})
        return jsonify({'error': 'Failed to start AirPlay capture'}), 500
    except Exception as e:
        logger.error(f"Error in start_airplay route: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stop_airplay', methods=['POST'])
def stop_airplay():
    """Stop AirPlay capture and Blackmagic output"""
    try:
        if stop_airplay_capture():
            return jsonify({'message': 'Stopped AirPlay capture'})
        return jsonify({'error': 'Failed to stop AirPlay capture'}), 500
    except Exception as e:
        logger.error(f"Error in stop_airplay route: {e}")
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info("Client connected")
    emit('player_state_update', player_state)

@socketio.on('seek')
def handle_seek(data):
    position = data.get('position', 0)
    seek(position)

@socketio.on('volume')
def handle_volume(data):
    volume = data.get('volume', 100)
    set_volume(volume)

if __name__ == '__main__':
    try:
        logger.info("Starting Flask application")
        socketio.run(app, host='0.0.0.0', port=5000)
    finally:
        logger.info("Shutting down scheduler")
        scheduler.shutdown()
