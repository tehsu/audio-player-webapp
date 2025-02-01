# Browser Audio Player

A Windows background application that can play audio files uploaded through a web browser.

## Prerequisites

- Python 3.7 or higher
- VLC media player installed on your system

## Installation

1. Install the required Python packages:
```bash
pip install -r requirements.txt
```

2. Make sure VLC media player is installed on your system.

## Usage

1. Run the application:
```bash
python app.py
```

2. Open your web browser and navigate to `http://127.0.0.1:5000`

3. Use the interface to:
   - Upload audio files (supported formats: MP3, WAV, OGG, M4A)
   - Play uploaded audio
   - Pause/Resume playback
   - Stop playback

## Features

- Simple web interface for audio file uploads
- Basic audio playback controls (play, pause, stop)
- Supports common audio formats
- Runs in the background
- Status feedback for all operations
