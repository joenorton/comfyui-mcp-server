"""Upload tools for ComfyUI MCP Server.

Supports both single-shot and chunked uploads. Chunked uploads matter because LLM tool
calls have practical token ceilings — a 1 MB file base64-encoded is ~1.4 MB of pure noise
the model has to generate, which routinely truncates the response. Split into ≤100 KB
decoded chunks (~140 KB encoded each) and the same upload becomes a sequence of small
tool calls.
"""

import base64
import io
import logging
import os
import threading
import time
import uuid
from typing import Optional

import requests
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("MCP_Server")

MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB decoded total
MAX_CHUNK_BYTES = 4 * 1024 * 1024   # 4 MB per chunk (decoded) — generous; LLM should stay <200 KB
UPLOAD_TTL_SECONDS = 1800           # stale upload sessions expire after 30 min

_EXT_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp", "tiff": "image/tiff",
    "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg", "m4a": "audio/mp4",
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "mkv": "video/x-matroska",
}

# In-memory chunk buffer: upload_id → {filename, backend, content_type, target, overwrite,
#                                       total_chunks, received: dict[int,bytes], created_at}
_uploads: dict[str, dict] = {}
_uploads_lock = threading.Lock()


def _safe_filename(name: str) -> Optional[str]:
    """Reject path traversal; collapse to basename."""
    if not name:
        return None
    base = os.path.basename(name.replace("\\", "/"))
    if not base or base in (".", "..") or base.startswith("."):
        return None
    if any(c in base for c in ("\x00", "/", "\\")):
        return None
    return base


def _infer_mime(filename: str, override: Optional[str]) -> str:
    if override:
        return override
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXT_MIME.get(ext, "application/octet-stream")


def _gc_uploads() -> None:
    """Drop stale upload sessions."""
    now = time.time()
    with _uploads_lock:
        stale = [k for k, v in _uploads.items() if now - v["created_at"] > UPLOAD_TTL_SECONDS]
        for k in stale:
            logger.info(f"upload_file: GC stale upload_id={k}")
            del _uploads[k]


def _resolve_target_filename(client_url: str, filename: str, target: str, overwrite: bool) -> str:
    """If overwrite=False and file exists, auto-suffix `name_1.ext`, `name_2.ext`, …"""
    if overwrite:
        return filename
    try:
        r = requests.head(f"{client_url}/view?filename={filename}&type={target}", timeout=10)
        if r.status_code != 200:
            return filename
    except Exception:
        return filename
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    i = 1
    while True:
        cand = f"{stem}_{i}.{ext}" if ext else f"{stem}_{i}"
        try:
            r = requests.head(f"{client_url}/view?filename={cand}&type={target}", timeout=10)
            if r.status_code != 200:
                return cand
        except Exception:
            return cand
        i += 1
        if i > 1000:
            return f"{stem}_{uuid.uuid4().hex[:8]}.{ext}" if ext else f"{stem}_{uuid.uuid4().hex[:8]}"


def _post_to_comfy(client, filename: str, data: bytes, content_type: str, target: str) -> dict:
    files = {"image": (filename, io.BytesIO(data), content_type)}
    post_data = {"type": target}
    r = requests.post(f"{client.base_url}/upload/image", files=files, data=post_data, timeout=300)
    r.raise_for_status()
    return r.json()


def _backend_name_for(comfyui_client, client) -> Optional[str]:
    for n, c in getattr(comfyui_client, "clients", {}).items():
        if c is client:
            return n
    return None


def register_upload_tools(mcp: FastMCP, comfyui_client):
    """Register file-upload tools with the MCP server."""

    @mcp.tool()
    def upload_file(
        filename: str,
        base64_content: str,
        backend: Optional[str] = None,
        content_type: Optional[str] = None,
        target: str = "input",
        overwrite: bool = False,
        chunk_index: int = 0,
        total_chunks: int = 1,
        upload_id: Optional[str] = None,
    ) -> dict:
        """Upload a binary file (image / audio / video / any blob) into ComfyUI's input folder.

        Two modes:

        **Single-shot** (`total_chunks=1`, default): pass full base64 payload in `base64_content`.
        Recommended only for files <100 KB — larger payloads bloat the LLM tool-call response with
        base64 text and frequently truncate. Use chunked mode instead.

        **Chunked**: split the base64 string into ≤140 KB pieces (≤100 KB decoded) and call
        `upload_file` once per piece. First call: `chunk_index=0`, `total_chunks=N`,
        `base64_content=<chunk 0>`. Server returns `upload_id`. Pass that `upload_id` on every
        subsequent call. The final chunk (`chunk_index = total_chunks - 1`) commits the assembled
        bytes to ComfyUI's input folder and returns the same shape as a single-shot upload.

        Args:
            filename: Bare filename (no path separators). Will be sanitised; subfolders not allowed.
            base64_content: Base64-encoded file content for this chunk. Standard padding required.
            backend: "rtx4090" or "rtx3090". If None, routes to backend with shortest queue.
                     Subsequent workflow runs that consume this file MUST target the same backend.
                     For chunked uploads the backend is fixed at chunk 0; later chunks may omit it.
            content_type: Optional MIME type override. Auto-inferred from extension if omitted.
            target: ComfyUI folder type — "input" (default), "temp", or "output".
            overwrite: If False (default) and a file with the same name exists, the upload is
                       auto-suffixed (`portrait.jpg` → `portrait_1.jpg`). If True, the existing
                       file is replaced.
            chunk_index: Zero-indexed position of this chunk. Required for `total_chunks > 1`.
            total_chunks: Total number of chunks. Default 1 = single-shot mode.
            upload_id: Returned from the chunk-0 call; required for `chunk_index > 0`.

        Returns (mid-chunk):
            { status: "buffering", upload_id, received_chunks, total_chunks, bytes_so_far }

        Returns (final chunk / single-shot):
            { filename, subfolder, type, backend, backend_url, view_url, bytes }
        """
        _gc_uploads()

        safe = _safe_filename(filename)
        if not safe:
            return {"error": "filename must be a bare name (no slashes, no leading dot, no traversal)"}

        if total_chunks < 1 or chunk_index < 0 or chunk_index >= total_chunks:
            return {"error": f"invalid chunk indexing: chunk_index={chunk_index}, total_chunks={total_chunks}"}

        if target not in ("input", "temp", "output"):
            return {"error": f"target must be one of input/temp/output (got {target!r})"}

        try:
            chunk_bytes = base64.b64decode(base64_content, validate=True) if base64_content else b""
        except Exception as e:
            return {"error": f"Invalid base64 in chunk {chunk_index}: {e}"}
        if len(chunk_bytes) > MAX_CHUNK_BYTES:
            return {"error": f"Chunk {chunk_index} exceeds {MAX_CHUNK_BYTES} bytes"}

        # Single-shot path
        if total_chunks == 1:
            if not chunk_bytes:
                return {"error": "Empty payload"}
            if len(chunk_bytes) > MAX_FILE_BYTES:
                return {"error": f"File exceeds {MAX_FILE_BYTES} bytes"}
            client = comfyui_client._pick_client(backend) if hasattr(comfyui_client, "_pick_client") else comfyui_client
            mime = _infer_mime(safe, content_type)
            target_name = _resolve_target_filename(client.base_url, safe, target, overwrite)
            try:
                result = _post_to_comfy(client, target_name, chunk_bytes, mime, target)
            except Exception as e:
                logger.exception("upload_file (single-shot) failed")
                return {"error": f"Upload failed: {e}"}
            return _format_response(result, target, target_name, len(chunk_bytes), client, comfyui_client)

        # Chunked path
        if chunk_index == 0:
            new_id = uuid.uuid4().hex
            with _uploads_lock:
                _uploads[new_id] = {
                    "filename": safe,
                    "backend": backend,
                    "content_type": content_type,
                    "target": target,
                    "overwrite": overwrite,
                    "total_chunks": total_chunks,
                    "received": {0: chunk_bytes},
                    "created_at": time.time(),
                }
            session = _uploads[new_id]
            current_id = new_id
        else:
            if not upload_id:
                return {"error": "upload_id required for chunk_index > 0 (got from chunk 0 response)"}
            with _uploads_lock:
                session = _uploads.get(upload_id)
            if session is None:
                return {"error": f"unknown upload_id {upload_id} (expired or never started)"}
            if session["total_chunks"] != total_chunks:
                return {"error": f"total_chunks mismatch: chunk 0 said {session['total_chunks']}, this chunk said {total_chunks}"}
            if chunk_index in session["received"]:
                return {"error": f"chunk {chunk_index} already received"}
            session["received"][chunk_index] = chunk_bytes
            current_id = upload_id

        # Enforce per-session size cap
        bytes_so_far = sum(len(c) for c in session["received"].values())
        if bytes_so_far > MAX_FILE_BYTES:
            with _uploads_lock:
                _uploads.pop(current_id, None)
            return {"error": f"cumulative size exceeds {MAX_FILE_BYTES} bytes"}

        # Not done yet
        if len(session["received"]) < total_chunks:
            return {
                "status": "buffering",
                "upload_id": current_id,
                "received_chunks": len(session["received"]),
                "total_chunks": total_chunks,
                "bytes_so_far": bytes_so_far,
            }

        # Final assembly
        try:
            data = b"".join(session["received"][i] for i in range(total_chunks))
        except KeyError as e:
            return {"error": f"missing chunk index {e}"}

        client = comfyui_client._pick_client(session["backend"]) if hasattr(comfyui_client, "_pick_client") else comfyui_client
        mime = _infer_mime(session["filename"], session["content_type"])
        target_name = _resolve_target_filename(client.base_url, session["filename"], session["target"], session["overwrite"])
        try:
            result = _post_to_comfy(client, target_name, data, mime, session["target"])
        except Exception as e:
            logger.exception("upload_file (chunked finalize) failed")
            return {"error": f"Upload failed on finalize: {e}"}
        finally:
            with _uploads_lock:
                _uploads.pop(current_id, None)

        return _format_response(result, session["target"], target_name, len(data), client, comfyui_client)


def _format_response(result: dict, target: str, requested_name: str, byte_len: int, client, comfyui_client) -> dict:
    uploaded_name = result.get("name", requested_name)
    subfolder = result.get("subfolder", "")
    actual_type = result.get("type", target)
    backend_name = _backend_name_for(comfyui_client, client)

    view_url = f"{client.base_url}/view?filename={uploaded_name}&type={actual_type}"
    if subfolder:
        view_url += f"&subfolder={subfolder}"

    logger.info(
        f"upload_file: {requested_name} → {uploaded_name} ({byte_len}B) "
        f"on {backend_name or client.base_url}"
    )
    return {
        "filename": uploaded_name,
        "subfolder": subfolder,
        "type": actual_type,
        "backend": backend_name,
        "backend_url": client.base_url,
        "view_url": view_url,
        "bytes": byte_len,
    }
