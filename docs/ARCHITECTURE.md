# Architecture

High-level architecture and design decisions for ComfyUI MCP Server.

## Overview

The server bridges MCP (Model Context Protocol) and ComfyUI, providing a standardized interface for AI agents to generate media through ComfyUI workflows.

## Design Decisions

These foundational decisions shape the entire architecture and should be understood before diving into implementation details.

### Why Streamable-HTTP?

- Better scalability than WebSocket
- Cloud-ready (works behind load balancers)
- Standard HTTP tooling
- Stateless (easier to scale horizontally)

### Why Stable Asset Identity?

**Problem:** URL-based identity breaks with hostname/port changes.

**Solution:** Use `(filename, subfolder, type)` tuple as stable identity:
- Works across different ComfyUI instances (localhost, 127.0.0.1, different ports)
- Resilient to ComfyUI restarts for already-known output identities (URL computation)
- URLs computed on-the-fly from base_url
- O(1) lookups via dual-index structure

**Benefits:**
- Robust to configuration changes
- No "thor:8188" hostname bugs
- Portable across deployments

### Why UUID Asset IDs?

- Globally unique external reference
- Opaque (doesn't leak internal structure)
- Standard format
- Separate from stable identity (internal lookup)

### Why Full Provenance Storage?

**Stored Data:**
- `comfy_history`: Full `/history/{prompt_id}` response snapshot
- `submitted_workflow`: Original workflow JSON submitted to ComfyUI

**Benefits:**
- Free reproducibility (can regenerate with exact parameters)
- Debugging becomes trivial (see exactly what was submitted)
- Enables `regenerate()` tool without re-specifying everything
- Complete audit trail

**Trade-offs:**
- History snapshots can be large for complex workflows
- TTL-based expiration (24h) limits growth
- Future: Consider compression or selective field storage

### Why TTL Instead of Manual Deletion?

- Automatic cleanup reduces memory usage
- No manual management needed
- Predictable behavior
- Configurable per deployment

### Why Separate view_image Tool?

- Lazy loading: Only fetch/process when needed
- Size control: Enforce limits at viewing time
- Format conversion: Optimize for display
- Separation of concerns: Generation vs. viewing

### Why Thin Adapter Architecture?

The server delegates execution to ComfyUI rather than reimplementing:
- **Queue logic**: Direct passthrough to `/queue` endpoint
- **History tracking**: Direct passthrough to `/history` endpoint
- **Job cancellation**: Direct passthrough to `/queue` with delete action

**Benefits:**
- No sync issues (ComfyUI is source of truth)
- Minimal code surface
- Leverages ComfyUI's native capabilities
- Easier to maintain (changes in ComfyUI automatically reflected)

## Core Components

### WorkflowManager

**Purpose**: Discovers, loads, and processes ComfyUI workflow JSON files.

**Responsibilities:**
- Scan `workflows/` directory for JSON files
- Extract parameters from `PARAM_*` placeholders
- Build `WorkflowToolDefinition` objects
- Render workflows with provided parameters
- Apply constrained overrides (for `run_workflow`)

**Key Methods:**
- `_load_workflows()`: Discovery and loading
- `_extract_parameters()`: Placeholder parsing
- `render_workflow()`: Parameter substitution
- `apply_workflow_overrides()`: Constrained parameter updates

### DefaultsManager

**Purpose**: Manages default values with configurable precedence.

**Precedence Order:**
1. Per-call values (explicit parameters)
2. Runtime defaults (`set_defaults` tool)
3. Config file (`~/.config/comfy-mcp/config.json`)
4. Environment variables
5. Hardcoded defaults

**Key Methods:**
- `get_default()`: Resolve value with precedence
- `set_defaults()`: Set runtime defaults
- `persist_defaults()`: Write to config file

### AssetRegistry

**Purpose**: Track generated assets for viewing and management.

**Features:**
- UUID-based asset IDs for external reference
- Stable identity using `(filename, subfolder, type)` tuple (robust to URL changes)
- TTL-based expiration (default 24 hours)
- O(1) lookups via dual-index structure (`_assets` and `_asset_key_to_id`)
- Full provenance storage (`comfy_history`, `submitted_workflow`)
- Session tracking for conversation isolation
- Automatic cleanup of expired assets

**Key Methods:**
- `register_asset()`: Register new asset with stable identity, return `AssetRecord`
- `get_asset()`: Retrieve by ID (checks expiration)
- `list_assets()`: List assets with optional filtering (workflow_id, session_id)
- `cleanup_expired()`: Remove expired assets

**Stable Identity Design:**
Assets are identified by `(filename, subfolder, folder_type)` instead of URLs, making the system robust to:
- Hostname/port/base-url changes
- Resilient to ComfyUI restarts for already-known output identities

URLs are computed on-the-fly from the stable identity when needed.

**Note:** Stable identity prevents URL/base changes from breaking computed URLs, but does not imply persistence of the asset registry across MCP server restarts.

### ComfyUIClient

**Purpose**: Interface with ComfyUI API as a thin adapter.

**Responsibilities:**
- Queue workflows via `/prompt` endpoint
- Poll for completion via `/history/{prompt_id}`
- Extract asset info (filename, subfolder, type) from outputs (stable identity)
- Fetch asset metadata (size, dimensions, mime type)
- Direct passthrough to ComfyUI queue and history endpoints
- Cancel queued/running jobs

**Key Methods:**
- `run_custom_workflow()`: Execute workflow and wait for completion, returns stable identity + provenance
- `_queue_workflow()`: Submit workflow to ComfyUI
- `_wait_for_prompt()`: Poll until completion
- `_extract_first_asset_info()`: Extract `(filename, subfolder, type)` from outputs
- `get_queue()`: Direct passthrough to `/queue` endpoint
- `get_history(prompt_id)`: Direct passthrough to `/history` endpoint
- `cancel_prompt(prompt_id)`: Cancel queued or running jobs

**Thin Adapter Philosophy:**
The client delegates execution to ComfyUI rather than reimplementing queue logic. ComfyUI is the source of truth for job state.

## Workflow System

### Discovery

1. `WorkflowManager` scans `workflows/` directory
2. Loads JSON files (skips `.meta.json` files)
3. Extracts `PARAM_*` placeholders
4. Builds parameter definitions with types and bindings
5. Creates `WorkflowToolDefinition` objects

### Parameter Extraction

**Placeholder Format**: `PARAM_<TYPE?>_<NAME>`

**Examples:**
- `PARAM_PROMPT` → `prompt: str` (required)
- `PARAM_INT_STEPS` → `steps: int` (optional)
- `PARAM_FLOAT_CFG` → `cfg: float` (optional)

**Binding**: Maps to `[node_id, input_name]` in workflow JSON

### Tool Registration

1. `register_workflow_generation_tools()` iterates over definitions
2. Creates dynamic tool functions with proper signatures
3. Handles type coercion (JSON-RPC strings → Python types)
4. Registers with FastMCP via `@mcp.tool()` decorator

### Execution Flow

1. Tool called with parameters
2. `render_workflow()` substitutes placeholders with values
3. Defaults applied for missing optional parameters
4. Workflow queued to ComfyUI via `/prompt` endpoint
5. Server polls for completion via `/history/{prompt_id}`
6. Asset info extracted from outputs: `(filename, subfolder, type)` (stable identity)
7. Full history snapshot fetched from ComfyUI
8. Asset registered in `AssetRegistry` with:
   - Stable identity (filename, subfolder, folder_type)
   - Provenance data (`comfy_history`, `submitted_workflow`)
   - Session ID (if provided)
9. Asset URL computed from stable identity
10. Response returned with `asset_id`, `asset_url`, and metadata

## Asset Lifecycle

### Generation

1. Workflow executes in ComfyUI
2. Asset saved to ComfyUI output directory
3. ComfyUI returns output metadata

### Registration

1. `AssetRegistry.register_asset()` called with `(filename, subfolder, type)` stable identity
2. UUID generated for `asset_id` (external reference)
3. Stable identity key created: `f"{folder_type}:{subfolder}:{filename}"`
4. Deduplication check: if asset with same identity exists and not expired, return existing
5. Expiration time calculated (now + TTL)
6. `AssetRecord` created with:
   - Stable identity fields (filename, subfolder, folder_type)
   - Provenance data (`comfy_history`, `submitted_workflow`)
   - Session ID (for conversation isolation)
7. Dual-index storage:
   - `_assets[asset_id]` → `AssetRecord` (UUID lookup)
   - `_asset_key_to_id[asset_key]` → `asset_id` (identity lookup)

### Viewing

1. `view_image` called with `asset_id`
2. `AssetRegistry.get_asset()` retrieves record by UUID
3. Expiration checked (returns None if expired)
4. Asset URL computed from stable identity: `get_asset_url(base_url)`
5. Asset bytes fetched from ComfyUI `/view` endpoint (URL-encoded for special characters)
6. Image processed (downscale, re-encode as WebP)
7. Base64-encoded thumbnail returned

**URL Computation:**
URLs are computed on-the-fly from stable identity, ensuring they work even if ComfyUI base URL changes:
```python
asset_url = f"{base_url}/view?filename={quote(filename)}&subfolder={quote(subfolder)}&type={folder_type}"
```

### Expiration

1. Assets expire after TTL (default 24 hours)
2. `cleanup_expired()` removes expired records
3. Called periodically during `view_image` operations

## Image Processing Pipeline

### Purpose

Convert large images to small, context-friendly thumbnails for inline display in chat (i.e. for image injection into AI context).

### Constraints

- **Size limit**: 100KB base64 payload (configurable)
- **Dimension limit**: 512px max dimension (configurable)
- **Format**: WebP (efficient compression)

### Process

1. **Fetch**: Download image bytes from ComfyUI
2. **Load**: Open with Pillow, apply EXIF orientation
3. **Downscale**: Resize to fit within `max_dim` (maintain aspect ratio)
4. **Optimize**: Quality ladder (70 → 55 → 40) to fit budget
5. **Encode**: Save as WebP, base64 encode
6. **Validate**: Check total payload size (base64 + data URI prefix)
7. **Cache**: Store result (LRU cache, max 100 entries)

### Why WebP?

- Better compression than PNG/JPEG
- Supports transparency
- Widely supported in modern clients
- Good quality/size tradeoff

### Why Thumbnails Only?

- Context window limits in AI chat interfaces
- Base64 encoding adds ~33% overhead
- Large images cause context bloat and crashes
- Thumbnails provide visual feedback without cost

## Default Value System

### Why Multiple Sources?

Different use cases need different defaults:
- **Hardcoded**: Sensible defaults for new users
- **Config file**: Persistent preferences
- **Runtime**: Session-specific overrides
- **Environment**: Deployment-specific settings

### Resolution Algorithm

```python
def get_default(namespace, key, provided_value):
    if provided_value is not None:
        return provided_value  # Explicit wins
    
    # Check in order of precedence
    if key in runtime_defaults[namespace]:
        return runtime_defaults[namespace][key]
    if key in config_defaults[namespace]:
        return config_defaults[namespace][key]
    if key in env_defaults[namespace]:
        return env_defaults[namespace][key]
    if key in hardcoded_defaults[namespace]:
        return hardcoded_defaults[namespace][key]
    
    return None  # No default found
```

## Security Considerations

### Path Traversal Protection

Workflow IDs are sanitized before file access:

```python
safe_id = workflow_id.replace("/", "_").replace("\\", "_").replace("..", "_")
safe_id = "".join(c for c in safe_id if c.isalnum() or c in ("_", "-"))
```

Resolved paths are validated to be within `workflows/` directory.

### URL Encoding

Special characters in filenames are properly URL-encoded when constructing asset URLs:

```python
from urllib.parse import quote
encoded_filename = quote(filename, safe='')
encoded_subfolder = quote(subfolder, safe='') if subfolder else ''
```

Prevents injection attacks and ensures valid URLs for all filenames.

### Asset Access Control

- Only assets generated by this server can be viewed
- `asset_id` must exist in registry (UUID lookup)
- Expired assets are automatically removed
- No direct file system access from tools
- Asset URLs computed from stable identity (validated)

### Parameter Validation

- Overrides constrained to declared parameters
- Type coercion with validation
- Constraints enforced (min/max/enum) if metadata provided
- Workflow metadata (`.meta.json`) provides additional validation

## Performance Considerations

### Caching

- **Workflows**: Cached after first load (in-memory)
- **Image previews**: LRU cache (max 100 entries)
- **Model list**: Cached in `ComfyUIClient` (refreshed on init)

### Polling Strategy

- 1-second intervals
- Maximum 30 attempts (30 seconds)
- Exponential backoff considered but not implemented

### Memory Management

- Asset registry: In-memory dict with dual-index structure
  - `_assets`: UUID → AssetRecord (O(1) lookup)
  - `_asset_key_to_id`: Stable identity → UUID (O(1) lookup)
- Image cache: Limited to 100 entries (LRU)
- Expired assets cleaned up automatically
- Provenance data: Stored as-is (no compression), TTL limits growth

### Lookup Performance

- Asset by ID: O(1) via `_assets` dict
- Asset by identity: O(1) via `_asset_key_to_id` dict
- List assets: O(n log n) for sorting (n = total assets, typically small)
- URL encoding: Applied only when computing URLs (not stored)

### History Snapshot Size

`comfy_history` can be large for complex workflows:
- Stored as-is (no compression in v1)
- TTL-based expiration (24h) limits growth
- Future: Consider compression or selective field storage

## Job Management

The server provides tools for monitoring and controlling ComfyUI job execution, enabling AI agents to work asynchronously.

### Queue Status

`get_queue_status()` provides async awareness:
- Check if ComfyUI is busy before submitting new jobs
- Monitor queue depth
- Determine if a job is queued vs running

**Implementation:**
Direct passthrough to ComfyUI `/queue` endpoint - no reimplementation of queue logic.

### Job Polling

`get_job(prompt_id)` polls job completion:
- Checks queue first (running/queued status)
- Falls back to history endpoint for completed jobs
- Returns structured status: `completed`, `running`, `queued`, `error`, `not_found`
- Includes full history snapshot when available

**Error Handling:**
- Gracefully handles missing prompt_ids
- Distinguishes between "not found" and "error" states
- Handles ComfyUI unavailability

### Asset Browsing

`list_assets()` enables AI memory and iteration:
- Lists recently generated assets
- Filterable by `workflow_id` (e.g., only images)
- Filterable by `session_id` (conversation isolation)
- Returns stable identity for reliable follow-ups

### Asset Metadata

`get_asset_metadata(asset_id)` provides full provenance:
- Complete asset details (dimensions, size, type)
- Full ComfyUI history snapshot
- Original submitted workflow (enables regeneration)
- Creation and expiration timestamps

### Regeneration

`regenerate(asset_id, param_overrides)` enables iteration:
- Retrieves original workflow from `submitted_workflow`
- Applies parameter overrides (e.g., `{"steps": 30, "cfg": 10.0}`)
- Re-submits to ComfyUI with modifications
- Preserves session ID for conversation continuity

**Implementation:**
Uses deep copy of stored workflow, applies overrides via `_update_workflow_params()`, handles seed separately.

### Cancellation

`cancel_job(prompt_id)` cancels queued or running jobs:
- Direct passthrough to ComfyUI `/queue` with delete action
- Provides user control and resource management

## Publish System

The publish system enables AI agents to safely copy ComfyUI-generated assets into web project directories with deterministic filenames, automatic compression, and manifest management.

### Purpose

Bridge the gap between ComfyUI's output directory and web project asset directories:
- Copy generated assets to project's web directory (e.g., `public/gen/`)
- Enforce provenance (only assets from current session)
- Provide deterministic compression to meet size limits
- Support two modes: explicit filenames (demo) and manifest-based (library)
- Auto-detect configuration with conservative fallbacks

### Core Components

#### PublishConfig

**Purpose**: Manages publish configuration with auto-detection and persistent storage.

**Responsibilities:**
- Auto-detect project root (primary: `cwd`, fallback: search for markers)
- Auto-detect publish root (`public/gen`, `static/gen`, or `assets/gen`)
- Auto-detect ComfyUI output root (tight candidate list, validated)
- Load/save persistent configuration (platform-specific)
- Track detection methods and tried paths for debugging

**Key Methods:**
- `detect_project_root()`: Find project root with conservative fallback
- `get_default_publish_root()`: Infer publish directory from project structure
- `detect_comfyui_output_root()`: Best-effort detection with validation
- `load_publish_config()` / `save_publish_config()`: Persistent config management

**Configuration Priority:**
1. Explicit parameters (constructor args)
2. Persistent config file (platform-specific)
3. Auto-detection (best-effort)

#### PublishManager

**Purpose**: Manages safe asset publishing with path validation, compression, and manifest updates.

**Responsibilities:**
- Validate source paths (must be within ComfyUI output root)
- Validate target paths (must be within publish root)
- Compress images using deterministic ladder
- Update manifest.json atomically
- Provide status reporting via `get_publish_info()`

**Key Methods:**
- `resolve_source_path()`: Validate and canonicalize source path
- `resolve_target_path()`: Validate and canonicalize target path
- `_compress_image()`: Deterministic compression ladder
- `copy_asset()`: Copy with optional compression and atomic write
- `update_manifest()`: Atomic manifest update with locking
- `ensure_ready()`: Centralized configuration validation
- `get_publish_info()`: Comprehensive status reporting
- `set_comfyui_output_root()`: Configure and persist ComfyUI output root

### Publishing Flow

1. **Configuration Check**: `ensure_ready()` validates publish root and ComfyUI output root
2. **Asset Lookup**: Retrieve asset from `AssetRegistry` by `asset_id` (session-scoped)
3. **Source Resolution**: `resolve_source_path()` validates source is within ComfyUI output root
4. **Target Resolution**: `resolve_target_path()` validates target filename and resolves path
5. **Compression** (if needed): Deterministic compression ladder to meet `max_bytes` limit
6. **Atomic Copy**: Write to temporary file, then atomic rename
7. **Manifest Update** (if `manifest_key` provided): Atomic read/modify/write with lock

### Two Publishing Modes

**Demo Mode** (explicit filename):
- Agent provides `target_filename` (e.g., `"hero.webp"`)
- Deterministic output location: `<publish_root>/<target_filename>`
- Manifest not updated unless `manifest_key` also provided
- Use case: Direct file references, simple deployments

**Library Mode** (auto-generated with manifest):
- Agent provides `manifest_key`, omits `target_filename`
- Filename auto-generated: `asset_<shortid>.webp`
- Manifest automatically updated: `{"manifest_key": "filename"}`
- Use case: Hot-swappable assets, dynamic loading via manifest

### Key Design Decisions

#### Path Safety and Canonicalization

**Problem**: Path traversal attacks, symlink issues, relative path confusion.

**Solution**: All paths are canonicalized before use:
```python
def canonicalize_path(path: Union[str, Path], must_exist: bool = True) -> Path:
    """Resolve to absolute real path, handling symlinks."""
    resolved = Path(path).resolve(strict=must_exist)
    return resolved
```

**Containment Checks**: `is_within()` validates child paths are within parent directories:
```python
def is_within(child_path: Path, parent_path: Path, child_must_exist: bool = True) -> bool:
    """Check if child_path is within parent_path."""
    child_real = canonicalize_path(child_path, must_exist=child_must_exist)
    parent_real = canonicalize_path(parent_path, must_exist=True)
    try:
        child_real.relative_to(parent_real)
        return True
    except ValueError:
        return False
```

**Non-existent Paths**: `must_exist=False` parameter allows validation of target paths before creation, preventing path traversal even for files that don't exist yet.

**Benefits:**
- Prevents `../../../etc/passwd` style attacks
- Handles symlinks correctly (resolves to real path)
- Works for both existing and non-existent paths
- Clear error messages when containment fails

#### Provenance Enforcement

**Problem**: Prevent arbitrary filesystem copying, ensure assets come from ComfyUI.

**Solution**: Multi-layer validation:
1. **Session-scoped `asset_id`**: Only assets registered in current session can be published
2. **Source Validation**: Source paths must be within configured ComfyUI output root
3. **Asset Registry Integration**: Uses existing `AssetRegistry` to verify asset identity

**Implementation:**
- `asset_id` lookup fails if asset not in current session (expired or from different server instance)
- Source path canonicalized and checked against `comfyui_output_root` (real path comparison)
- No direct file system access from tools - all paths validated through manager

**Benefits:**
- Prevents copying arbitrary files
- Ensures assets come from ComfyUI runs
- Session isolation prevents cross-contamination
- Clear error messages when provenance fails

#### Persistent Configuration

**Problem**: Environment variables are ephemeral and not user-friendly for one-time setup.

**Solution**: Platform-specific config files with tool-based configuration:
- **Windows**: `%APPDATA%/comfyui-mcp-server/publish_config.json`
- **Mac**: `~/Library/Application Support/comfyui-mcp-server/publish_config.json`
- **Linux**: `~/.config/comfyui-mcp-server/publish_config.json`

**Priority Order:**
1. Explicit parameter (constructor args)
2. Persistent config file (via `set_comfyui_output_root()` tool)
3. Auto-detection (best-effort, tight candidate list)

**Tool-based Configuration**: `set_comfyui_output_root(path)` tool:
- Validates path exists and looks like ComfyUI output directory
- Saves to persistent config (merged with existing)
- Provides clear error messages if validation fails

**Benefits:**
- One-time setup persists across restarts
- User-friendly (no environment variable management)
- Platform-appropriate storage locations
- Clear error messages guide configuration

#### Auto-detection with Conservative Fallbacks

**Project Root Detection:**
- **Primary contract**: Server should be started from repo root (`cwd`)
- **Conservative fallback**: Search upward (max 10 levels) for project markers:
  - `.git`, `package.json`, `pyproject.toml`, `Cargo.toml`
- **Ambiguity handling**: If multiple markers found at different levels, raise error with guidance
- **Best guess**: If no markers found, use `cwd` with warning

**Publish Root Detection:**
- Tries in order: `public/gen` → `static/gen` → `assets/gen`
- Uses first parent directory that exists
- Creates directory if needed
- Defaults to `public/gen` if none exist

**ComfyUI Output Root Detection:**
- **Tight candidate list**: 2-5 specific paths (no broad scanning)
- **Priority**: Persistent config → specific candidates (e.g., `comfyui-desktop/output`)
- **Validation**: Pattern matching (ComfyUI_*.png files, image files, output/temp subdirs)
- **Reporting**: All tried paths returned with validation results

**Benefits:**
- Zero-config in common cases
- Conservative (doesn't scan entire filesystem)
- Clear error messages with tried paths
- User can override with `set_comfyui_output_root()` tool

#### Deterministic Compression Ladder

**Problem**: Need predictable compression to meet size limits without heuristics.

**Solution**: Fixed sequence of compression attempts:
1. **Quality progression**: [85, 75, 65, 55, 45, 35]
2. **Downscale factors**: [1.0, 0.9, 0.75, 0.6, 0.5] (if needed)
3. **Format conversion**: PNG/JPEG → WebP (if `format="webp"`)

**Algorithm:**
```python
for downscale_factor in [1.0, 0.9, 0.75, 0.6, 0.5]:
    im_resized = im.resize(new_size) if downscale_factor < 1.0 else im
    for quality in [85, 75, 65, 55, 45, 35]:
        compressed_bytes = save_with_quality(im_resized, quality)
        if len(compressed_bytes) <= max_bytes:
            return compressed_bytes, compression_info
```

**Compression Info Returned:**
- `compressed`: Whether compression was applied
- `original_size`: Original file size
- `final_size`: Compressed file size
- `quality`: Quality level used
- `original_dimensions`: Original image dimensions
- `final_dimensions`: Final image dimensions (if downscaled)
- `downscaled`: Whether downscaling was applied

**Benefits:**
- Reproducible results (same input → same output)
- Clear failure modes (can't compress below limit)
- Detailed feedback for debugging
- Predictable behavior for agents

#### Atomic Manifest Updates

**Problem**: Race conditions when multiple processes update `manifest.json`.

**Solution**: Process-level locking with atomic writes:
```python
_manifest_lock = threading.Lock()  # Process-level lock

def update_manifest(self, manifest_key: str, filename: str):
    with self._manifest_lock:
        # Read existing manifest
        manifest = json.load(manifest_path) if manifest_path.exists() else {}
        # Update entry
        manifest[manifest_key] = filename
        # Atomic write: temp file + rename
        temp_path = manifest_path.with_suffix(".tmp")
        json.dump(manifest, temp_path)
        temp_path.replace(manifest_path)  # Atomic on most filesystems
```

**Benefits:**
- Prevents corruption from concurrent updates
- Atomic writes prevent partial updates
- Simple key-value format (no arrays in v1)
- Fast (in-memory lock, minimal I/O)

#### Strict Validation

**Filename Validation:**
- Regex: `^[a-z0-9][a-z0-9._-]{0,63}\.(webp|png|jpg|jpeg)$`
- Prevents path traversal (`../`, `/`, `\`)
- Enforces safe naming (lowercase, alphanumeric, dots, dashes, underscores)
- Length limit: 64 characters (including extension)

**Manifest Key Validation:**
- Regex: `^[a-z0-9][a-z0-9._-]{0,63}$`
- Same pattern as filename but without extension
- Prevents injection and ensures safe keys

**Early Validation**: All validation happens before any file operations:
- Filename validated before path resolution
- Manifest key validated before manifest update
- Source path validated before file access
- Target path validated before write

**Benefits:**
- Prevents path traversal attacks
- Clear error messages before operations
- Consistent validation across all entry points

#### Operational Honesty

**Status Reporting**: `get_publish_info()` provides comprehensive configuration status:
- Project root (path and detection method)
- Publish root (path and writability)
- ComfyUI output root (path, method, validation status)
- All tried paths with validation results
- Status: `"ready"` | `"needs_comfyui_root"` | `"error"`
- Human-readable messages and warnings

**Machine-readable Errors**: Standardized error codes:
- `ASSET_NOT_FOUND_OR_EXPIRED`: Asset not in current session
- `COMFYUI_OUTPUT_ROOT_NOT_FOUND`: ComfyUI output root not configured
- `INVALID_TARGET_FILENAME`: Filename doesn't match regex
- `SOURCE_PATH_OUTSIDE_ROOT`: Source file outside ComfyUI output root
- `PATH_TRAVERSAL_DETECTED`: Path traversal attempt detected
- `PUBLISH_ROOT_NOT_WRITABLE`: Publish directory not writable

**Tried Paths Reporting**: Shows all attempted detection paths with validation results:
```json
{
  "comfyui_tried_paths": [
    {"path": "E:/comfyui-desktop/output", "exists": true, "is_valid": true, "source": "persistent_config"},
    {"path": "E:/ComfyUI/output", "exists": false, "is_valid": false, "source": "candidate"}
  ]
}
```

**Benefits:**
- Agents can diagnose configuration issues
- Clear guidance for fixing problems
- No silent failures
- Debugging information available

### Security Considerations

#### Path Traversal Prevention

**Multi-layer Defense:**
1. **Filename Validation**: Regex prevents `../`, `/`, `\` in filenames
2. **Path Canonicalization**: All paths resolved to absolute real paths
3. **Containment Checks**: `is_within()` validates child within parent
4. **Source Validation**: Source must be within ComfyUI output root
5. **Target Validation**: Target must be within publish root

**Example Attack Prevention:**
```python
# Attack attempt: "../../../etc/passwd"
target_filename = "../../../etc/passwd"  # Blocked by regex validation

# Attack attempt: symlink to sensitive file
source_path = canonicalize_path(symlink)  # Resolves to real path
is_within(source_path, comfyui_output_root)  # Validates containment
```

#### Provenance Enforcement

- Only assets from current session can be published (`asset_id` lookup)
- Source paths validated against ComfyUI output root
- No arbitrary file copying
- Session isolation prevents cross-contamination

#### Atomic Operations

- Manifest updates use process-level locking
- File writes use temporary file + atomic rename
- Prevents corruption from concurrent access
- Prevents partial updates

### Performance Considerations

#### Compression Performance

- **Deterministic Ladder**: Fixed sequence means predictable performance
- **Early Exit**: Stops at first successful compression attempt
- **Quality vs. Size**: Tries quality first (faster), then downscaling (slower)
- **Format Conversion**: WebP encoding is CPU-intensive but provides best compression

#### Path Resolution

- **Canonicalization**: `Path.resolve()` is O(1) for most cases (cached by filesystem)
- **Containment Check**: `relative_to()` is O(1) for valid paths
- **Validation**: Regex validation is O(n) where n is filename length (typically < 64 chars)

#### Manifest Updates

- **Lock Contention**: Process-level lock prevents concurrent updates (acceptable for low-frequency operations)
- **Atomic Writes**: Temporary file + rename is atomic on most filesystems
- **JSON Parsing**: Small manifest files (< 1KB typically) parse quickly

#### Auto-detection

- **Project Root**: Upward search limited to 10 levels (O(10) file checks)
- **Publish Root**: 3 candidate checks (O(3) directory checks)
- **ComfyUI Output Root**: 2-5 candidate checks with validation (O(5) file system checks)
- **Caching**: Detection results cached in `PublishConfig` instance

## Future Considerations

### Potential Improvements

- **Persistent asset registry**: Database backend for production (SQLite option)
- **History compression**: Compress large `comfy_history` snapshots
- **Rate limiting**: Prevent spam polling in `get_job()`
- **Health checks**: ComfyUI connectivity monitoring
- **Metrics**: Generation time, success rates
- **Batch operations**: Generate multiple assets
- **Streaming**: Real-time progress updates
- **Session filtering enhancements**: More granular conversation isolation

### Scalability

Current design is single-instance. For scale:
- Add database backend for asset registry
- Implement distributed locking for workflow execution
- Add queue system for high-volume scenarios
- Consider caching layer for ComfyUI responses
