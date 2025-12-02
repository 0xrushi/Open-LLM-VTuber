#!/usr/bin/env python3
"""
Test script to upload a video file to the vrm_mediapipe_video.py server.
Usage: python test_video_upload.py <video_file_path> [server_url]
"""

import requests
import sys
import os

DEFAULT_URL = "http://localhost:8000/upload_video"

def upload_video(file_path, url=DEFAULT_URL):
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    print(f"Uploading '{file_path}' to {url}...")
    try:
        with open(file_path, "rb") as f:
            files = {"file": f}
            response = requests.post(url, files=files)
            
        if response.status_code == 200:
            print("Success! Video uploaded.")
            print(f"Server response: {response.text}")
        else:
            print(f"Failed with status code: {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to server at {url}.")
        print("Make sure 'scripts/vrm_mediapipe_video.py' is running.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <video_file_path> [server_url]")
        sys.exit(1)
    
    video_path = sys.argv[1]
    target_url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_URL
    
    upload_video(video_path, target_url)
