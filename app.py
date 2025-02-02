from flask import Flask, request, jsonify, send_from_directory, render_template
import vlc
import os
import threading
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.utils import secure_filename
import cv2
import numpy as np
import av
import subprocess

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
player = None
current_media = None
video_thread = None
stop_video = False

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def init_player():
    global player
    if player is None:
        instance = vlc.Instance()
        player = instance.media_player_new()

def is_video_file(filename):
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv'}
    return any(filename.lower().endswith(ext) for ext in video_extensions)

def play_video_blackmagic(filepath):
    global stop_video
    stop_video = False
    
    try:
        # Open video file using PyAV
        container = av.open(filepath)
        video = container.streams.video[0]
        
        # Set up Blackmagic output using decklink
        command = [
            'ffmpeg',
            '-re',  # Read input at native frame rate
            '-i', filepath,
            '-f', 'decklink',
            '-pix_fmt', 'uyvy422',
            'DeckLink Output'
        ]
        
        process = subprocess.Popen(command)
        
        while not stop_video:
            if process.poll() is not None:  # Process has ended
                break
            time.sleep(0.1)
        
        process.terminate()
        process.wait()
        
    except Exception as e:
        print(f"Error playing video: {str(e)}")
    finally:
        container.close()

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
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    output_device = request.form.get('output_device', 'default')
    
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
            instance = vlc.Instance()
            global current_media
            current_media = instance.media_new(filepath)
            player.set_media(current_media)
            
            return jsonify({
                'message': 'File uploaded successfully',
                'filename': filename,
                'is_video': is_video_file(filename),
                'output_device': output_device
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/play', methods=['POST'])
def play():
    global video_thread, stop_video
    
    if not current_media:
        return jsonify({'error': 'No media loaded'}), 400
    
    filepath = current_media.get_mrl().replace('file://', '')
    output_device = request.form.get('output_device', 'default')
    
    if is_video_file(filepath) and output_device == 'blackmagic':
        stop_video = True  # Stop any existing video playback
        if video_thread and video_thread.is_alive():
            video_thread.join()
        
        video_thread = threading.Thread(target=play_video_blackmagic, args=(filepath,))
        video_thread.start()
        return jsonify({'message': 'Started video playback on Blackmagic'})
    else:
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
    global stop_video
    
    if is_video_file(current_media.get_mrl()) and video_thread and video_thread.is_alive():
        stop_video = True
        video_thread.join()
        return jsonify({'message': 'Stopped video'})
    elif player:
        player.stop()
        return jsonify({'message': 'Stopped media'})
    return jsonify({'error': 'No media playing'}), 400

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000)
    finally:
        scheduler.shutdown()
