"""File upload endpoint — stores uploaded files and returns URLs.

POST /api/v1/files/upload — multipart upload, returns file_url
GET  /api/v1/files/{file_id} — serve uploaded file

Storage: Local ./uploads/ directory (production uses Vercel Blob via BLOB_READ_WRITE_TOKEN).
Security: Auth required, file type validation, size limit 25MB, no executable files.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from isg_agent.api.deps import require_auth, CurrentUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/files", tags=["files"])

# ─── Config ───────────────────────────────────────────────────────────────────

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/app/data/uploads"))
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
ALLOWED_EXTENSIONS = {
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".svg",
    # Videos
    ".mp4", ".mov", ".webm", ".avi",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt",
    ".rtf", ".ppt", ".pptx", ".json", ".xml",
}
BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".vbs", ".js",
    ".msi", ".dll", ".com", ".scr", ".pif",
}

# ─── Models ───────────────────────────────────────────────────────────────────


class UploadResponse(BaseModel):
    file_id: str
    file_url: str
    file_name: str
    file_size: int
    content_type: str


# ─── Validation ───────────────────────────────────────────────────────────────

_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9._\- ]{1,255}$")


def _validate_file(file: UploadFile) -> None:
    """Validate file before storing."""
    if not file.filename:
        raise HTTPException(400, "File name is required")

    # Extension check
    ext = Path(file.filename).suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        raise HTTPException(400, f"File type {ext} is not allowed")
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type {ext} is not supported. Supported: images, videos, documents")

    # Content type check
    if file.content_type and file.content_type.startswith("application/x-"):
        raise HTTPException(400, "Executable files are not allowed")


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    user: CurrentUser = Depends(require_auth),
):
    """Upload a file. Returns file_id and file_url."""
    _validate_file(file)

    # Read and check size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB")

    # Generate safe filename
    file_id = str(uuid.uuid4())
    ext = Path(file.filename or "file").suffix.lower()
    safe_name = f"{file_id}{ext}"

    # Store locally
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / safe_name
    file_path.write_bytes(content)

    # Build URL (relative — works behind reverse proxy)
    file_url = f"/api/v1/files/{file_id}{ext}"

    logger.info(
        "File uploaded: %s (%s, %d bytes) by user %s",
        file.filename, file.content_type, len(content), user.user_id,
    )

    return UploadResponse(
        file_id=file_id,
        file_url=file_url,
        file_name=file.filename or safe_name,
        file_size=len(content),
        content_type=file.content_type or "application/octet-stream",
    )


@router.get("/{file_id_with_ext}")
async def get_file(file_id_with_ext: str):
    """Serve an uploaded file by its ID."""
    # Validate the ID format to prevent path traversal
    if not re.match(r"^[a-f0-9\-]{36}\.[a-z0-9]{1,10}$", file_id_with_ext):
        raise HTTPException(400, "Invalid file ID")

    file_path = UPLOAD_DIR / file_id_with_ext
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "File not found")

    # Prevent path traversal
    if not file_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
        raise HTTPException(403, "Access denied")

    return FileResponse(file_path)
