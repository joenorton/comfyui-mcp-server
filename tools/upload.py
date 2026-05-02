"""Upload tools for ComfyUI MCP Server"""

import base64
import io
import logging
from typing import Optional

import requests
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("MCP_Server")

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB decoded

_EXT_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp", "tiff": "image/tiff",
    "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg", "m4a": "audio/mp4",
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "mkv": "video/x-matroska",
}


def register_upload_tools(mcp: FastMCP, comfyui_client):
    """Register file-upload tools with the MCP server."""

    @mcp.tool()
    def upload_file(
        filename: str,
        base64_content: str,
        backend: Optional[str] = None,
        content_type: Optional[str] = None,
        target: str = "input",
    ) -> dict:
        """Upload a binary file (image / audio / video / any blob) into ComfyUI's input folder.

        Returns the uploaded filename (use directly as the `image`/`audio`/`image_last` workflow param)
        and a `view_url` (use as a full URL for the same params — the server auto-uploads URLs too,
        but referencing the already-uploaded filename is faster). Files persist in ComfyUI's input dir.

        Args:
            filename: Bare filename — no path separators (e.g. "portrait.jpg", "narration.mp3").
            base64_content: Base64-encoded file bytes. Max 100 MB decoded.
            backend: "rtx4090" or "rtx3090". If None, routes to the backend with the shortest queue.
                     Subsequent workflow runs that consume this file MUST target the same backend
                     (use `backend=` on the workflow tool).
            content_type: Optional MIME type. Auto-inferred from extension if omitted.
            target: ComfyUI folder type — "input" (default), "temp", or "output".

        Returns:
            { filename, subfolder, type, backend, backend_url, view_url, bytes }
        """
        if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
            return {"error": "filename must be a bare name without path separators"}

        try:
            data = base64.b64decode(base64_content, validate=True)
        except Exception as e:
            return {"error": f"Invalid base64: {e}"}
        if not data:
            return {"error": "Empty payload after base64 decode"}
        if len(data) > MAX_UPLOAD_BYTES:
            return {"error": f"File exceeds {MAX_UPLOAD_BYTES} bytes (got {len(data)})"}

        if content_type is None:
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            content_type = _EXT_MIME.get(ext, "application/octet-stream")

        if target not in ("input", "temp", "output"):
            return {"error": f"target must be one of input/temp/output (got {target!r})"}

        # Pool routes; single-client passes through.
        if hasattr(comfyui_client, "_pick_client"):
            client = comfyui_client._pick_client(backend)
        else:
            client = comfyui_client

        files = {"image": (filename, io.BytesIO(data), content_type)}
        post_data = {"type": target}
        try:
            r = requests.post(f"{client.base_url}/upload/image", files=files, data=post_data, timeout=180)
            r.raise_for_status()
            result = r.json()
        except Exception as e:
            logger.exception("upload_file failed")
            return {"error": f"Upload failed: {e}"}

        uploaded_name = result.get("name", filename)
        subfolder = result.get("subfolder", "")
        actual_type = result.get("type", target)

        backend_name = None
        for n, c in getattr(comfyui_client, "clients", {}).items():
            if c is client:
                backend_name = n
                break

        view_url = f"{client.base_url}/view?filename={uploaded_name}&type={actual_type}"
        if subfolder:
            view_url += f"&subfolder={subfolder}"

        logger.info(
            f"upload_file: {filename} → {uploaded_name} ({len(data)}B, {content_type}) "
            f"on {backend_name or client.base_url}"
        )

        return {
            "filename": uploaded_name,
            "subfolder": subfolder,
            "type": actual_type,
            "backend": backend_name,
            "backend_url": client.base_url,
            "view_url": view_url,
            "bytes": len(data),
        }
