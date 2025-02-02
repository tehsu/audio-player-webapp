FROM python:3.11-slim

# Add Blackmagic repository
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && wget https://sw.blackmagicdesign.com/DesktopVideo/v12.4/Blackmagic_Desktop_Video_Linux_12.4.tar.gz \
    && tar xvf Blackmagic_Desktop_Video_Linux_12.4.tar.gz \
    && dpkg -i Blackmagic_Desktop_Video_Linux_12.4/deb/x86_64/desktopvideo_12.4_amd64.deb \
    && rm -rf Blackmagic_Desktop_Video_Linux_12.4*

# Install VLC and dependencies
RUN apt-get update && apt-get install -y \
    vlc \
    libvlc-dev \
    pulseaudio \
    pulseaudio-utils \
    mesa-va-drivers \
    mesa-vdpau-drivers \
    va-driver-all \
    vdpau-driver-all \
    xvfb \
    x11vnc \
    xauth \
    imagemagick \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create a virtual display script with 4K resolution
RUN echo '#!/bin/bash\nXvfb :99 -screen 0 3840x2160x24 &\nexport DISPLAY=:99\nsleep 1\necho "Starting Flask app..."\nexec python app.py' > /app/start.sh && \
    chmod +x /app/start.sh

# Expose port 5000 for Flask
EXPOSE 5000

# Set display environment variable
ENV DISPLAY=:99

# Command to run the application
CMD ["/app/start.sh"]
