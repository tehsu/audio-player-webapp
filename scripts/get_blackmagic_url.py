#!/usr/bin/env python3
import requests
import re
import sys
from bs4 import BeautifulSoup

def get_download_url(version="14.4.1"):
    # URL of the download page
    download_page = f"https://www.blackmagicdesign.com/support/download/5baba0af3eda41ee9cd0ec7349660d74/Linux"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    try:
        # Get the download page
        response = requests.get(download_page, headers=headers)
        if response.status_code != 200:
            print(f"Error accessing download page: {response.status_code}", file=sys.stderr)
            sys.exit(1)

        # Parse the page
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the Download Only link
        download_link = soup.find('a', text=re.compile('Download Only', re.IGNORECASE))
        if not download_link:
            # Try finding by class and checking text
            buttons = soup.find_all('a', {'class': 'button'})
            for button in buttons:
                if 'Download Only' in button.text:
                    download_link = button
                    break
                    
        if not download_link:
            print("Could not find Download Only link on page", file=sys.stderr)
            print("Page content:", response.text, file=sys.stderr)
            sys.exit(1)
            
        download_url = download_link.get('href')
        if not download_url:
            print("No download URL found in link", file=sys.stderr)
            sys.exit(1)
            
        # If URL is relative, make it absolute
        if not download_url.startswith('http'):
            download_url = f"https://www.blackmagicdesign.com{download_url}"
            
        print(download_url)
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        get_download_url(sys.argv[1])
    else:
        get_download_url()
