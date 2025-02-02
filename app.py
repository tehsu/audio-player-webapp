from flask import Flask, request, jsonify, send_from_directory, render_template
import vlc
import os
import threading
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.utils import secure_filename

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
        # Initialize VLC with GPU acceleration
        instance = vlc.Instance('--vout=gpu')
        player = instance.media_player_new()
        # Enable hardware decoding
        player.set_hwdecoding(True)

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

@app.route('/list_files')
def list_files():
    """List all uploaded files with their information"""
    try:
        files = []
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            files.append(get_file_info(filename))
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
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
            instance = vlc.Instance('--vout=gpu')
            global current_media
            current_media = instance.media_new(filepath)
            
            # Enable hardware decoding for video files
            if is_video_file(filename):
                current_media.add_option('avcodec-hw=any')  # Try any available hardware decoder
            
            player.set_media(current_media)
            
            return jsonify({
                'message': 'File uploaded successfully',
                'filename': filename,
                'is_video': is_video_file(filename)
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/play', methods=['POST'])
def play():
    if not current_media:
        return jsonify({'error': 'No media loaded'}), 400
    
    player.play()
    return jsonify({'message': 'Started playback'})

@app.route('/pause', methods=['POST'])
def pause():
    if player:
        player.pause()
        return jsonify({'message': 'Media paused'})
    return jsonify({'error': 'No media playing'}), 400

@app.route('/stop', methods=['POST'])
def stop():
    if player:
        player.stop()
        return jsonify({'message': 'Stopped media'})
    return jsonify({'error': 'No media playing'}), 400

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000)
    finally:
        scheduler.shutdown()
