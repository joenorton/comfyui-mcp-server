"""Publish manager for safely publishing ComfyUI assets to web project directories"""

import json
import logging
import os
import platform
import re
import shutil
import threading
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger("MCP_Server")

# Target filename validation regex: simple filename only, no paths
TARGET_FILENAME_REGEX = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}\.(webp|png|jpg|jpeg)$')
# Manifest key validation regex: same as target_filename but no extension
MANIFEST_KEY_REGEX = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')


def get_publish_config_dir() -> Path:
    """Get platform-specific config directory for publish settings.
    
    Returns:
        Windows: %APPDATA%/comfyui-mcp-server
        Mac: ~/Library/Application Support/comfyui-mcp-server
        Linux: ~/.config/comfyui-mcp-server
    """
    system = platform.system()
    if system == "Windows":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "comfyui-mcp-server"
        # Fallback to user home
        return Path.home() / "AppData" / "Roaming" / "comfyui-mcp-server"
    elif system == "Darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "comfyui-mcp-server"
    else:  # Linux and others
        return Path.home() / ".config" / "comfyui-mcp-server"


def get_publish_config_file() -> Path:
    """Get path to publish config file."""
    return get_publish_config_dir() / "publish_config.json"


def load_publish_config() -> Dict[str, Any]:
    """Load persistent publish configuration.
    
    Returns:
        Config dict with keys like 'comfyui_output_root'
    """
    config_file = get_publish_config_file()
    if not config_file.exists():
        return {}
    
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config if isinstance(config, dict) else {}
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load publish config from {config_file}: {e}")
        return {}


def save_publish_config(config: Dict[str, Any]) -> bool:
    """Save persistent publish configuration.
    
    Args:
        config: Config dict to save
    
    Returns:
        True if successful, False otherwise
    """
    config_file = get_publish_config_file()
    config_dir = config_file.parent
    
    try:
        # Ensure config directory exists
        config_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing config to merge
        existing = load_publish_config()
        existing.update(config)
        
        # Save merged config
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        
        logger.info(f"Saved publish config to {config_file}")
        return True
    except (IOError, OSError) as e:
        logger.error(f"Failed to save publish config to {config_file}: {e}")
        return False


def canonicalize_path(path: Union[str, Path], must_exist: bool = True) -> Path:
    """Resolve path to absolute real path (handles symlinks).
    
    Args:
        path: Path to canonicalize (can be string or Path)
        must_exist: If True, path must exist (default: True)
    
    Returns:
        Absolute Path object with symlinks resolved
    
    Raises:
        ValueError: If path cannot be resolved and must_exist=True
    """
    try:
        if must_exist:
            resolved = Path(path).resolve(strict=True)
        else:
            # For non-existent paths, resolve without strict check
            # This still resolves symlinks in parent directories
            resolved = Path(path).resolve()
        return resolved
    except (OSError, RuntimeError) as e:
        if must_exist:
            raise ValueError(f"Cannot resolve path {path}: {e}")
        # For non-existent paths, still try to resolve (may fail on invalid parent)
        try:
            return Path(path).resolve()
        except (OSError, RuntimeError):
            raise ValueError(f"Cannot resolve path {path}: {e}")


def is_within(child_path: Union[str, Path], parent_path: Union[str, Path], child_must_exist: bool = True) -> bool:
    """Check if child_path is within parent_path using real path resolution.
    
    Both paths are canonicalized (symlinks resolved) before comparison.
    This prevents path traversal attacks via symlinks.
    
    Args:
        child_path: Path to check (can be string or Path)
        parent_path: Parent directory to check against (can be string or Path)
        child_must_exist: If True, child path must exist (default: True)
    
    Returns:
        True if child_path is within parent_path, False otherwise
    """
    try:
        child_real = canonicalize_path(child_path, must_exist=child_must_exist)
        parent_real = canonicalize_path(parent_path, must_exist=True)  # Parent should always exist
        
        # Use Path.is_relative_to() if available (Python 3.9+)
        # Otherwise, check if commonpath equals parent path
        if hasattr(Path, 'is_relative_to'):
            # Python 3.9+
            try:
                return child_real.is_relative_to(parent_real)
            except (ValueError, TypeError):
                # Different drives or invalid paths
                return False
        else:
            # Python < 3.9 fallback
            try:
                common = os.path.commonpath([str(child_real), str(parent_real)])
                return os.path.normpath(common) == os.path.normpath(str(parent_real))
            except ValueError:
                # Paths on different drives (Windows) or invalid
                return False
    except (ValueError, OSError):
        return False


def detect_project_root() -> Tuple[Path, str]:
    """Detect project root directory.
    
    Primary contract: server should be started from repo root (cwd).
    Conservative fallback: search upward for project markers.
    
    Returns:
        Tuple of (project_root Path, detection_method string)
        detection_method: "cwd" | "auto-detected" | "error"
    
    Raises:
        ValueError: If detection is ambiguous or fails
    """
    cwd = Path.cwd()
    
    # Primary: use cwd (expected usage)
    # Check if cwd looks like a project root
    project_markers = [".git", "package.json", "pyproject.toml", "Cargo.toml"]
    has_markers = any((cwd / marker).exists() for marker in project_markers)
    has_public = (cwd / "public").exists() or (cwd / "static").exists()
    
    if has_markers or has_public:
        return cwd, "cwd"
    
    # Conservative fallback: search upward for markers
    current = cwd
    found_markers = []
    
    for _ in range(10):  # Limit search depth
        markers_here = [m for m in project_markers if (current / m).exists()]
        if markers_here:
            found_markers.append((current, markers_here))
        current = current.parent
        if current == current.parent:  # Reached filesystem root
            break
    
    if len(found_markers) == 0:
        # No markers found, use cwd anyway (best guess)
        logger.warning("No project markers found, using cwd as project root")
        return cwd, "cwd"
    elif len(found_markers) == 1:
        # Single marker found, use it
        project_root, _ = found_markers[0]
        logger.info(f"Auto-detected project root: {project_root} (found markers: {found_markers[0][1]})")
        return project_root, "auto-detected"
    else:
        # Multiple markers at different levels - ambiguous
        levels = [str(p) for p, _ in found_markers]
        raise ValueError(
            f"Ambiguous project root detection. Found markers at multiple levels: {levels}. "
            f"Please start the MCP server from the repo root (cwd)."
        )


def get_default_publish_root(project_root: Path) -> Path:
    """Get default publish root directory.
    
    Tries in order: public/gen → static/gen → assets/gen
    Creates directory if needed.
    
    Args:
        project_root: Project root directory
    
    Returns:
        Publish root directory (created if needed)
    """
    candidates = [
        project_root / "public" / "gen",
        project_root / "static" / "gen",
        project_root / "assets" / "gen"
    ]
    
    for candidate in candidates:
        if candidate.parent.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
    
    # If none of the parent dirs exist, use public/gen (most common)
    default = candidates[0]
    default.mkdir(parents=True, exist_ok=True)
    return default


def validate_comfyui_output_root(path: Path) -> bool:
    """Validate that a path looks like a ComfyUI output directory.
    
    Checks for ComfyUI patterns:
    - ComfyUI_*.png files (strong indicator)
    - Any image files (png, jpg, jpeg, webp) - ComfyUI outputs images
    - output/ or temp/ subdirectories (ComfyUI structure)
    - At least a few files (not empty)
    
    Args:
        path: Path to validate
    
    Returns:
        True if path looks like ComfyUI output, False otherwise
    """
    if not path.exists() or not path.is_dir():
        return False
    
    # Strong indicator: ComfyUI_*.png files
    comfyui_files = list(path.glob("ComfyUI_*.png"))
    if comfyui_files:
        return True
    
    # Check for output/ or temp/ subdirectories (ComfyUI structure)
    if (path / "output").exists() or (path / "temp").exists():
        return True
    
    # Lenient check: if directory has image files, it's probably ComfyUI output
    # (ComfyUI typically outputs images directly to the output directory)
    image_extensions = [".png", ".jpg", ".jpeg", ".webp", ".gif"]
    image_files = []
    for ext in image_extensions:
        image_files.extend(path.glob(f"*{ext}"))
        if len(image_files) >= 3:  # If we find a few images, it's likely ComfyUI output
            return True
    
    return False


def detect_comfyui_output_root(project_root: Path, comfyui_url: str = "http://localhost:8188") -> Tuple[Optional[Path], List[Dict[str, Any]]]:
    """Detect ComfyUI output root directory (best-effort, tight candidates only).
    
    Detection order:
    1. Persistent config (if set via set_comfyui_output_root tool)
    2. Tight candidate list (2-5 paths only, no broad scanning)
    
    Args:
        project_root: Project root directory
        comfyui_url: ComfyUI server URL (unused for now, reserved for future API queries)
    
    Returns:
        Tuple of (detected_path or None, list of tried paths with validation results)
    """
    tried_paths = []
    
    # 1. Check persistent config first (highest priority)
    persistent_config = load_publish_config()
    configured_path = persistent_config.get("comfyui_output_root")
    if configured_path:
        try:
            resolved = Path(configured_path).resolve()
            exists = resolved.exists() and resolved.is_dir()
            is_valid = validate_comfyui_output_root(resolved) if exists else False
            
            tried_paths.append({
                "path": str(resolved),
                "exists": exists,
                "is_valid": is_valid,
                "source": "persistent_config"
            })
            
            if is_valid:
                logger.info(f"Using ComfyUI output root from persistent config: {resolved}")
                return resolved, tried_paths
            elif exists:
                # Path exists but doesn't validate - still return it with warning
                logger.warning(f"Configured ComfyUI output root exists but doesn't validate: {resolved}")
                return resolved, tried_paths
        except (OSError, ValueError) as e:
            tried_paths.append({
                "path": configured_path,
                "exists": False,
                "is_valid": False,
                "source": "persistent_config",
                "error": str(e)
            })
    
    # 2. Tight candidate list (2-5 paths only, no broad scanning)
    candidates = []
    
    # Relative to project root (common for dev setups)
    candidates.append(project_root / "comfyui-desktop" / "output")
    candidates.append(project_root.parent / "comfyui-desktop" / "output")
    candidates.append(project_root / "ComfyUI" / "output")
    
    # User home (common for desktop installs)
    candidates.append(Path.home() / "comfyui-desktop" / "output")
    
    # Platform-specific common location (one per platform, not scanning drives)
    if os.name == "nt":  # Windows - check E: drive (user's specific location)
        candidates.append(Path("E:/comfyui-desktop/output"))
    # Don't scan C:, D:, etc. - that's what we're avoiding
    
    # Try each candidate
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            exists = resolved.exists() and resolved.is_dir()
            is_valid = validate_comfyui_output_root(resolved) if exists else False
            
            tried_paths.append({
                "path": str(resolved),
                "exists": exists,
                "is_valid": is_valid,
                "source": "auto_detection"
            })
            
            if is_valid:
                logger.info(f"Auto-detected ComfyUI output root: {resolved}")
                return resolved, tried_paths
        except (OSError, ValueError) as e:
            tried_paths.append({
                "path": str(candidate),
                "exists": False,
                "is_valid": False,
                "source": "auto_detection",
                "error": str(e)
            })
    
    # None found
    logger.warning(f"Could not detect ComfyUI output root. Tried {len(tried_paths)} paths.")
    return None, tried_paths


def validate_target_filename(filename: str) -> bool:
    """Validate target filename against regex.
    
    Args:
        filename: Filename to validate
    
    Returns:
        True if valid, False otherwise
    """
    return bool(TARGET_FILENAME_REGEX.match(filename))


def validate_manifest_key(key: str) -> bool:
    """Validate manifest key against regex.
    
    Args:
        key: Manifest key to validate
    
    Returns:
        True if valid, False otherwise
    """
    return bool(MANIFEST_KEY_REGEX.match(key))


def auto_generate_filename(asset_id: str) -> str:
    """Auto-generate filename from asset_id.
    
    Args:
        asset_id: Asset ID (UUID)
    
    Returns:
        Generated filename: asset_<shortid>.webp
    """
    # Use first 8 chars of asset_id for shortid
    shortid = asset_id[:8] if len(asset_id) >= 8 else asset_id
    return f"asset_{shortid}.webp"


class PublishConfig:
    """Configuration for asset publishing."""
    
    def __init__(
        self,
        project_root: Optional[Union[str, Path]] = None,
        publish_root: Optional[Union[str, Path]] = None,
        comfyui_output_root: Optional[Union[str, Path]] = None,
        comfyui_url: str = "http://localhost:8188"
    ):
        """Initialize publish configuration.
        
        Args:
            project_root: Project root directory (auto-detected if None)
            publish_root: Publish directory (auto-detected if None)
            comfyui_output_root: ComfyUI outputs directory (auto-detected if None, best-effort)
            comfyui_url: ComfyUI server URL (for detection)
        """
        # Detect project root
        if project_root:
            self.project_root = Path(project_root).resolve()
            self.project_root_method = "configured"
        else:
            self.project_root, self.project_root_method = detect_project_root()
        
        # Get publish root
        if publish_root:
            self.publish_root = Path(publish_root).resolve()
        else:
            self.publish_root = get_default_publish_root(self.project_root)
        
        # Ensure publish_root exists
        self.publish_root.mkdir(parents=True, exist_ok=True)
        
        # ComfyUI output root
        # Priority: explicit param > persistent config > auto-detection
        if comfyui_output_root:
            self.comfyui_output_root = Path(comfyui_output_root).resolve()
            self.comfyui_output_method = "explicit"
            self.comfyui_tried_paths = []
        else:
            # detect_comfyui_output_root now checks persistent config first
            detected, tried = detect_comfyui_output_root(self.project_root, comfyui_url)
            self.comfyui_output_root = detected
            # Check if it came from persistent config
            persistent_config = load_publish_config()
            if persistent_config.get("comfyui_output_root"):
                self.comfyui_output_method = "persistent_config" if detected else "not_found"
            else:
                self.comfyui_output_method = "auto-detected" if detected else "not_found"
            self.comfyui_tried_paths = tried
        
        self.comfyui_url = comfyui_url


class PublishManager:
    """Manages safe publishing of ComfyUI assets to web project directories."""
    
    def __init__(self, config: PublishConfig):
        """Initialize publish manager.
        
        Args:
            config: Publish configuration
        """
        self.config = config
        self._manifest_lock = threading.Lock()  # Process-level lock for manifest updates
        logger.info(f"Initialized PublishManager with publish_root={config.publish_root}")
        if config.comfyui_output_root:
            logger.info(f"ComfyUI output root: {config.comfyui_output_root} (method: {config.comfyui_output_method})")
    
    def ensure_ready(self) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Check if publish manager is ready to publish.
        
        Returns:
            Tuple of (is_ready, error_code, error_info)
            error_info contains tried paths, warnings, etc.
        """
        errors = []
        warnings = []
        info = {}
        
        # Check publish_root is writable
        if not os.access(self.config.publish_root, os.W_OK):
            errors.append("PUBLISH_ROOT_NOT_WRITABLE")
            return False, "PUBLISH_ROOT_NOT_WRITABLE", {
                "publish_root": str(self.config.publish_root),
                "message": f"Publish root is not writable: {self.config.publish_root}"
            }
        
        # Check ComfyUI output root
        if not self.config.comfyui_output_root:
            errors.append("COMFYUI_OUTPUT_ROOT_NOT_FOUND")
            return False, "COMFYUI_OUTPUT_ROOT_NOT_FOUND", {
                "tried_paths": self.config.comfyui_tried_paths,
                "message": f"COMFYUI_OUTPUT_ROOT not configured. Tried: {[p['path'] for p in self.config.comfyui_tried_paths]}. Set COMFYUI_OUTPUT_ROOT environment variable."
            }
        
        # Check ComfyUI output root exists and is valid
        if not self.config.comfyui_output_root.exists():
            errors.append("COMFYUI_OUTPUT_ROOT_NOT_FOUND")
            return False, "COMFYUI_OUTPUT_ROOT_NOT_FOUND", {
                "comfyui_output_root": str(self.config.comfyui_output_root),
                "message": f"ComfyUI output root does not exist: {self.config.comfyui_output_root}"
            }
        
        if not validate_comfyui_output_root(self.config.comfyui_output_root):
            warnings.append(f"ComfyUI output root may not be valid: {self.config.comfyui_output_root}")
        
        # Add warnings for fallback detection
        if self.config.project_root_method == "auto-detected":
            warnings.append("Using fallback project root detection (start server from repo root for best results)")
        
        if self.config.comfyui_output_method == "auto-detected":
            warnings.append("Using auto-detected ComfyUI output root (set COMFYUI_OUTPUT_ROOT for explicit control)")
        
        return True, None, {"warnings": warnings} if warnings else None
    
    def resolve_source_path(self, subfolder: str, filename: str) -> Path:
        """Resolve source path from asset metadata.
        
        Args:
            subfolder: Asset subfolder (often empty)
            filename: Asset filename
        
        Returns:
            Resolved source path
        
        Raises:
            ValueError: If source path is outside COMFYUI_OUTPUT_ROOT or doesn't exist
        """
        if not self.config.comfyui_output_root:
            raise ValueError("COMFYUI_OUTPUT_ROOT not configured")
        
        # Join paths
        if subfolder:
            source_path = self.config.comfyui_output_root / subfolder / filename
        else:
            source_path = self.config.comfyui_output_root / filename
        
        # Canonicalize to resolve symlinks and get absolute path
        try:
            source_real = canonicalize_path(source_path)
        except ValueError as e:
            raise ValueError(f"Source path cannot be resolved: {e}")
        
        # Verify containment within ComfyUI output root
        output_root_real = canonicalize_path(self.config.comfyui_output_root)
        if not is_within(source_real, output_root_real):
            raise ValueError(
                f"Source path {source_real} is outside ComfyUI output root {output_root_real}"
            )
        
        # Verify file exists
        if not source_real.exists():
            raise ValueError(f"Source file does not exist: {source_real}")
        
        if not source_real.is_file():
            raise ValueError(f"Source path is not a file: {source_real}")
        
        return source_real
    
    def resolve_target_path(self, target_filename: str) -> Path:
        """Resolve target path from target_filename.
        
        Args:
            target_filename: Target filename (validated by regex)
        
        Returns:
            Resolved target path
        
        Raises:
            ValueError: If target_filename is invalid or path is outside publish root
        """
        # Validate filename
        if not validate_target_filename(target_filename):
            raise ValueError(
                f"Invalid target_filename: '{target_filename}'. "
                f"Must match regex: ^[a-z0-9][a-z0-9._-]{{0,63}}\\.(webp|png|jpg|jpeg)$"
            )
        
        target_path = self.config.publish_root / target_filename
        
        # Verify containment within publish root
        # Use must_exist=False since target may not exist yet
        target_real = canonicalize_path(target_path, must_exist=False)
        publish_root_real = canonicalize_path(self.config.publish_root, must_exist=True)
        if not is_within(target_real, publish_root_real, child_must_exist=False):
            raise ValueError(
                f"Target path {target_real} is outside publish root {publish_root_real}"
            )
        
        return target_real
    
    def _compress_image(
        self,
        source_path: Path,
        target_format: str,
        max_bytes: int
    ) -> Tuple[bytes, Dict[str, Any]]:
        """Compress image using deterministic compression ladder.
        
        Tries quality levels and downscaling in a fixed sequence until size limit is met.
        
        Args:
            source_path: Source image path
            target_format: Target format ("webp", "png", "jpg")
            max_bytes: Maximum file size in bytes
        
        Returns:
            Tuple of (compressed_bytes, compression_info dict)
        
        Raises:
            ImportError: If Pillow is not available
            ValueError: If image cannot be compressed below max_bytes
        """
        if not PIL_AVAILABLE:
            raise ImportError("Pillow is required for image compression. Install with: pip install Pillow")
        
        # Read source image
        with open(source_path, "rb") as f:
            source_bytes = f.read()
        
            # If source is already small enough and format matches, return as-is
            source_ext = source_path.suffix.lower().lstrip(".")
            if len(source_bytes) <= max_bytes and source_ext == target_format:
                return source_bytes, {
                    "compressed": False,
                    "original_size": len(source_bytes),
                    "final_size": len(source_bytes),
                    "quality": None,
                    "downscaled": False
                }
        
        # Load image
        with Image.open(BytesIO(source_bytes)) as im:
            original_size = im.size
            original_mode = im.mode
            
            # Convert to RGB if needed (for JPEG/WebP)
            if target_format in ("webp", "jpg", "jpeg"):
                if im.mode in ("RGBA", "LA", "P"):
                    # Create white background for transparency
                    background = Image.new("RGB", im.size, (255, 255, 255))
                    if im.mode == "P":
                        im = im.convert("RGBA")
                    if im.mode in ("RGBA", "LA"):
                        background.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                    im = background
                elif im.mode != "RGB":
                    im = im.convert("RGB")
            
            # Deterministic compression ladder
            # Quality progression: [85, 75, 65, 55, 45, 35]
            # Downscale targets: [original, 0.9x, 0.75x, 0.6x, 0.5x] (if needed)
            quality_levels = [85, 75, 65, 55, 45, 35]
            downscale_factors = [1.0, 0.9, 0.75, 0.6, 0.5]
            
            compression_info = {
                "compressed": True,
                "original_size": len(source_bytes),
                "original_dimensions": original_size,
                "quality": None,
                "final_dimensions": original_size,
                "downscaled": False
            }
            
            for downscale_factor in downscale_factors:
                # Calculate new dimensions
                if downscale_factor < 1.0:
                    new_size = (max(1, int(im.size[0] * downscale_factor)), 
                               max(1, int(im.size[1] * downscale_factor)))
                    im_resized = im.resize(new_size, Image.Resampling.LANCZOS)
                    compression_info["downscaled"] = True
                    compression_info["final_dimensions"] = new_size
                else:
                    im_resized = im
                
                # Try quality levels
                for quality in quality_levels:
                    buf = BytesIO()
                    
                    try:
                        if target_format == "webp":
                            save_kwargs = {
                                "format": "WEBP",
                                "quality": quality,
                                "method": 5  # Method 5 trades CPU for size
                            }
                            # Preserve alpha if original had it and we're not converting to RGB
                            if original_mode in ("RGBA", "LA") and downscale_factor == 1.0:
                                # For WebP, we can preserve alpha if not downscaled
                                if im_resized.mode not in ("RGBA", "LA"):
                                    # Re-check if we need alpha
                                    pass
                            im_resized.save(buf, **save_kwargs)
                        elif target_format in ("jpg", "jpeg"):
                            im_resized.save(buf, format="JPEG", quality=quality, optimize=True)
                        elif target_format == "png":
                            # PNG doesn't use quality, but we can optimize
                            im_resized.save(buf, format="PNG", optimize=True)
                        else:
                            raise ValueError(f"Unsupported target format: {target_format}")
                        
                        compressed_bytes = buf.getvalue()
                        
                        # Check if within size limit
                        if len(compressed_bytes) <= max_bytes:
                            compression_info["final_size"] = len(compressed_bytes)
                            compression_info["quality"] = quality
                            logger.info(
                                f"Compressed image: {len(source_bytes)} -> {len(compressed_bytes)} bytes "
                                f"(quality={quality}, downscale={downscale_factor:.2f})"
                            )
                            return compressed_bytes, compression_info
                    except Exception as e:
                        logger.warning(f"Compression attempt failed (quality={quality}, factor={downscale_factor}): {e}")
                        continue
            
            # If we get here, couldn't compress below max_bytes
            # Return the smallest we achieved
            buf = BytesIO()
            if target_format == "webp":
                im_resized.save(buf, format="WEBP", quality=35, method=5)
            elif target_format in ("jpg", "jpeg"):
                im_resized.save(buf, format="JPEG", quality=35, optimize=True)
            else:
                im_resized.save(buf, format="PNG", optimize=True)
            
            final_bytes = buf.getvalue()
            compression_info["final_size"] = len(final_bytes)
            compression_info["quality"] = 35
            
            if len(final_bytes) > max_bytes:
                raise ValueError(
                    f"Image cannot be compressed below {max_bytes} bytes. "
                    f"Smallest achieved: {len(final_bytes)} bytes. "
                    f"Original: {len(source_bytes)} bytes, {original_size[0]}x{original_size[1]}"
                )
            
            return final_bytes, compression_info
    
    def copy_asset(
        self,
        source_path: Path,
        target_path: Path,
        overwrite: bool = True,
        asset_id: Optional[str] = None,
        target_filename: Optional[str] = None,
        format: str = "webp",
        max_bytes: int = 600_000
    ) -> Dict[str, Any]:
        """Copy asset from source to target with atomic write and optional compression.
        
        Args:
            source_path: Source file path
            target_path: Target file path
            overwrite: Whether to overwrite existing file (default: True)
            asset_id: Optional asset ID for logging
            target_filename: Optional target filename for logging
            format: Target format (default: webp)
            max_bytes: Maximum file size in bytes (default: 600KB)
        
        Returns:
            Dict with published file info: dest_path, dest_url, bytes_size, mime_type, compression_info
        
        Raises:
            ValueError: If overwrite is False and target exists, or if size limit exceeded
            OSError: If copy fails
        """
        if target_path.exists() and not overwrite:
            raise ValueError(f"Target file already exists and overwrite=False: {target_path}")
        
        # Create temp file in same directory for atomic write
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
        
        try:
            # Check if source is an image and needs compression
            source_ext = source_path.suffix.lower()
            target_ext = target_path.suffix.lower()
            is_image = source_ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")
            needs_compression = is_image and (format != "original" or target_ext != source_ext)
            
            if needs_compression and PIL_AVAILABLE:
                # Compress image
                compressed_bytes, compression_info = self._compress_image(
                    source_path, format, max_bytes
                )
                
                # Write compressed image
                with open(temp_path, "wb") as f:
                    f.write(compressed_bytes)
            else:
                # Simple copy (no compression)
                shutil.copy2(source_path, temp_path)
                compression_info = {
                    "compressed": False,
                    "original_size": source_path.stat().st_size,
                    "final_size": None,  # Will be set below
                }
            
            # Atomic rename
            temp_path.replace(target_path)
            
            # Get file size
            bytes_size = target_path.stat().st_size
            if compression_info.get("final_size") is None:
                compression_info["final_size"] = bytes_size
            
            # Determine relative URL (from publish_root)
            try:
                rel_path = target_path.relative_to(self.config.publish_root)
                dest_url = f"/gen/{rel_path.as_posix()}"
            except ValueError:
                # Fallback if relative path calculation fails
                dest_url = f"/gen/{target_path.name}"
            
            # Infer mime type from extension
            ext = target_path.suffix.lower()
            mime_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif"
            }
            mime_type = mime_map.get(ext, "application/octet-stream")
            
            logger.info(f"Published asset: {source_path} -> {target_path} ({bytes_size} bytes)")
            
            # Log to publish_log.jsonl
            self._log_publish(
                asset_id=asset_id,
                target_filename=target_filename,
                source_path=str(source_path),
                dest_path=str(target_path),
                bytes_size=bytes_size
            )
            
            result = {
                "dest_path": str(target_path),
                "dest_url": dest_url,
                "bytes_size": bytes_size,
                "mime_type": mime_type,
                "compression_info": compression_info
            }
            
            return result
        except Exception as e:
            # Clean up temp file on error
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise
    
    def update_manifest(self, manifest_key: str, filename: str):
        """Update manifest.json with published asset.
        
        Uses process-level lock to prevent race conditions.
        
        Args:
            manifest_key: Manifest key (validated by regex)
            filename: Published filename
        """
        # Validate manifest key
        if not validate_manifest_key(manifest_key):
            raise ValueError(
                f"Invalid manifest_key: '{manifest_key}'. "
                f"Must match regex: ^[a-z0-9][a-z0-9._-]{{0,63}}$"
            )
        
        manifest_path = self.config.publish_root / "manifest.json"
        
        # Process-level lock for atomicity
        with self._manifest_lock:
            # Read existing manifest or create empty dict
            if manifest_path.exists():
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Failed to read manifest, creating new one: {e}")
                    manifest = {}
            else:
                manifest = {}
            
            # Update manifest entry (simple key→filename, no arrays in v1)
            manifest[manifest_key] = filename
            
            # Atomic write: write to temp file then rename
            temp_path = manifest_path.with_suffix(".tmp")
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)
                temp_path.replace(manifest_path)
                logger.debug(f"Updated manifest: {manifest_key} -> {filename}")
            except (OSError, json.JSONEncodeError) as e:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                logger.error(f"Failed to update manifest: {e}")
                raise
    
    def _log_publish(
        self,
        asset_id: Optional[str],
        target_filename: Optional[str],
        source_path: str,
        dest_path: str,
        bytes_size: int
    ):
        """Log publish operation to publish_log.jsonl.
        
        Args:
            asset_id: Asset ID (optional)
            target_filename: Target filename (optional)
            source_path: Source file path
            dest_path: Destination file path
            bytes_size: File size in bytes
        """
        log_path = self.config.publish_root / "publish_log.jsonl"
        
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "asset_id": asset_id,
            "target_filename": target_filename,
            "source_path": source_path,
            "dest_path": dest_path,
            "bytes_size": bytes_size
        }
        
        try:
            # Append to log file (create if doesn't exist)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except OSError as e:
            logger.warning(f"Failed to write to publish log: {e}")
    
    def get_publish_info(self) -> Dict[str, Any]:
        """Get publish configuration and status information.
        
        Returns:
            Dict with:
            - project_root: Path and detection method
            - publish_root: Path, exists, writable
            - comfyui_output_root: Path or None
            - comfyui_tried_paths: List of tried paths with validation results
            - status: "ready" | "needs_comfyui_root" | "error"
            - message: Human-readable status
            - warnings: List of warnings
            - config_file: Path to persistent config file
        """
        is_ready, error_code, error_info = self.ensure_ready()
        
        config_file = get_publish_config_file()
        persistent_config = load_publish_config()
        
        result = {
            "project_root": {
                "path": str(self.config.project_root),
                "detection_method": self.config.project_root_method
            },
            "publish_root": {
                "path": str(self.config.publish_root),
                "exists": self.config.publish_root.exists(),
                "writable": os.access(self.config.publish_root, os.W_OK) if self.config.publish_root.exists() else False
            },
            "comfyui_output_root": {
                "path": str(self.config.comfyui_output_root) if self.config.comfyui_output_root else None,
                "exists": self.config.comfyui_output_root.exists() if self.config.comfyui_output_root else False,
                "detection_method": self.config.comfyui_output_method,
                "configured": persistent_config.get("comfyui_output_root") is not None
            },
            "comfyui_tried_paths": self.config.comfyui_tried_paths,
            "config_file": str(config_file),
            "status": "ready" if is_ready else ("needs_comfyui_root" if error_code == "COMFYUI_OUTPUT_ROOT_NOT_FOUND" else "error"),
            "message": error_info.get("message", "Ready to publish") if error_info else "Ready to publish"
        }
        
        if error_info and "warnings" in error_info:
            result["warnings"] = error_info["warnings"]
        elif not is_ready and error_info:
            result["error_code"] = error_code
            if "tried_paths" in error_info:
                result["comfyui_tried_paths"] = error_info["tried_paths"]
            # Add helpful message about set_comfyui_output_root tool
            if error_code == "COMFYUI_OUTPUT_ROOT_NOT_FOUND":
                result["message"] = (
                    f"{error_info.get('message', 'COMFYUI_OUTPUT_ROOT not configured.')} "
                    f"Use the set_comfyui_output_root tool to configure it once."
                )
        
        return result
    
    def set_comfyui_output_root(self, path: Union[str, Path]) -> Dict[str, Any]:
        """Set ComfyUI output root in persistent config.
        
        Args:
            path: Path to ComfyUI output directory
        
        Returns:
            Dict with success status and validation results
        """
        try:
            resolved = Path(path).resolve()
            
            # Validate path exists
            if not resolved.exists():
                return {
                    "error": "COMFYUI_OUTPUT_ROOT_PATH_NOT_FOUND",
                    "message": f"Path does not exist: {resolved}",
                    "path": str(resolved)
                }
            
            if not resolved.is_dir():
                return {
                    "error": "COMFYUI_OUTPUT_ROOT_NOT_DIRECTORY",
                    "message": f"Path is not a directory: {resolved}",
                    "path": str(resolved)
                }
            
            # Validate it looks like ComfyUI output
            is_valid = validate_comfyui_output_root(resolved)
            if not is_valid:
                return {
                    "error": "COMFYUI_OUTPUT_ROOT_INVALID",
                    "message": f"Path does not appear to be a ComfyUI output directory: {resolved}. Expected ComfyUI_*.png files or output/temp subdirectories.",
                    "path": str(resolved),
                    "warning": "Path saved but validation failed. It may still work if ComfyUI outputs are present."
                }
            
            # Save to persistent config
            success = save_publish_config({"comfyui_output_root": str(resolved)})
            if not success:
                return {
                    "error": "CONFIG_SAVE_FAILED",
                    "message": f"Failed to save config to {get_publish_config_file()}",
                    "path": str(resolved)
                }
            
            # Update config in memory
            self.config.comfyui_output_root = resolved
            self.config.comfyui_output_method = "persistent_config"
            self.config.comfyui_tried_paths = []
            
            logger.info(f"Set ComfyUI output root to: {resolved}")
            
            return {
                "success": True,
                "path": str(resolved),
                "message": f"ComfyUI output root configured: {resolved}",
                "config_file": str(get_publish_config_file())
            }
            
        except (OSError, ValueError) as e:
            return {
                "error": "INVALID_PATH",
                "message": f"Invalid path: {e}",
                "path": str(path)
            }
