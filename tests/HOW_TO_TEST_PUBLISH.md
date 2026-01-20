# How to Test Publish Assets Feature

## Overview

The publish assets feature allows you to safely copy ComfyUI-generated assets to a web project directory (e.g., `public/gen/`) with automatic compression and manifest management.

**Key features:**
- **Zero-config setup**: Auto-detects project root and publish directory
- **Persistent configuration**: One-time setup via `set_comfyui_output_root` tool
- **Two modes**: Demo mode (explicit filename) or Library mode (auto-generated)
- **Automatic compression**: Images compressed to meet size limits (default: 600KB)
- **Manifest management**: Automatic `manifest.json` updates for hot-swapping

## Critical Contract

**⚠️ IMPORTANT:** The MCP server must be started from the repository root (cwd). This ensures proper project root detection.

**Other important behaviors:**
- Asset IDs are session-scoped and expire on server restart
- Publishing writes only to `<project_root>/public/gen/` (or `static/gen/`, `assets/gen/`)
- If ComfyUI output root detection fails, use `set_comfyui_output_root` tool

## Running Unit Tests

**From project root:**
```bash
# Run all publish tests
pytest tests/test_publish.py -v

# Run specific test class
pytest tests/test_publish.py::TestPublishManager -v

# Run with coverage
pytest tests/test_publish.py --cov=managers.publish_manager --cov=tools.publish
```

**Note:** Don't run `python test_publish.py` directly - use `pytest` from the project root.

**Troubleshooting pytest errors:**

- **`ImportError: cannot import name 'FixtureDef'`** → Use `python -m pytest` instead of `pytest`
- **Permission errors on Windows** → Clean temp dir: `rmdir /s C:\Users\<user>\AppData\Local\Temp\pytest-of-<user>`
- **Plugin conflicts** → Use virtual environment:
  ```bash
  python -m venv venv
  venv\Scripts\activate  # Windows
  pip install -r requirements.txt
  python -m pytest tests/test_publish.py -v
  ```

## Quick Setup

The publish tools are **always available** - no environment variables required! The system auto-detects:
- Project root (from cwd)
- Publish directory (`public/gen`, `static/gen`, or `assets/gen`)
- ComfyUI output root (best-effort, with fallback to manual config)

### 1. Check Configuration

First, verify your setup:

```python
info = get_publish_info()
# Returns: project_root, publish_root, comfyui_output_root, status, etc.
```

**If `status` is not "ready":**
- Check `comfyui_output_root` - if `None`, use `set_comfyui_output_root` tool
- Check `publish_root` - should be writable
- Review `warnings` for any issues

### 2. Configure ComfyUI Output Root (if needed)

If auto-detection fails, set it once:

```python
result = set_comfyui_output_root("E:/comfyui-desktop/output")
# Returns: success, path, config_file
```

This is saved to persistent config and remembered across restarts:
- Windows: `%APPDATA%/comfyui-mcp-server/publish_config.json`
- Mac: `~/Library/Application Support/comfyui-mcp-server/publish_config.json`
- Linux: `~/.config/comfyui-mcp-server/publish_config.json`

### 3. Start ComfyUI (if not running)

Make sure ComfyUI is running on `http://localhost:8188` (or your configured URL).

### 4. Start the MCP Server

From the repository root:

```bash
python server.py --stdio
```

The publish tools are always registered - no environment variables needed!

## Test Workflow

### 1. Generate an Image

```python
result = generate_image(prompt="a beautiful sunset", return_inline_preview=False)
asset_id = result["asset_id"]
# Save: asset_id
```

### 2. Publish Asset (Demo Mode)

**Demo mode** - explicit filename:

```python
publish_result = publish_asset(
    asset_id="your-asset-id",
    target_filename="hero.webp",  # Explicit filename
    format="webp",                  # Optional: webp, png, jpg (default: webp)
    max_bytes=600_000,              # Optional: size limit (default: 600KB)
    overwrite=True                  # Optional: overwrite existing (default: True)
)
```

**Returns:**
```json
{
  "dest_url": "/gen/hero.webp",
  "dest_path": "E:\\dev\\project\\public\\gen\\hero.webp",
  "bytes_size": 37478,
  "mime_type": "image/webp",
  "width": 512,
  "height": 512,
  "compression_info": {
    "compressed": true,
    "original_size": 457374,
    "quality": 85,
    "downscaled": false,
    "final_size": 37478
  }
}
```

### 3. Publish Asset (Library Mode)

**Library mode** - auto-generated filename with manifest:

```python
publish_result = publish_asset(
    asset_id="your-asset-id",
    manifest_key="hero-image",      # Required when target_filename omitted
    format="webp",                  # Optional
    max_bytes=600_000,              # Optional
    overwrite=True                  # Optional
)
```

**Returns:**
```json
{
  "dest_url": "/gen/asset_0b3eacbc.webp",
  "dest_path": "E:\\dev\\project\\public\\gen\\asset_0b3eacbc.webp",
  "bytes_size": 37478,
  "mime_type": "image/webp",
  "width": 512,
  "height": 512,
  "compression_info": {...}
}
```

The manifest (`public/gen/manifest.json`) is automatically updated:
```json
{
  "hero-image": "asset_0b3eacbc.webp"
}
```

### 4. Verify

- **File exists:** Check `public/gen/hero.webp` (or auto-generated filename)
- **Manifest updated:** Check `public/gen/manifest.json` (if `manifest_key` provided)
- **Log entry:** Check `public/gen/publish_log.jsonl` has new entry
- **Compression:** Check `compression_info` in response

## Two Modes Explained

### Demo Mode
- **Use when:** You want a specific, deterministic filename
- **Provide:** `target_filename` (e.g., `"hero.webp"`)
- **Manifest:** Not updated (unless you also provide `manifest_key`)
- **Example:** `publish_asset(asset_id="...", target_filename="hero.webp")`

### Library Mode
- **Use when:** You want auto-generated filenames with manifest tracking
- **Provide:** `manifest_key` (required), omit `target_filename`
- **Manifest:** Automatically updated with `manifest_key → filename` mapping
- **Filename:** Auto-generated as `asset_<shortid>.webp` (or specified format)
- **Example:** `publish_asset(asset_id="...", manifest_key="hero")`

## Error Codes

The system returns machine-readable error codes:

- **`ASSET_NOT_FOUND_OR_EXPIRED`**: Asset not in current session (session-scoped)
- **`INVALID_TARGET_FILENAME`**: Filename doesn't match regex `^[a-z0-9][a-z0-9._-]{0,63}\.(webp|png|jpg|jpeg)$`
- **`INVALID_MANIFEST_KEY`**: Manifest key doesn't match regex `^[a-z0-9][a-z0-9._-]{0,63}$`
- **`MANIFEST_KEY_REQUIRED`**: `manifest_key` required when `target_filename` omitted
- **`SOURCE_PATH_OUTSIDE_ROOT`**: Source file outside ComfyUI output root
- **`PATH_TRAVERSAL_DETECTED`**: Path traversal attempt detected
- **`COMFYUI_OUTPUT_ROOT_NOT_FOUND`**: ComfyUI output root not configured
- **`PUBLISH_ROOT_NOT_WRITABLE`**: Publish directory not writable
- **`PUBLISH_FAILED`**: Copy/compression operation failed

## Compression Details

Images are automatically compressed using a deterministic compression ladder:

1. **Quality progression**: [85, 75, 65, 55, 45, 35]
2. **Downscale factors**: [1.0, 0.9, 0.75, 0.6, 0.5] (if needed)
3. **Format conversion**: PNG/JPEG → WebP (if format="webp")
4. **Size limit**: Enforced via `max_bytes` (default: 600KB)

The compression ladder tries quality levels first, then downscaling if needed, until the size limit is met.

## Quick Test Script

```python
# 1. Check configuration
info = get_publish_info()
assert info["status"] == "ready"

# 2. Configure ComfyUI output (if needed)
if not info["comfyui_output_root"]["path"]:
    set_comfyui_output_root("E:/comfyui-desktop/output")

# 3. Generate image
result = generate_image(prompt="test image")
asset_id = result["asset_id"]

# 4. Publish (demo mode)
publish = publish_asset(asset_id=asset_id, target_filename="test.webp")

# 5. Verify
assert "dest_url" in publish
assert publish["dest_url"] == "/gen/test.webp"
assert "compression_info" in publish
print(f"✅ Published to {publish['dest_url']} ({publish['bytes_size']} bytes)")

# 6. Publish (library mode)
publish2 = publish_asset(asset_id=asset_id, manifest_key="test-image")
assert "dest_url" in publish2
print(f"✅ Published to {publish2['dest_url']} with manifest key 'test-image'")
```

## Troubleshooting

- **Tool not appearing in MCP** → Tools are always registered; check server logs for errors
- **"COMFYUI_OUTPUT_ROOT_NOT_FOUND"** → Use `set_comfyui_output_root` tool to configure
- **"Asset not found or expired"** → Assets are session-scoped; generate new asset in same session
- **"MANIFEST_KEY_REQUIRED"** → Provide `manifest_key` when omitting `target_filename` (library mode)
- **"INVALID_TARGET_FILENAME"** → Filename must match regex (lowercase, alphanumeric, dots/dashes/underscores, valid extension)
- **"Source file does not exist"** → Check ComfyUI output directory path
- **Compression fails** → Image may be too large; check `compression_info` for details
- **Server logs show errors** → Check `get_publish_info()` for configuration status
