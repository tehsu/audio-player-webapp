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
    wget \
    gnupg \
    avahi-daemon \
    && rm -rf /var/lib/apt/lists/*

# Configure Avahi to work in containers
RUN sed -i 's/.*enable-dbus=.*/enable-dbus=no/' /etc/avahi/avahi-daemon.conf && \
    sed -i 's/.*disallow-other-stacks=.*/disallow-other-stacks=no/' /etc/avahi/avahi-daemon.conf

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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install NumPy first to ensure correct version
COPY requirements.txt .
RUN pip install numpy==1.24.3 && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Copy the start script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Expose ports for Flask and UxPlay
EXPOSE 5000 7000 7001 7100

# Set display environment variable
ENV DISPLAY=:99

# Command to run the application
CMD ["/app/start.sh"]
