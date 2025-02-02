#!/bin/bash

# Load v4l2loopback module
#modprobe v4l2loopback devices=1 video_nr=0 exclusive_caps=1 card_label="UxPlay"

# Start Xvfb with 4K resolution
Xvfb :99 -screen 0 3840x2160x24 &

# Wait for Xvfb to start
sleep 1

# Export display for X11 applications
export DISPLAY=:99

# Start Avahi daemon
avahi-daemon --no-chroot -D

# Wait for Avahi to start
sleep 2

# Start PulseAudio in daemon mode
# pulseaudio --start --log-target=syslog

# Start UxPlay with correct options
uxplay -s 3840x2160 -p &

# Start Flask app
echo "Starting Flask app..."
exec python app.py
