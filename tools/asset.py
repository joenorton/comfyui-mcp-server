"""Asset viewing tools for ComfyUI MCP Server"""

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP, Image as FastMCPImage
from asset_processor import (
    encode_preview_for_mcp,
    estimate_response_chars,
    fetch_asset_bytes,
    get_cache_key,
)

logger = logging.getLogger("MCP_Server")


def register_asset_tools(
    mcp: FastMCP,
    asset_registry
):
    """Register asset viewing tools with the MCP server"""
    
    @mcp.tool()
    def view_image(
        asset_id: str,
        mode: str = "thumb",
        max_dim: Optional[int] = None,
        max_b64_chars: Optional[int] = None,
    ) -> dict:
        """View a generated image inline in chat (thumbnail preview only).
        
        This tool allows the AI agent to view generated images inline in the chat interface,
        enabling closed-loop iteration: generate → view → adjust → regenerate.
        
        Only supports image assets (PNG, JPEG, WebP, GIF). For audio/video assets, use the
        asset_url directly or implement separate viewing tools.
        
        Args:
            asset_id: Asset ID returned from generation tools (e.g., generate_image)
            mode: Display mode - "thumb" (thumbnail preview, default) or "metadata" (info only)
            max_dim: Maximum dimension in pixels (default: 512, hard cap)
            max_b64_chars: Maximum base64 character count (default: 100000, ~100KB)
        
        Returns:
            MCP ImageContent structure for inline display, or metadata dict if mode="metadata"
            or if image exceeds budget (refuse-inline branch).
        """
        # Cleanup expired assets periodically
        asset_registry.cleanup_expired()
        
        # Validate asset_id exists in registry (security: only our assets)
        asset_record = asset_registry.get_asset(asset_id)
        if not asset_record:
            return {"error": f"Asset {asset_id} not found (registry is in-memory and resets on restart). Generate a new asset to regenerate."}
        
        # Get asset URL (computed from stable identity)
        asset_url = asset_record.asset_url or asset_record.get_asset_url(asset_registry.comfyui_base_url)
        
        # If metadata mode, return info only
        if mode == "metadata":
            return {
                "asset_id": asset_record.asset_id,
                "asset_url": asset_url,
                "filename": asset_record.filename,
                "subfolder": asset_record.subfolder,
                "folder_type": asset_record.folder_type,
                "mime_type": asset_record.mime_type,
                "width": asset_record.width,
                "height": asset_record.height,
                "bytes_size": asset_record.bytes_size,
                "workflow_id": asset_record.workflow_id,
                "prompt_id": asset_record.prompt_id,
                "created_at": asset_record.created_at.isoformat(),
                "expires_at": asset_record.expires_at.isoformat() if asset_record.expires_at else None
            }
        
        # Enforce: only "thumb" mode for scoped version
        if mode != "thumb":
            return {
                "error": f"Mode '{mode}' not supported in scoped version. Use 'thumb' or 'metadata'."
            }
        
        # Validate content type (only images supported for inline viewing)
        supported_types = ("image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif")
        if asset_record.mime_type not in supported_types:
            return {
                "error": f"Asset type '{asset_record.mime_type}' not supported for inline viewing. "
                         f"Supported types: {', '.join(supported_types)}"
            }
        
        # Set conservative defaults
        if max_dim is None:
            max_dim = 512  # Hard cap for scoped version
        if max_b64_chars is None:
            max_b64_chars = 100_000  # 100KB base64 payload (conservative to prevent hangs)
        
        # Process image for inline viewing
        try:
            # Fetch image bytes using computed URL
            image_url = asset_url
            image_bytes = fetch_asset_bytes(image_url)
            
            # Encode with new function (accepts bytes directly)
            cache_key = get_cache_key(asset_id, max_dim, 70)  # Use quality=70 for cache key
            encoded = encode_preview_for_mcp(
                image_bytes,
                max_dim=max_dim,
                max_b64_chars=max_b64_chars,
                quality=70,
                cache_key=cache_key,
            )
            
            # Log telemetry
            logger.info(
                f"view_image success: asset_id={asset_id} "
                f"src={asset_record.bytes_size}B src_dims={asset_record.width}x{asset_record.height} "
                f"preview_dims={encoded.size_px[0]}x{encoded.size_px[1]} format=webp "
                f"encoded={encoded.bytes_len}B b64_chars={encoded.b64_chars} "
                f"response_est={estimate_response_chars(encoded.b64_chars)}chars"
            )
            
            # Use FastMCP.Image for inline display (not dict)
            # FastMCP.Image takes raw bytes and format string
            return FastMCPImage(data=encoded.raw_bytes, format="webp")
            
        except ValueError as e:
            # Image too large or processing failed - REFUSE-INLINE (non-lethal failure)
            logger.warning(f"Refusing to inline image for {asset_id}: {e}")
            return {
                "content": [{
                    "type": "text",
                    "text": (
                        f"Could not inline image (exceeds budget: {e}).\n"
                        f"Asset ID: {asset_id}\n"
                        f"URL: {asset_record.asset_url}\n"
                        f"Source size: {asset_record.bytes_size} bytes\n"
                        f"Source dimensions: {asset_record.width}x{asset_record.height}\n"
                        f"Hint: Open URL locally or use metadata mode."
                    )
                }]
            }
        except ImportError as e:
            return {"error": f"Image processing not available: {e}. Install Pillow: pip install Pillow"}
        except Exception as e:
            logger.exception(f"Failed to process asset {asset_id} for viewing")
            return {"error": f"Failed to process asset: {str(e)}"}
