#!/bin/bash

# Ensure XDG_RUNTIME_DIR exists and has correct permissions
mkdir -p $XDG_RUNTIME_DIR
chmod 700 $XDG_RUNTIME_DIR

# Load v4l2loopback module
modprobe v4l2loopback devices=1 video_nr=0 exclusive_caps=1 card_label="UxPlay"

# Start Xvfb with 4K resolution
Xvfb :99 -screen 0 3840x2160x24 &

# Wait for Xvfb to start
sleep 1

# Export display for X11 applications
export DISPLAY=:99

# Start PulseAudio in daemon mode
pulseaudio --start --log-target=syslog

# Start UxPlay with output to both virtual display and v4l2loopback
uxplay --screen $DISPLAY --v4l2 /dev/video0 --fps 60 --width 3840 --height 2160 --pixfmt nv12 &

echo "Virtual display initialized at 4K resolution (3840x2160)"
echo "UxPlay started and ready for AirPlay connections"
echo "Starting Flask app..."

# Start the Flask application
exec python app.py
