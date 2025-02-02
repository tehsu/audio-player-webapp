#!/bin/bash

# Ensure XDG_RUNTIME_DIR exists and has correct permissions
mkdir -p $XDG_RUNTIME_DIR
chmod 700 $XDG_RUNTIME_DIR

# Start Xvfb with 4K resolution
Xvfb :99 -screen 0 3840x2160x24 &

# Wait for Xvfb to start
sleep 1

# Export display for X11 applications
export DISPLAY=:99

# Start PulseAudio in daemon mode
pulseaudio --start --log-target=syslog

echo "Virtual display initialized at 4K resolution (3840x2160)"
echo "Starting Flask app..."

# Start the Flask application
exec python app.py
