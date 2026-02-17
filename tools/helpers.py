"""Shared helper functions for tool implementations"""

import logging
from typing import Any, Dict, Optional

from asset_processor import encode_preview_for_mcp, fetch_asset_bytes, get_cache_key

logger = logging.getLogger("MCP_Server")


def register_and_build_response(
    result: Dict[str, Any],
    workflow_id: str,
    asset_registry,
    tool_name: Optional[str] = None,
    return_inline_preview: bool = False,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """Helper function to register asset and build response data.

    Eliminates code duplication between run_workflow() and _register_workflow_tool().

    Args:
        result: Result dict from comfyui_client.run_custom_workflow()
        workflow_id: Workflow ID
        asset_registry: AssetRegistry instance
        tool_name: Optional tool name (for workflow-backed tools)
        return_inline_preview: Whether to include inline preview
        session_id: Optional session identifier for conversation filtering

    Returns:
        Response data dict with asset_id, asset_url, metadata, etc.
        If the workflow is still running (timeout), returns a job handle dict instead.
    """
    # If the result is a "still running" job handle, pass it through directly
    if result.get("status") == "running":
        return result

    # Register asset in registry using stable identity
    asset_metadata = result.get("asset_metadata", {})
    metadata = {"workflow_id": workflow_id}
    if tool_name:
        metadata["tool"] = tool_name
    
    asset_record = asset_registry.register_asset(
        filename=result.get("filename", ""),
        subfolder=result.get("subfolder", ""),
        folder_type=result.get("folder_type", "output"),
        workflow_id=workflow_id,
        prompt_id=result.get("prompt_id", ""),
        mime_type=asset_metadata.get("mime_type"),
        width=asset_metadata.get("width"),
        height=asset_metadata.get("height"),
        bytes_size=asset_metadata.get("bytes_size"),
        comfy_history=result.get("comfy_history"),
        submitted_workflow=result.get("submitted_workflow"),
        metadata=metadata,
        session_id=session_id
    )
    
    # Build response data
    # Use asset_record.asset_url (computed from stable identity)
    asset_url = asset_record.asset_url or result.get("asset_url", "")
    response_data = {
        "asset_id": asset_record.asset_id,
        "asset_url": asset_url,
        "image_url": asset_url,  # Backward compatibility
        "filename": asset_record.filename,  # Stable identity
        "subfolder": asset_record.subfolder,  # Stable identity
        "folder_type": asset_record.folder_type,  # Stable identity
        "workflow_id": workflow_id,
        "prompt_id": result.get("prompt_id"),
        "mime_type": asset_record.mime_type,
        "width": asset_record.width,
        "height": asset_record.height,
        "bytes_size": asset_record.bytes_size,
    }
    
    if tool_name:
        response_data["tool"] = tool_name
    
    # Include inline preview if requested
    if return_inline_preview:
        try:
            # Only generate preview for images
            supported_types = ("image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif")
            if asset_record.mime_type in supported_types:
                # Use asset URL (computed from stable identity)
                preview_url = asset_url
                if not preview_url:
                    # Fallback: compute from stable identity
                    preview_url = asset_record.get_asset_url(asset_registry.comfyui_base_url)
                # Use new encoding function with conservative budget
                image_bytes = fetch_asset_bytes(preview_url)
                cache_key = get_cache_key(asset_record.asset_id, 256, 70)
                encoded = encode_preview_for_mcp(
                    image_bytes,
                    max_dim=256,
                    max_b64_chars=100_000,  # ~100KB base64
                    quality=70,
                    cache_key=cache_key,
                )
                # Convert to data URI format for backward compatibility
                response_data["inline_preview_base64"] = f"data:{encoded.mime_type};base64,{encoded.b64}"
                response_data["inline_preview_mime_type"] = encoded.mime_type
        except Exception as e:
            logger.warning(f"Failed to generate inline preview: {e}")
            # Don't fail the request if preview generation fails
    
    # Include base64 image data if available (legacy)
    if "image_base64" in result:
        response_data["image_base64"] = result["image_base64"]
        response_data["image_mime_type"] = result.get("image_mime_type", "image/png")
    
    return response_data
