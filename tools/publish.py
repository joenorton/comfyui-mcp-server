"""Publish tools for safely publishing ComfyUI assets to web project directories"""

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from managers.publish_manager import (
    PublishManager,
    auto_generate_filename,
    validate_manifest_key,
    validate_target_filename
)

logger = logging.getLogger("MCP_Server")


def register_publish_tools(
    mcp: FastMCP,
    asset_registry,
    publish_manager: PublishManager
):
    """Register publish tools with the MCP server"""
    
    @mcp.tool()
    def get_publish_info() -> dict:
        """Get publish configuration and status information.
        
        This tool helps debug configuration issues and surfaces wrong assumptions
        immediately. Call this first to verify publish setup before attempting to publish.
        
        Returns:
            Dict with:
            - project_root: Detected project root (path and detection method: "cwd" | "auto-detected")
            - publish_root: Publish directory (path, exists, writable)
            - comfyui_output_root: ComfyUI output root (path or None, detection method, configured flag)
            - comfyui_tried_paths: List of paths checked during detection with validation results
            - config_file: Path to persistent config file
            - status: "ready" | "needs_comfyui_root" | "error"
            - message: Human-readable status/instructions
            - warnings: List of warnings (e.g., "Using fallback project root detection")
            - error_code: Machine-readable error code (if not ready)
        """
        return publish_manager.get_publish_info()
    
    @mcp.tool()
    def set_comfyui_output_root(path: str) -> dict:
        """Set ComfyUI output root directory in persistent configuration.
        
        This tool configures the ComfyUI output directory once, and it will be remembered
        across server restarts. Use this when auto-detection fails or you want explicit control.
        
        The path is validated to ensure:
        - It exists and is a directory
        - It appears to be a ComfyUI output directory (contains ComfyUI_*.png files or output/temp subdirs)
        
        Configuration is stored in a platform-specific location:
        - Windows: %APPDATA%/comfyui-mcp-server/publish_config.json
        - Mac: ~/Library/Application Support/comfyui-mcp-server/publish_config.json
        - Linux: ~/.config/comfyui-mcp-server/publish_config.json
        
        Args:
            path: Absolute or relative path to ComfyUI output directory
                (e.g., "E:/comfyui-desktop/output" or "/opt/ComfyUI/output")
        
        Returns:
            Dict with:
            - success: True if configured successfully
            - path: Resolved absolute path
            - config_file: Path to config file where setting was saved
            - message: Human-readable status message
            - error: Error code if configuration failed
        """
        return publish_manager.set_comfyui_output_root(path)
    
    @mcp.tool()
    def publish_asset(
        asset_id: str,
        target_filename: Optional[str] = None,
        manifest_key: Optional[str] = None,
        format: str = "webp",
        max_bytes: int = 600_000,
        overwrite: bool = True
    ) -> dict:
        """Publish a ComfyUI-generated asset to a web project directory.
        
        Supports two modes:
        - **Demo mode**: Provide `target_filename` (e.g., "hero.webp") - deterministic filename
        - **Library mode**: Omit `target_filename`, provide `manifest_key` - auto-generates filename
        
        **Safety guarantees:**
        - Only assets from current session can be published (asset_id must exist in registry)
        - Source path must be within ComfyUI output root (validated with real path resolution)
        - Target filename validated by strict regex (prevents path traversal)
        - All paths are canonicalized to prevent symlink/traversal attacks
        - Images automatically compressed to meet size limits (deterministic compression ladder)
        
        **Workflow:**
        1. Agent calls `generate_image` → gets `asset_id`
        2. Agent calls `list_assets(session_id=...)` to discover assets
        3. Agent calls `publish_asset(asset_id, target_filename="hero.webp")` (demo mode)
           OR `publish_asset(asset_id, manifest_key="hero")` (library mode)
        4. Server validates, compresses if needed, copies, and updates manifest.json
        
        Args:
            asset_id: Asset ID from generation tools (session-scoped, dies on restart)
            target_filename: Optional target filename (e.g., "hero.webp"). If omitted, auto-generated.
                Must match regex: ^[a-z0-9][a-z0-9._-]{0,63}\.(webp|png|jpg|jpeg)$
            manifest_key: Optional manifest key (required if target_filename omitted).
                Must match regex: ^[a-z0-9][a-z0-9._-]{0,63}$
            format: Target image format (default: "webp"). Ignored if target_filename has extension.
            max_bytes: Maximum file size in bytes (default: 600000). Images are compressed if needed.
            overwrite: Whether to overwrite existing file (default: True)
        
        Returns:
            Dict with published file info:
            - dest_url: Relative URL (e.g., "/gen/hero.webp")
            - dest_path: Absolute path to published file
            - bytes_size: File size in bytes
            - mime_type: MIME type (e.g., "image/webp")
            - width: Image width (if available)
            - height: Image height (if available)
            - compression_info: Compression details (if image was compressed)
        
        Raises:
            Error dict with "error" and "error_code" keys if:
            - Asset not found or expired (ASSET_NOT_FOUND_OR_EXPIRED)
            - Invalid target_filename format (INVALID_TARGET_FILENAME)
            - manifest_key required but missing (MANIFEST_KEY_REQUIRED)
            - Source path outside ComfyUI outputs (SOURCE_PATH_OUTSIDE_ROOT)
            - Path traversal attempt detected (PATH_TRAVERSAL_DETECTED)
            - Copy/compression operation fails (PUBLISH_FAILED)
        """
        # Cleanup expired assets
        asset_registry.cleanup_expired()
        
        # Check readiness first
        is_ready, error_code, error_info = publish_manager.ensure_ready()
        if not is_ready:
            return {
                "error": error_info.get("message", "Publish manager not ready"),
                "error_code": error_code,
                **error_info
            }
        
        # Lookup asset in registry (session-scoped)
        asset_record = asset_registry.get_asset(asset_id)
        if not asset_record:
            return {
                "error": f"Asset {asset_id} not found or expired. Assets are session-scoped and die on server restart. Generate a new asset in the current session.",
                "error_code": "ASSET_NOT_FOUND_OR_EXPIRED"
            }
        
        try:
            # Resolve source path from asset metadata
            source_path = publish_manager.resolve_source_path(
                subfolder=asset_record.subfolder,
                filename=asset_record.filename
            )
            
            # Determine target filename
            if target_filename:
                # Demo mode: use provided filename
                if not validate_target_filename(target_filename):
                    return {
                        "error": f"Invalid target_filename: '{target_filename}'. Must match regex: ^[a-z0-9][a-z0-9._-]{{0,63}}\\.(webp|png|jpg|jpeg)$",
                        "error_code": "INVALID_TARGET_FILENAME"
                    }
                final_target_filename = target_filename
            else:
                # Library mode: auto-generate filename, manifest_key is required
                if not manifest_key:
                    return {
                        "error": "manifest_key is required when target_filename is omitted (library mode). Provide either target_filename or manifest_key.",
                        "error_code": "MANIFEST_KEY_REQUIRED"
                    }
                if not validate_manifest_key(manifest_key):
                    return {
                        "error": f"Invalid manifest_key: '{manifest_key}'. Must match regex: ^[a-z0-9][a-z0-9._-]{{0,63}}$",
                        "error_code": "INVALID_MANIFEST_KEY"
                    }
                # Auto-generate filename
                final_target_filename = auto_generate_filename(asset_id)
                # Extract format from generated filename or use provided format
                if format and not final_target_filename.endswith(f".{format}"):
                    final_target_filename = final_target_filename.rsplit(".", 1)[0] + f".{format}"
            
            # Resolve target path
            target_path = publish_manager.resolve_target_path(final_target_filename)
            
            # Determine format from target filename extension
            target_ext = target_path.suffix.lower().lstrip(".")
            if target_ext in ("webp", "png", "jpg", "jpeg"):
                actual_format = target_ext
            else:
                actual_format = format
            
            # Copy asset with compression if needed
            publish_info = publish_manager.copy_asset(
                source_path=source_path,
                target_path=target_path,
                overwrite=overwrite,
                asset_id=asset_id,
                target_filename=final_target_filename,
                format=actual_format,
                max_bytes=max_bytes
            )
            
            # Update manifest.json if manifest_key provided
            if manifest_key:
                try:
                    publish_manager.update_manifest(
                        manifest_key=manifest_key,
                        filename=target_path.name
                    )
                except Exception as e:
                    # Manifest update failure is non-fatal
                    logger.warning(f"Failed to update manifest for key {manifest_key}: {e}")
            
            # Add image dimensions if available
            result = {
                "dest_url": publish_info["dest_url"],
                "dest_path": publish_info["dest_path"],
                "bytes_size": publish_info["bytes_size"],
                "mime_type": publish_info["mime_type"]
            }
            
            if "compression_info" in publish_info:
                result["compression_info"] = publish_info["compression_info"]
            
            if asset_record.width and asset_record.height:
                result["width"] = asset_record.width
                result["height"] = asset_record.height
            
            logger.info(
                f"Published asset {asset_id} to {final_target_filename}: {publish_info['dest_url']} "
                f"({publish_info['bytes_size']} bytes)"
            )
            
            return result
            
        except ValueError as e:
            # Path validation errors
            error_msg = str(e)
            if "outside" in error_msg.lower() or "COMFYUI_OUTPUT_ROOT" in error_msg:
                error_code = "SOURCE_PATH_OUTSIDE_ROOT"
            elif "traversal" in error_msg.lower() or ".." in error_msg:
                error_code = "PATH_TRAVERSAL_DETECTED"
            elif "Invalid target_filename" in error_msg:
                error_code = "INVALID_TARGET_FILENAME"
            else:
                error_code = "VALIDATION_ERROR"
            
            return {
                "error": error_msg,
                "error_code": error_code
            }
        except Exception as e:
            logger.exception(f"Failed to publish asset {asset_id}")
            return {
                "error": f"Failed to publish asset: {str(e)}",
                "error_code": "PUBLISH_FAILED"
            }
