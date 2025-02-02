FROM python:3.11-slim

# # Install requests and bs4 for URL generation script
# RUN pip install requests beautifulsoup4

# # Add Blackmagic repository
# COPY scripts /tmp/scripts
# RUN chmod +x /tmp/scripts/get_blackmagic_url.py

# # Download and install Blackmagic Desktop Video
# RUN cd /tmp \
#             && wget --progress=dot:giga -O Blackmagic_Desktop_Video_Linux_14.4.1.tar.gz \
#                 "https://www.blackmagicdesign.com/support/download/5baba0af3eda41ee9cd0ec7349660d74/Linux" \
#     && tar xf Blackmagic_Desktop_Video_Linux_14.4.1.tar.gz \
#     && dpkg -i Blackmagic_Desktop_Video_Linux_14.4.1/deb/x86_64/desktopvideo_14.4.1_amd64.deb \
#     && rm -rf Blackmagic_Desktop_Video_Linux_14.4.1* /tmp/scripts

# Enable non-free repository
RUN echo "deb http://deb.debian.org/debian bookworm contrib non-free" >> /etc/apt/sources.list

# Install build dependencies for UxPlay
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    cmake \
    libavahi-compat-libdnssd-dev \
    libssl-dev \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    libplist-dev \
    libfdk-aac-dev \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Build and install UxPlay
RUN git clone https://github.com/FDH2/UxPlay.git && \
    cd UxPlay && \
    mkdir build && \
    cd build && \
    cmake .. && \
    make -j$(nproc) && \
    make install && \
    cd ../.. && \
    rm -rf UxPlay

# Install VLC and other dependencies
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
    v4l2loopback-dkms \
    v4l2loopback-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create a virtual display script with 4K resolution
#RUN echo '#!/bin/bash\nXvfb :99 -screen 0 3840x2160x24 &\nexport DISPLAY=:99\nsleep 1\necho "Starting Flask app..."\nexec python app.py' > /app/start.sh && \
#    chmod +x /app/start.sh

# Copy the start script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Expose ports for Flask and UxPlay
EXPOSE 5000 7000 7001 7100

# Set display environment variable
ENV DISPLAY=:99

# Command to run the application
CMD ["/app/start.sh"]
