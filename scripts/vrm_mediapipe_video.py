#!/usr/bin/env python3
"""
A simple FastAPI server to serve the VRM Mediapipe viewer (new_index.html)
and accept video uploads to drive the animation remotely.
"""

import os
import uvicorn
from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from typing import List

app = FastAPI()

# Global variable to store connected clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# Paths
# This script is in scripts/, so we go up one level to root
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MEDIAPIPE_DIR = os.path.join(BASE_DIR, "mediapipe-avatar")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
VIDEO_PATH = os.path.join(CACHE_DIR, "current_video.mp4")

# Ensure cache dir
os.makedirs(CACHE_DIR, exist_ok=True)

@app.get("/")
async def get_index():
    """Serves the main HTML page."""
    index_path = os.path.join(MEDIAPIPE_DIR, "new_index.html")
    if not os.path.exists(index_path):
        return {"error": "new_index.html not found in mediapipe-avatar directory."}
    return FileResponse(index_path)

@app.get("/video_file")
async def get_video():
    """Serves the uploaded video file."""
    if os.path.exists(VIDEO_PATH):
        return FileResponse(VIDEO_PATH, media_type="video/mp4")
    return {"error": "No video uploaded yet"}

@app.post("/upload_video")
async def upload_video(file: UploadFile):
    """Accepts a video file upload and notifies connected clients."""
    print(f"Receiving video upload: {file.filename}")
    with open(VIDEO_PATH, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
    
    print("Video saved. Broadcasting to clients...")
    await manager.broadcast({"type": "video_uploaded"})
    return {"status": "success", "filename": file.filename}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

def main():
    print("Starting VRM MediaPipe Server...")
    print(f"Serving {os.path.join(MEDIAPIPE_DIR, 'new_index.html')}")
    print("Open http://localhost:8000 in your browser.")
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()