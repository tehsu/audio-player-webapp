from flask import Flask, request, jsonify, send_from_directory, render_template
import vlc
import os
import threading
import time
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.utils import secure_filename

# Configure logging
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
player = None
current_media = None

# VLC instance options for virtual display
vlc_options = [
    '--no-xlib',  # Disable X11 video output
    '--vout=dummy',  # Use dummy video output
    '--aout=pulse',  # Use PulseAudio for audio output
    '--quiet',  # Reduce VLC's output
    '--no-video-title-show',  # Don't show the title
    '--no-snapshot-preview',  # Disable snapshot previews
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

def is_video_file(filename):
    """Check if the file is a video based on its extension"""
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    return any(filename.lower().endswith(ext) for ext in video_extensions)

def get_file_info(filename):
    """Get information about a file"""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    return {
        'name': filename,
        'size': os.path.getsize(filepath),
        'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
        'is_video': is_video_file(filename)
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
        global current_media
        current_media = instance.media_new(filepath)
        
        # Enable hardware decoding for video files
        if is_video_file(filename):
            logger.debug("Enabling hardware decoding for video file")
            current_media.add_option('avcodec-hw=any')
        
        logger.debug("Setting media in player")
        player.set_media(current_media)
        
        logger.info(f"File selected successfully: {filename}")
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
    return jsonify({'message': 'Started playback'})

@app.route('/pause', methods=['POST'])
def pause():
    if player:
        logger.info("Pausing playback")
        player.pause()
        return jsonify({'message': 'Media paused'})
    logger.error("No media playing")
    return jsonify({'error': 'No media playing'}), 400

@app.route('/stop', methods=['POST'])
def stop():
    if player:
        logger.info("Stopping playback")
        player.stop()
        return jsonify({'message': 'Stopped media'})
    logger.error("No media playing")
    return jsonify({'error': 'No media playing'}), 400

if __name__ == '__main__':
    try:
        logger.info("Starting Flask application")
        app.run(host='0.0.0.0', port=5000)
    finally:
        logger.info("Shutting down scheduler")
        scheduler.shutdown()
