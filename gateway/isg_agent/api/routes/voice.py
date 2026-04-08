"""Voice agent API routes.

Endpoints for configuring voice agents, managing phone numbers,
viewing call logs, handling Vapi webhooks, and local STT/TTS.

Routes
------
POST  /api/v1/voice/configure/{agent_id}  -- configure voice for an agent
GET   /api/v1/voice/config/{agent_id}     -- get voice configuration
POST  /api/v1/voice/phone/{agent_id}      -- assign a phone number
POST  /api/v1/voice/call/{agent_id}       -- initiate an outbound call
GET   /api/v1/voice/calls/{agent_id}      -- get call history
POST  /api/v1/voice/webhook/vapi          -- Vapi webhook (public)
POST  /api/v1/voice/transcribe            -- Moonshine STT (public)
GET   /api/v1/voice/speak                 -- Kokoro TTS (public)
"""

from __future__ import annotations

import collections
import datetime
import hmac
import io
import json
import logging
import os
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from fastapi.responses import JSONResponse, StreamingResponse

from isg_agent.api.deps import CurrentUser, require_auth
from isg_agent.integrations.voice_vapi import VapiConnector

__all__ = ["router"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Webhook idempotency cache (in-memory, bounded LRU — max 2 000 entries)
# Key: "{call_id}:{msg_type}"  Value: processed_at epoch float
# Evicts oldest entry when full.  Survives within a single process lifetime.
# ---------------------------------------------------------------------------
_WEBHOOK_SEEN: collections.OrderedDict[str, float] = collections.OrderedDict()
_WEBHOOK_SEEN_MAX = 2_000
_WEBHOOK_SEEN_LOCK = threading.Lock()

# Max accepted webhook payload size (512 KB — Vapi payloads are <10 KB in practice)
_WEBHOOK_MAX_BYTES = 512 * 1024

router = APIRouter(
    prefix="/api/v1/voice",
    tags=["voice"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_vapi(request: Request) -> VapiConnector:
    """Extract the VapiConnector from FastAPI app state.

    Raises 503 if not yet initialised.
    """
    vapi: Optional[VapiConnector] = getattr(request.app.state, "vapi", None)
    if vapi is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice integration not initialised. Server is starting up.",
        )
    return vapi


# Skill dispatch mapping: Vapi function name -> (skill_name, action)
_SKILL_MAP: dict[str, tuple[str, str]] = {
    "schedule_appointment": ("appointments", "schedule"),
    "check_availability": ("appointments", "list"),
    "save_contact": ("contacts", "add"),
    "lookup_information": ("data-store", "search"),
    "send_followup": ("notifications", "send"),
    "transfer_to_owner": ("transfer", "owner_cell"),
}


def _notify_owner_call_transfer(caller_id: str = "unknown") -> None:
    """Fire-and-forget ntfy.sh push notification on call transfer. Never blocks."""

    def _send() -> None:
        try:
            import urllib.request

            ntfy_topic = os.environ.get("NTFY_TOPIC", "mila-dingdawg-calls")
            req = urllib.request.Request(
                f"https://ntfy.sh/{ntfy_topic}",
                data=f"Incoming call transfer from {caller_id}".encode(),
                headers={
                    "Title": "DingDawg Call Transfer",
                    "Priority": "urgent",
                    "Tags": "telephone_receiver",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            logger.debug("ntfy.sh notification failed for caller %s", caller_id)

    threading.Thread(target=_send, daemon=True).start()


# ---------------------------------------------------------------------------
# Authenticated endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/configure/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Configure voice capabilities for an agent",
)
async def configure_voice(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Configure voice capabilities for an agent.

    Body: ``{first_message?, voice_model?, voice_id?, system_prompt?, server_url?}``

    If a Vapi API key is configured on the server, creates a Vapi assistant
    automatically.  Otherwise stores the configuration locally for later
    activation.
    """
    vapi = _get_vapi(request)
    body = await request.json()

    result = await vapi.configure_agent(agent_id, body)
    logger.info(
        "POST /voice/configure/%s: status=%s user=%s",
        agent_id, result.get("status"), current_user.user_id,
    )
    return result


@router.get(
    "/config/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Get voice configuration for an agent",
)
async def get_voice_config(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Get voice configuration for an agent.

    Returns 404 if voice is not configured.
    """
    vapi = _get_vapi(request)
    config = await vapi.get_voice_config(agent_id)

    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice not configured for agent {agent_id!r}.",
        )
    return config


@router.post(
    "/phone/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Assign a phone number to an agent",
)
async def assign_phone(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Assign a phone number to an agent via Vapi.

    Body: ``{area_code?: str}``

    Requires Vapi API key and a configured voice assistant.
    """
    vapi = _get_vapi(request)
    body = await request.json()
    area_code = body.get("area_code", "")

    result = await vapi.assign_phone_number(agent_id, area_code=area_code)

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    logger.info(
        "POST /voice/phone/%s: number=%s user=%s",
        agent_id, result.get("phone_number"), current_user.user_id,
    )
    return result


@router.post(
    "/call/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Initiate an outbound call",
)
async def make_call(
    agent_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Initiate an outbound call from the agent.

    Body: ``{to_number: str, context?: str}``
    """
    vapi = _get_vapi(request)
    body = await request.json()

    to_number = body.get("to_number", "")
    if not to_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="to_number is required.",
        )

    context = body.get("context", "")
    result = await vapi.make_outbound_call(agent_id, to_number, context=context)

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    logger.info(
        "POST /voice/call/%s: call_id=%s user=%s",
        agent_id, result.get("call_id"), current_user.user_id,
    )
    return result


@router.get(
    "/calls/{agent_id}",
    status_code=status.HTTP_200_OK,
    summary="Get call history for an agent",
)
async def get_call_logs(
    agent_id: str,
    request: Request,
    limit: int = 50,
    current_user: CurrentUser = Depends(require_auth),
) -> dict:
    """Get call history for an agent.

    Returns a list of call log entries, newest first.
    """
    vapi = _get_vapi(request)
    logs = await vapi.get_call_logs(agent_id, limit=limit)
    return {"agent_id": agent_id, "calls": logs, "count": len(logs)}


# ---------------------------------------------------------------------------
# Public webhook (no auth — Vapi calls this)
# ---------------------------------------------------------------------------


@router.post(
    "/webhook/vapi",
    status_code=status.HTTP_200_OK,
    summary="Handle Vapi webhook callbacks",
)
async def vapi_webhook(request: Request) -> dict:
    """Handle Vapi webhook callbacks (STOA 5-layer security gate).

    PUBLIC endpoint — Vapi calls this when the voice agent needs to execute a
    function during a call, or to report call completion.

    Security layers (in order):
    1. Content-Type + payload size guard (DoS prevention — max 512 KB)
    2. Shared secret — X-Vapi-Secret header, timing-safe compare
    3. Replay prevention — timestamp freshness window (±5 min)
    4. Idempotency — bounded LRU cache deduplicates call_id + msg_type
    5. Structured rejection audit — every rejected request logged with reason + source IP

    Function-call flow:
    1. Vapi sends ``{message: {type: "function-call", functionCall: {...}}}``
    2. We map the function name to a DingDawg skill
    3. Execute the skill via our executor
    4. Return the result so Vapi speaks it to the caller
    """
    client_ip = request.client.host if request.client else "unknown"

    # ── Layer 1: Content-Type + payload size ─────────────────────────────────
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        logger.warning("Vapi webhook rejected: bad content-type=%r ip=%s", content_type, client_ip)
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Content-Type must be application/json")

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _WEBHOOK_MAX_BYTES:
        logger.warning("Vapi webhook rejected: payload too large (%s bytes) ip=%s", content_length, client_ip)
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload exceeds 512 KB limit")

    raw_body = await request.body()
    if len(raw_body) > _WEBHOOK_MAX_BYTES:
        logger.warning("Vapi webhook rejected: body too large (%d bytes) ip=%s", len(raw_body), client_ip)
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload exceeds 512 KB limit")

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        logger.warning("Vapi webhook rejected: invalid JSON (%s) ip=%s", exc, client_ip)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    # ── Layer 2: Shared secret (timing-safe) ─────────────────────────────────
    webhook_secret = os.environ.get("VAPI_WEBHOOK_SECRET", "")
    if webhook_secret:
        incoming = request.headers.get("x-vapi-secret", "")
        if not hmac.compare_digest(incoming, webhook_secret):
            logger.warning("Vapi webhook rejected: invalid secret ip=%s", client_ip)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret")

    # ── Layer 3: Replay prevention (±5 min freshness window) ─────────────────
    _ts_candidates = [
        body.get("timestamp"),
        body.get("message", {}).get("timestamp"),
        body.get("call", {}).get("createdAt"),
    ]
    for _ts_raw in _ts_candidates:
        if _ts_raw is None:
            continue
        try:
            if isinstance(_ts_raw, str):
                _epoch = datetime.datetime.fromisoformat(_ts_raw.replace("Z", "+00:00")).timestamp()
            else:
                _epoch = float(_ts_raw)
            _age = time.time() - _epoch
            if _age > 300 or _age < -30:
                logger.warning(
                    "Vapi webhook rejected: timestamp age=%.1fs (replay guard) ip=%s", _age, client_ip
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Webhook timestamp outside 5-minute freshness window",
                )
        except HTTPException:
            raise
        except Exception as ts_err:
            logger.debug("Vapi webhook: unparseable timestamp %r (%s) — allowing", _ts_raw, ts_err)
        break  # Check first available timestamp only

    # ── Layer 4: Idempotency (bounded LRU cache) ──────────────────────────────
    message = body.get("message", {})
    _call_id = body.get("call", {}).get("id") or body.get("callId") or ""
    _msg_type = message.get("type", "unknown")
    _idem_key = f"{_call_id}:{_msg_type}"
    if _call_id:
        with _WEBHOOK_SEEN_LOCK:
            if _idem_key in _WEBHOOK_SEEN:
                logger.info("Vapi webhook deduplicated: key=%r ip=%s", _idem_key, client_ip)
                return {"status": "ok", "deduplicated": True}
            _WEBHOOK_SEEN[_idem_key] = time.time()
            _WEBHOOK_SEEN.move_to_end(_idem_key)
            if len(_WEBHOOK_SEEN) > _WEBHOOK_SEEN_MAX:
                _WEBHOOK_SEEN.popitem(last=False)  # evict oldest
    msg_type = message.get("type")

    if msg_type == "function-call":
        func_call = message.get("functionCall", {})
        func_name = func_call.get("name", "")
        params = func_call.get("parameters", {})

        # Handle call transfer to owner (native Vapi transfer action)
        if func_name == "transfer_to_owner":
            owner_cell = os.environ.get("OWNER_CELL_NUMBER", "")
            caller_id = params.get("caller_id", message.get("call", {}).get("customer", {}).get("number", "unknown"))
            _notify_owner_call_transfer(caller_id)
            logger.info("Transferring call to owner: caller=%s", caller_id)
            if not owner_cell:
                logger.warning("OWNER_CELL_NUMBER not set -- cannot transfer call")
                return {"result": "I'm sorry, I'm unable to transfer the call right now. Please try again later."}
            return {
                "result": "Transferring you now.",
                "action": {
                    "type": "transfer-call",
                    "destination": {
                        "type": "number",
                        "number": owner_cell,
                        "callerId": os.environ.get("TWILIO_NUMBER", ""),
                    },
                },
            }

        if func_name in _SKILL_MAP:
            skill_name, action = _SKILL_MAP[func_name]

            # Build skill parameters
            skill_params = {"action": action, **params}

            # Execute via skill executor if available
            executor = getattr(request.app.state, "skill_executor", None)
            if executor is not None:
                try:
                    result = await executor.execute(skill_name, skill_params)
                    output = result.output if result.success else f"Sorry, I couldn't do that: {result.error}"
                    return {"result": output}
                except Exception:
                    logger.exception("Skill execution failed for voice function %s", func_name)
                    return {"result": "Sorry, something went wrong. Let me try a different approach."}

            return {"result": f"I received your request for {func_name}. Let me look into that."}

        return {"result": "I'm not sure how to help with that. Let me transfer you to someone who can."}

    if msg_type == "end-of-call-report":
        vapi = getattr(request.app.state, "vapi", None)
        if vapi is not None:
            try:
                await vapi.log_completed_call(body)
            except Exception:
                logger.exception("Failed to log completed call from Vapi webhook")
        return {"status": "ok"}

    # Other message types (status-update, transcript, etc.) — acknowledge
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Public STT / TTS endpoints (no auth — utility for voice MVP)
# ---------------------------------------------------------------------------

# Minimal valid WAV header (44 bytes, empty audio, 24kHz mono 16-bit)
_EMPTY_WAV = (
    b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    b"\x01\x00\x01\x00\x00\x77\x01\x00\x00\xee\x02\x00"
    b"\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
)


@router.post(
    "/transcribe",
    status_code=status.HTTP_200_OK,
    summary="Speech-to-text via Moonshine STT",
)
async def transcribe_audio(audio: UploadFile = File(...)) -> dict:
    """Moonshine STT endpoint. Accepts audio/wav or audio/webm.

    Returns transcript text and processing duration.

    Model: UsefulSensors/moonshine-base (Apache 2.0).
    Falls back to empty transcript if the model is not installed.

    Install: ``pip install moonshine-onnx``
    """
    import tempfile
    import time

    start_ms = time.monotonic()

    # Save upload to temp file
    tmp_path: str = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name
    except Exception:
        logger.exception("Failed to save uploaded audio to temp file")
        return {"transcript": "", "duration_ms": 0, "model": "moonshine-base", "error": "upload_failed"}

    transcript = ""
    try:
        try:
            from moonshine_onnx import MoonshineOnnxModel, load_audio  # type: ignore[import-untyped]

            model = MoonshineOnnxModel(model_name="moonshine/base")
            audio_data = load_audio(tmp_path)
            tokens = model.generate(audio_data)

            from tokenizers import Tokenizer  # type: ignore[import-untyped]

            tokenizer = Tokenizer.from_pretrained("UsefulSensors/moonshine-base")
            transcript = tokenizer.decode_batch(tokens)[0]
        except ImportError:
            # Moonshine not installed — return empty transcript
            transcript = ""
    except Exception:
        logger.exception("Moonshine STT inference failed")
        transcript = ""
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    duration_ms = int((time.monotonic() - start_ms) * 1000)
    return {"transcript": transcript, "duration_ms": duration_ms, "model": "moonshine-base"}


@router.get(
    "/speak",
    status_code=status.HTTP_200_OK,
    summary="Text-to-speech via Kokoro TTS",
)
async def text_to_speech(text: str, voice: str = "kokoro") -> StreamingResponse:
    """TTS endpoint. Returns an audio/wav stream.

    Model: Kokoro-82M (Apache 2.0, ~300ms first chunk, CPU-viable).
    Falls back to an empty WAV if the model is not installed.

    Install: ``pip install kokoro soundfile``
    """
    audio_bytes: bytes = _EMPTY_WAV
    try:
        try:
            import kokoro  # type: ignore[import-untyped]
            import numpy as np  # type: ignore[import-untyped]
            import soundfile as sf  # type: ignore[import-untyped]

            pipeline = kokoro.KPipeline(lang_code="a")
            audio_chunks: list = []
            for _, _, chunk_audio in pipeline(text, voice="af_heart", speed=1.0):
                audio_chunks.append(chunk_audio)
            if audio_chunks:
                buf = io.BytesIO()
                combined = np.concatenate(audio_chunks)
                sf.write(buf, combined, 24000, format="WAV")
                audio_bytes = buf.getvalue()
        except ImportError:
            # Kokoro/soundfile not installed — return minimal valid WAV
            pass
    except Exception:
        logger.exception("Kokoro TTS synthesis failed")
        audio_bytes = _EMPTY_WAV

    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/wav",
        headers={"X-Voice-Model": voice, "X-Text-Length": str(len(text))},
    )
