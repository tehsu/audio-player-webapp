#!/usr/bin/env python3
import requests
import re
import sys
import json

def get_download_url(version="14.4.1"):
    # Initial URL to get the token
    initial_url = f"https://www.blackmagicdesign.com/api/register/us/download/desktop-video-linux-{version}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Origin': 'https://www.blackmagicdesign.com',
        'Referer': 'https://www.blackmagicdesign.com/support'
    }

    # Required registration data
    data = {
        "firstName": "User",
        "lastName": "Name",
        "email": "user@example.com",
        "phone": "",
        "country": "us",
        "state": "",
        "city": "",
        "product": f"Desktop Video {version}",
        "platform": "Linux",
        "version": version,
        "serialNumber": "",
        "type": "Desktop Video",
        "accept": True
    }
    
    # Get download token
    try:
        response = requests.post(initial_url, headers=headers, json=data)
        if response.status_code != 200:
            print(f"Error getting download token: {response.status_code}", file=sys.stderr)
            print(f"Response: {response.text}", file=sys.stderr)
            sys.exit(1)
        
        download_url = response.json().get('downloadUrl', '')
        if not download_url:
            print("No download URL found in response", file=sys.stderr)
            print(f"Response: {response.text}", file=sys.stderr)
            sys.exit(1)
        print(download_url)
    except Exception as e:
        print(f"Error making request: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        get_download_url(sys.argv[1])
    else:
        get_download_url()
