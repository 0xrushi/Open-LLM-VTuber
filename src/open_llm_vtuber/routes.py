import asyncio
import os
import json
import time
from urllib.request import urlopen
from uuid import uuid4
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, WebSocket, UploadFile, File, Response, HTTPException, Request, Query
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, FileResponse, RedirectResponse
from starlette.websockets import WebSocketDisconnect
from loguru import logger
from .service_context import ServiceContext
from .websocket_handler import WebSocketHandler, WSMessage
from .proxy_handler import ProxyHandler
from .config_manager.utils import scan_config_alts_directory_rich

# Server-side store: client_ip → {config filename, expiry timestamp}
# Avoids relying on browser cookie forwarding to WebSocket upgrade requests.
_pending_profile_store: dict = {}


class RotationPayload(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: Optional[float] = Field(default=None, description="Quaternion W component. When omitted, XYZ is treated as Euler angles.")


class PositionPayload(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None


class VRMBonePayload(BaseModel):
    name: str = Field(..., description="Humanoid bone name (e.g. RightLowerArm)")
    rotation: Optional[RotationPayload] = None
    position: Optional[PositionPayload] = None


class VRMMotionPayload(BaseModel):
    bones: List[VRMBonePayload] = Field(..., description="List of bone poses to apply immediately")
    target_client_uid: Optional[str] = Field(
        default=None,
        description="Optional client UID to deliver the pose to. When omitted, the pose is broadcast.",
    )
    worldQuaternion: Optional[bool] = Field(
        default=None,
        description=(
            "When true, treat each bone.rotation quaternion as a world-space "
            "orientation and convert it to local space on the client. "
            "When omitted or false, rotations are interpreted as local (Euler XYZ "
            "if w is absent, quaternion otherwise)."
        ),
    )


def init_vrm_routes(ws_handler: WebSocketHandler) -> APIRouter:
    """
    Create and return routes responsible for VRM-specific HTTP and WebSocket APIs.

    Provides:
        - POST /vrm/motion: One-shot bone pose updates
        - WebSocket /vrm/motion-ws: Streaming bone pose updates for continuous animation
    """

    router = APIRouter()

    @router.post("/vrm/motion")
    async def push_vrm_motion(payload: VRMMotionPayload):
        """
        Apply VRM bone poses immediately via HTTP POST.

        Args:
            payload: VRMMotionPayload containing bones list and optional target_client_uid.

        Returns:
            dict: Number of clients the motion was delivered to.

        Raises:
            HTTPException: 400 if no bones provided, 404 if no active clients.
        """
        if not payload.bones:
            raise HTTPException(status_code=400, detail="At least one bone pose is required")

        message = {
            "type": "vrm-motion",
            "bones": [bone.model_dump(exclude_none=True) for bone in payload.bones],
        }
        if payload.worldQuaternion is not None:
            message["worldQuaternion"] = payload.worldQuaternion
        delivered = await ws_handler.push_vrm_motion(
            message,
            target_client_uid=payload.target_client_uid,
        )
        if delivered == 0:
            raise HTTPException(status_code=404, detail="No active clients available for this request")
        return {"delivered": delivered, "target_client_uid": payload.target_client_uid}

    @router.websocket("/vrm/motion-ws")
    async def vrm_motion_stream(websocket: WebSocket):
        """
        WebSocket endpoint for streaming VRM bone poses.

        Accepts JSON messages with the following structure:
        {
            "bones": [
                {"name": "rightLowerArm", "rotation": {"x": -1.5708, "y": 0, "z": 0}},
                ...
            ],
            "target_client_uid": "optional-client-id"
        }

        Each message is broadcast to connected frontend clients displaying VRM models.
        This is more efficient than REST for continuous animations (30-60 FPS).
        """
        await websocket.accept()
        logger.info("VRM motion streaming WebSocket connection established")

        try:
            while True:
                data = await websocket.receive_json()

                # Validate bones data
                bones = data.get("bones")
                if not bones or not isinstance(bones, list):
                    await websocket.send_json({
                        "status": "error",
                        "message": "Invalid payload: 'bones' array is required"
                    })
                    continue

                # Build the motion message
                message = {
                    "type": "vrm-motion",
                    "bones": bones,
                }

                world_quaternion_flag = data.get("worldQuaternion")
                if isinstance(world_quaternion_flag, bool):
                    message["worldQuaternion"] = world_quaternion_flag

                # Broadcast to frontend clients
                target_client_uid = data.get("target_client_uid")
                delivered = await ws_handler.push_vrm_motion(
                    message,
                    target_client_uid=target_client_uid,
                )

                # Send acknowledgment back to the streaming client
                await websocket.send_json({
                    "status": "ok",
                    "delivered": delivered,
                })

        except WebSocketDisconnect:
            logger.info("VRM motion streaming WebSocket client disconnected")
        except Exception as e:
            logger.error(f"Error in VRM motion streaming WebSocket: {e}")
            await websocket.close()

    return router



def init_config_routes() -> APIRouter:
    """
    Create and return routes responsible for configuration-related HTTP APIs.

    Currently all configuration management is handled via WebSocket messages,
    so this router is intentionally empty and serves as a placeholder hook
    for future HTTP config endpoints.
    """
    router = APIRouter()
    return router


def init_client_ws_route(ws_handler: WebSocketHandler) -> APIRouter:
    """
    Create and return API routes for handling the `/client-ws` WebSocket connections.

    Args:
        default_context_cache: Default service context cache for new sessions.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()

    @router.websocket("/client-ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for client connections"""
        await websocket.accept()
        client_uid = str(uuid4())

        try:
            await ws_handler.handle_new_connection(websocket, client_uid)
            await ws_handler.handle_websocket_communication(websocket, client_uid)
        except WebSocketDisconnect:
            await ws_handler.handle_disconnect(client_uid)
        except Exception as e:
            logger.error(f"Error in WebSocket connection: {e}")
            await ws_handler.handle_disconnect(client_uid)
            raise

    return router


def init_proxy_route(server_url: str) -> APIRouter:
    """
    Create and return API routes for handling proxy connections.

    Args:
        server_url: The WebSocket URL of the actual server

    Returns:
        APIRouter: Configured router with proxy WebSocket endpoint
    """
    router = APIRouter()
    proxy_handler = ProxyHandler(server_url)

    @router.websocket("/proxy-ws")
    async def proxy_endpoint(websocket: WebSocket):
        """WebSocket endpoint for proxy connections"""
        try:
            await proxy_handler.handle_client_connection(websocket)
        except Exception as e:
            logger.error(f"Error in proxy connection: {e}")
            raise

    return router


def init_webtool_routes(default_context_cache: ServiceContext) -> APIRouter:
    """
    Create and return API routes for handling web tool interactions.

    Args:
        default_context_cache: Default service context cache for new sessions.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()

    @router.get("/web-tool")
    async def web_tool_redirect():
        """Redirect /web-tool to /web_tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    @router.get("/web_tool")
    async def web_tool_redirect_alt():
        """Redirect /web_tool to /web_tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    @router.get("/live2d-models/info")
    async def get_live2d_folder_info():
        """Get information about available Live2D models"""
        live2d_dir = "live2d-models"
        if not os.path.exists(live2d_dir):
            return JSONResponse(
                {"error": "Live2D models directory not found"}, status_code=404
            )

        valid_characters = []
        supported_extensions = [".png", ".jpg", ".jpeg"]

        for entry in os.scandir(live2d_dir):
            if entry.is_dir():
                folder_name = entry.name.replace("\\", "/")
                model3_file = os.path.join(
                    live2d_dir, folder_name, f"{folder_name}.model3.json"
                ).replace("\\", "/")

                if os.path.isfile(model3_file):
                    # Find avatar file if it exists
                    avatar_file = None
                    for ext in supported_extensions:
                        avatar_path = os.path.join(
                            live2d_dir, folder_name, f"{folder_name}{ext}"
                        )
                        if os.path.isfile(avatar_path):
                            avatar_file = avatar_path.replace("\\", "/")
                            break

                    valid_characters.append(
                        {
                            "name": folder_name,
                            "avatar": avatar_file,
                            "model_path": model3_file,
                        }
                    )
        return JSONResponse(
            {
                "type": "live2d-models/info",
                "count": len(valid_characters),
                "characters": valid_characters,
            }
        )

    @router.post("/asr")
    async def transcribe_audio(file: UploadFile = File(...)):
        """
        Endpoint for transcribing audio using the ASR engine
        """
        logger.info(f"Received audio file for transcription: {file.filename}")

        try:
            contents = await file.read()

            # Validate minimum file size
            if len(contents) < 44:  # Minimum WAV header size
                raise ValueError("Invalid WAV file: File too small")

            # Decode the WAV header and get actual audio data
            wav_header_size = 44  # Standard WAV header size
            audio_data = contents[wav_header_size:]

            # Validate audio data size
            if len(audio_data) % 2 != 0:
                raise ValueError("Invalid audio data: Buffer size must be even")

            # Convert to 16-bit PCM samples to float32
            try:
                audio_array = (
                    np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )
            except ValueError as e:
                raise ValueError(
                    f"Audio format error: {str(e)}. Please ensure the file is 16-bit PCM WAV format."
                )

            # Validate audio data
            if len(audio_array) == 0:
                raise ValueError("Empty audio data")

            text = await default_context_cache.asr_engine.async_transcribe_np(
                audio_array
            )
            logger.info(f"Transcription result: {text}")
            return {"text": text}

        except ValueError as e:
            logger.error(f"Audio format error: {e}")
            return Response(
                content=json.dumps({"error": str(e)}),
                status_code=400,
                media_type="application/json",
            )
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            return Response(
                content=json.dumps(
                    {"error": "Internal server error during transcription"}
                ),
                status_code=500,
                media_type="application/json",
            )

    @router.get("/api/infra/redis-health")
    async def redis_health():
        """Health check for Redis connectivity used by async tool queues."""
        try:
            from redis import Redis

            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            r = Redis.from_url(redis_url)
            ok = bool(r.ping())
            if ok:
                return JSONResponse({"ok": True, "redis_url": redis_url})
            return JSONResponse(
                {"ok": False, "error": "Redis ping failed", "redis_url": redis_url},
                status_code=503,
            )
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=503,
            )

    @router.get("/api/infra/workers-health")
    async def workers_health():
        """Health check for RQ workers consuming async tool queues."""
        try:
            from redis import Redis
            from rq import Worker

            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            heartbeat_ttl_sec = int(os.environ.get("RQ_WORKER_HEARTBEAT_TTL", "120"))
            required_queues = {"obsidian-tools"}
            r = Redis.from_url(redis_url)

            workers = Worker.all(connection=r)
            alive_workers = []
            covered_queues = set()
            now = time.time()

            for w in workers:
                # Worker heartbeat is considered fresh if seen recently.
                raw_last_hb = getattr(w, "last_heartbeat", None)
                if isinstance(raw_last_hb, datetime):
                    last_hb = raw_last_hb.timestamp()
                elif raw_last_hb is None:
                    last_hb = 0.0
                else:
                    last_hb = float(raw_last_hb)
                is_alive = (now - last_hb) <= heartbeat_ttl_sec if last_hb else False
                queue_names = [q.name for q in getattr(w, "queues", [])]
                if is_alive:
                    covered_queues.update(queue_names)
                    alive_workers.append(
                        {
                            "name": getattr(w, "name", "unknown"),
                            "queues": queue_names,
                            "last_heartbeat": last_hb,
                        }
                    )

            missing_queues = sorted(required_queues - covered_queues)
            ok = len(missing_queues) == 0 and len(alive_workers) > 0

            payload = {
                "ok": ok,
                "heartbeat_ttl_sec": heartbeat_ttl_sec,
                "required_queues": sorted(required_queues),
                "covered_queues": sorted(covered_queues),
                "missing_queues": missing_queues,
                "alive_worker_count": len(alive_workers),
                "workers": alive_workers,
            }
            if ok:
                return JSONResponse(payload)
            return JSONResponse(payload, status_code=503)
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=503,
            )

    @router.get("/api/infra/tts-health")
    async def tts_health():
        """Report currently configured TTS mode/endpoint for connectivity diagnostics."""
        try:
            tts_cfg = default_context_cache.character_config.tts_config
            tts_model = getattr(tts_cfg, "tts_model", None)
            if not tts_model:
                return JSONResponse(
                    {"ok": False, "error": "No active TTS model configured"},
                    status_code=503,
                )

            provider_cfg = getattr(tts_cfg, tts_model.lower(), None)
            endpoint = getattr(provider_cfg, "api_url", None) if provider_cfg else None
            mode = "remote" if endpoint and endpoint.startswith("http") else "local"

            return JSONResponse(
                {
                    "ok": True,
                    "tts_model": tts_model,
                    "mode": mode,
                    "endpoint": endpoint,
                    "message": (
                        "Active TTS is remote API based."
                        if mode == "remote"
                        else "Active TTS is local/in-process."
                    ),
                }
            )
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc)},
                status_code=503,
            )

    @router.websocket("/tts-ws")
    async def tts_endpoint(websocket: WebSocket):
        """WebSocket endpoint for TTS generation"""
        await websocket.accept()
        logger.info("TTS WebSocket connection established")

        try:
            while True:
                data = await websocket.receive_json()
                text = data.get("text")
                if not text:
                    continue

                logger.info(f"Received text for TTS: {text}")

                # Split text into sentences
                sentences = [s.strip() for s in text.split(".") if s.strip()]

                try:
                    # Generate and send audio for each sentence
                    for sentence in sentences:
                        sentence = sentence + "."  # Add back the period
                        file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid4())[:8]}"
                        audio_path = (
                            await default_context_cache.tts_engine.async_generate_audio(
                                text=sentence, file_name_no_ext=file_name
                            )
                        )
                        logger.info(
                            f"Generated audio for sentence: {sentence} at: {audio_path}"
                        )

                        await websocket.send_json(
                            {
                                "status": "partial",
                                "audioPath": audio_path,
                                "text": sentence,
                            }
                        )

                    # Send completion signal
                    await websocket.send_json({"status": "complete"})

                except Exception as e:
                    logger.error(f"Error generating TTS: {e}")
                    await websocket.send_json({"status": "error", "message": str(e)})

        except WebSocketDisconnect:
            logger.info("TTS WebSocket client disconnected")
        except Exception as e:
            logger.error(f"Error in TTS WebSocket connection: {e}")
            await websocket.close()

    return router


_last_esp32_alert_time: float = 0.0
_ESP32_COOLDOWN_SECONDS: float = 60.0
_ESP32_FREE_PROMPT: str = (
    "The user is chilling and has some free time right now. "
    "Proactively entertain them — tell a short joke, share a fun fact, "
    "or mention something interesting. Keep it brief and in character."
)


def init_esp32_routes(ws_handler: WebSocketHandler) -> APIRouter:
    """Routes for ESP32 behavior pipeline integration.

    Provides:
        - POST /api/esp32-alert: Receive phone-usage alert and trigger VTuber speech
    """
    router = APIRouter()

    @router.post("/api/esp32-alert")
    async def esp32_alert(request: Request):
        global _last_esp32_alert_time

        now = time.time()
        if now - _last_esp32_alert_time < _ESP32_COOLDOWN_SECONDS:
            remaining = int(_ESP32_COOLDOWN_SECONDS - (now - _last_esp32_alert_time))
            logger.info(f"ESP32 alert received but cooldown active ({remaining}s remaining)")
            return JSONResponse({"triggered": 0, "skipped_cooldown": True, "cooldown_remaining_s": remaining})

        if not ws_handler.client_connections:
            logger.info("ESP32 alert received but no active clients")
            return JSONResponse({"triggered": 0, "skipped_cooldown": False})

        _last_esp32_alert_time = now
        data: WSMessage = {"type": "text-input", "text": _ESP32_FREE_PROMPT}

        async def _trigger_with_log(uid: str, ws):
            try:
                await ws_handler._handle_conversation_trigger(
                    websocket=ws, client_uid=uid, data=data
                )
            except Exception as exc:
                logger.exception(f"ESP32 alert: conversation trigger failed for {uid}: {exc}")

        triggered = 0
        for client_uid, websocket in list(ws_handler.client_connections.items()):
            context = ws_handler.client_contexts.get(client_uid)
            if context is None:
                continue
            asyncio.create_task(_trigger_with_log(client_uid, websocket))
            triggered += 1

        logger.info(f"ESP32 free-time alert triggered speech for {triggered} client(s)")
        return JSONResponse({"triggered": triggered, "skipped_cooldown": False})

    return router


def init_profile_routes(config_alts_dir: str) -> APIRouter:
    """
    Routes for the profile selector UI.

    Provides:
        - GET /profiles: Serves the standalone profile selection HTML page
        - GET /api/profiles: Returns rich profile metadata as JSON
    """
    router = APIRouter()

    _static_dir = Path(__file__).parent / "static"

    @router.get("/")
    async def root_redirect(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        entry = _pending_profile_store.get(client_ip)
        if entry and entry.get("expires", 0) > time.time():
            # Valid profile selection pending — let the static frontend handle it
            return RedirectResponse(url="/index.html", status_code=302)
        return RedirectResponse(url="/profiles", status_code=302)

    @router.get("/profiles")
    async def profiles_page():
        html_path = _static_dir / "profiles.html"
        if not html_path.exists():
            return Response("Profile selector not found", status_code=404)
        return FileResponse(str(html_path), media_type="text/html")

    @router.get("/api/profiles")
    async def get_profiles():
        profiles = scan_config_alts_directory_rich(config_alts_dir)
        # Hide the generic fallback default config; only show characters/
        profiles = [p for p in profiles if p.get("filename") != "conf.yaml"]
        return JSONResponse(profiles)

    @router.post("/api/select-profile")
    async def select_profile(request: Request, config: str = Query(...)):
        client_ip = request.client.host if request.client else "unknown"
        _pending_profile_store[client_ip] = {
            "config": config,
            "expires": time.time() + 30,
        }
        logger.info(f"Profile selected by {client_ip}: {config}")
        return JSONResponse({"ok": True})

    return router
