FROM python:3.11-slim

# Install VLC, PipeWire, and video dependencies
RUN apt-get update && apt-get install -y \
    vlc \
    libvlc-dev \
    pipewire \
    pipewire-audio \
    libspa-0.2-modules \
    pipewire-alsa \
    pipewire-pulse \
    wireplumber \
    wget \
    unzip \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Blackmagic Desktop Video SDK
RUN wget https://sw.blackmagicdesign.com/DesktopVideo/v12.5/Blackmagic_Desktop_Video_Linux_12.5.tar.gz && \
    tar xvfz Blackmagic_Desktop_Video_Linux_12.5.tar.gz && \
    cd Blackmagic_Desktop_Video_Linux_12.5/deb/x86_64 && \
    dpkg -i desktopvideo_12.5_amd64.deb && \
    dpkg -i desktopvideo-dev_12.5_amd64.deb && \
    cd ../../.. && \
    rm -rf Blackmagic_Desktop_Video_Linux_12.5* 

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose port 5000 for Flask
EXPOSE 5000

# Command to run the application
CMD ["python", "app.py"]
