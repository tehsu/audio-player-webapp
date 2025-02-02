#!/usr/bin/env python3
import requests
import re
import sys

def get_download_url(version="14.4.1"):
    # Initial URL to get the token
    initial_url = f"https://www.blackmagicdesign.com/api/register/us/download/desktop-video-linux-{version}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    # Get download token
    response = requests.post(initial_url, headers=headers)
    if response.status_code != 200:
        print(f"Error getting download token: {response.status_code}", file=sys.stderr)
        sys.exit(1)
    
    try:
        download_url = response.json().get('downloadUrl', '')
        if not download_url:
            print("No download URL found in response", file=sys.stderr)
            sys.exit(1)
        print(download_url)
    except Exception as e:
        print(f"Error parsing response: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        get_download_url(sys.argv[1])
    else:
        get_download_url()
