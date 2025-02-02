from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_socketio import SocketIO, emit
import vlc
import os
import threading
import time
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.utils import secure_filename
from PIL import Image
import subprocess

# Configure logging
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

player = None
decklink_player = None  # Separate player for Blackmagic output
current_media = None
decklink_media = None
player_state = {
    'current_file': None,
    'duration': 0,
    'position': 0,
    'is_playing': False,
    'volume': 100,
    'decklink_active': False
}

# VLC instance options for virtual display
vlc_options = [
    '--no-xlib',  # Disable X11 video output
    '--vout=dummy',  # Use dummy video output
    '--aout=pulse',  # Use PulseAudio for audio output
    '--quiet',  # Reduce VLC's output
    '--no-video-title-show',  # Don't show the title
    '--no-snapshot-preview',  # Disable snapshot previews
]

# VLC instance options for Blackmagic output
decklink_options = [
    '--decklink-output-device=0',  # Use first Decklink device
    '--decklink-mode=1080p60',  # Set output mode to 1080p60
    '--decklink-audio-output=2',  # 2 channel audio output
    '--no-audio',  # Disable audio for Decklink output
    '--quiet',
    '--no-video-title-show'
]

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def init_player():
    global player
    if player is None:
        logger.info("Initializing new VLC player instance")
        try:
            # Initialize VLC with virtual display options
            instance = vlc.Instance(' '.join(vlc_options))
            player = instance.media_player_new()
            # Enable hardware decoding
            player.set_hwdecoding(True)
            logger.debug("VLC player initialized with virtual display and hardware decoding")
        except Exception as e:
            logger.error(f"Error initializing VLC player: {e}", exc_info=True)
            raise
    else:
        logger.debug("Using existing VLC player instance")

def init_decklink_player():
    global decklink_player
    if decklink_player is None:
        logger.info("Initializing new VLC player instance for Blackmagic output")
        try:
            # Initialize VLC with Decklink options
            instance = vlc.Instance(' '.join(decklink_options))
            decklink_player = instance.media_player_new()
            logger.debug("VLC player initialized with Blackmagic output")
        except Exception as e:
            logger.error(f"Error initializing Decklink player: {e}", exc_info=True)
            raise
    else:
        logger.debug("Using existing Decklink player instance")

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

def update_player_state():
    """Update and broadcast player state to all clients"""
    global player, player_state
    if player and current_media:
        player_state['position'] = player.get_time()
        player_state['duration'] = player.get_length()
        player_state['is_playing'] = player.is_playing()
        player_state['volume'] = player.audio_get_volume()
        socketio.emit('player_state_update', player_state)

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info("Client connected")
    emit('player_state_update', player_state)

@socketio.on('seek')
def handle_seek(data):
    """Handle seek request"""
    try:
        if player and current_media:
            position = int(data['position'])
            player.set_time(position)
            update_player_state()
    except Exception as e:
        logger.error(f"Error handling seek: {e}")

@socketio.on('set_volume')
def handle_volume(data):
    """Handle volume change request"""
    try:
        if player:
            volume = int(data['volume'])
            player.audio_set_volume(volume)
            update_player_state()
    except Exception as e:
        logger.error(f"Error handling volume change: {e}")

def start_state_update_thread():
    """Start thread to periodically update player state"""
    def update_loop():
        while True:
            if player and current_media:
                update_player_state()
            time.sleep(0.1)  # Update every 100ms
    
    thread = threading.Thread(target=update_loop, daemon=True)
    thread.start()

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

        init_player()
        
        # Create a new media instance
        logger.debug("Creating new VLC media instance")
        instance = vlc.Instance(' '.join(vlc_options))
        global current_media, player_state
        current_media = instance.media_new(filepath)
        
        # Enable hardware decoding for video files
        if is_video_file(filename):
            logger.debug("Enabling hardware decoding for video file")
            current_media.add_option('avcodec-hw=any')
        
        logger.debug("Setting media in player")
        player.set_media(current_media)
        
        # Update player state
        player_state['current_file'] = filename
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
            
            init_player()
            
            # Create a new media instance
            logger.debug("Creating new VLC media instance")
            instance = vlc.Instance(' '.join(vlc_options))
            global current_media
            current_media = instance.media_new(filepath)
            
            # Enable hardware decoding for video files
            if is_video_file(filename):
                logger.debug("Enabling hardware decoding for video file")
                current_media.add_option('avcodec-hw=any')
            
            logger.debug("Setting media in player")
            player.set_media(current_media)
            
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
    if not current_media:
        logger.error("No media loaded")
        return jsonify({'error': 'No media loaded'}), 400
    
    logger.info("Starting playback")
    player.play()
    update_player_state()
    return jsonify({'message': 'Started playback'})

@app.route('/pause', methods=['POST'])
def pause():
    if player:
        logger.info("Pausing playback")
        player.pause()
        update_player_state()
        return jsonify({'message': 'Media paused'})
    logger.error("No media playing")
    return jsonify({'error': 'No media playing'}), 400

@app.route('/stop', methods=['POST'])
def stop():
    if player:
        logger.info("Stopping playback")
        player.stop()
        update_player_state()
        return jsonify({'message': 'Stopped media'})
    logger.error("No media playing")
    return jsonify({'error': 'No media playing'}), 400

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

        init_decklink_player()

        # Handle different file types
        if is_image_file(filename):
            logger.info(f"Converting image to video for Blackmagic output: {filename}")
            video_path = convert_image_to_video(filepath)
            if not video_path:
                return jsonify({'error': 'Failed to convert image'}), 500
            filepath = video_path

        # Create media for Decklink output
        instance = vlc.Instance(' '.join(decklink_options))
        global decklink_media
        decklink_media = instance.media_new(filepath)
        decklink_player.set_media(decklink_media)
        
        # Start playback
        decklink_player.play()
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
        if decklink_player:
            decklink_player.stop()
            player_state['decklink_active'] = False
            return jsonify({'message': 'Stopped Blackmagic output'})
        return jsonify({'error': 'No Blackmagic output active'}), 400
    except Exception as e:
        logger.error(f"Error stopping Blackmagic output: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    try:
        logger.info("Starting Flask application")
        start_state_update_thread()
        socketio.run(app, host='0.0.0.0', port=5000)
    finally:
        logger.info("Shutting down scheduler")
        scheduler.shutdown()
