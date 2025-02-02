FROM python:3.11-slim

# Install VLC and PipeWire dependencies
RUN apt-get update && apt-get install -y \
    vlc \
    libvlc-dev \
    pipewire \
    pipewire-audio \
    libspa-0.2-modules \
    pipewire-alsa \
    pipewire-pulse \
    wireplumber \
    && rm -rf /var/lib/apt/lists/*

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
