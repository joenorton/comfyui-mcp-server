# API Reference

Complete technical reference for ComfyUI MCP Server tools, parameters, and behavior.

## Table of Contents

- [Generation Tools](#generation-tools)
- [Viewing Tools](#viewing-tools)
- [Job Management Tools](#job-management-tools)
- [Asset Management Tools](#asset-management-tools)
- [Configuration Tools](#configuration-tools)
- [Workflow Tools](#workflow-tools)
- [Parameters](#parameters)
- [Return Values](#return-values)
- [Error Handling](#error-handling)
- [Limits and Constraints](#limits-and-constraints)

## Generation Tools

### generate_image

Generate images using Stable Diffusion workflows.

**Signature:**
```python
generate_image(
    prompt: str,
    seed: int | None = None,
    width: int | None = None,
    height: int | None = None,
    model: str | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    denoise: float | None = None,
    negative_prompt: str | None = None,
    return_inline_preview: bool = False
) -> dict
```

**Required Parameters:**
- `prompt` (str): Text description of the image to generate

**Optional Parameters:**
- `seed` (int): Random seed. Auto-generated if not provided.
- `width` (int): Image width in pixels. Default: 512
- `height` (int): Image height in pixels. Default: 512
- `model` (str): Checkpoint model name. Default: "v1-5-pruned-emaonly.ckpt"
- `steps` (int): Number of sampling steps. Default: 20
- `cfg` (float): Classifier-free guidance scale. Default: 8.0
- `sampler_name` (str): Sampling method. Default: "euler"
- `scheduler` (str): Scheduler type. Default: "normal"
- `denoise` (float): Denoising strength (0.0-1.0). Default: 1.0
- `negative_prompt` (str): Negative prompt. Default: "text, watermark"
- `return_inline_preview` (bool): Include thumbnail in response. Default: False

**Returns:**
```json
{
  "asset_id": "uuid-string",
  "asset_url": "http://localhost:8188/view?filename=...",
  "image_url": "http://localhost:8188/view?filename=...",
  "filename": "ComfyUI_00265_.png",
  "subfolder": "",
  "folder_type": "output",
  "workflow_id": "generate_image",
  "prompt_id": "uuid-string",
  "tool": "generate_image",
  "mime_type": "image/png",
  "width": 512,
  "height": 512,
  "bytes_size": 497648,
  "inline_preview_base64": "data:image/webp;base64,..."  // if return_inline_preview=true
}
```

**Examples:**
```python
# Minimal call
result = generate_image(prompt="a cat")

# Full parameters
result = generate_image(
    prompt="cyberpunk cityscape",
    width=1024,
    height=768,
    model="sd_xl_base_1.0.safetensors",
    steps=30,
    cfg=7.5,
    sampler_name="dpmpp_2m",
    negative_prompt="blurry, low quality"
)
```

### generate_song

Generate audio using AceStep workflows.

**Signature:**
```python
generate_song(
    tags: str,
    lyrics: str,
    seed: int | None = None,
    steps: int | None = None,
    cfg: float | None = None,
    seconds: int | None = None,
    lyrics_strength: float | None = None
) -> dict
```

**Required Parameters:**
- `tags` (str): Comma-separated descriptive tags (e.g., "electronic, ambient")
- `lyrics` (str): Full lyric text

**Optional Parameters:**
- `seed` (int): Random seed. Auto-generated if not provided.
- `steps` (int): Number of sampling steps. Default: 50
- `cfg` (float): Classifier-free guidance scale. Default: 5.0
- `seconds` (int): Audio duration in seconds. Default: 60
- `lyrics_strength` (float): Lyrics influence (0.0-1.0). Default: 0.99

**Returns:**
```json
{
  "asset_id": "uuid-string",
  "asset_url": "http://localhost:8188/view?filename=...",
  "filename": "ComfyUI_00001_.mp3",
  "subfolder": "",
  "folder_type": "output",
  "workflow_id": "generate_song",
  "prompt_id": "uuid-string",
  "tool": "generate_song",
  "mime_type": "audio/mpeg",
  "bytes_size": 1234567
}
```

## Viewing Tools

### view_image

View generated images inline in chat (thumbnail preview only).

**Signature:**
```python
view_image(
    asset_id: str,
    mode: str = "thumb",
    max_dim: int | None = None,
    max_b64_chars: int | None = None
) -> dict | FastMCPImage
```

**Parameters:**
- `asset_id` (str): Asset ID returned from generation tools
- `mode` (str): Display mode - `"thumb"` (default) or `"metadata"`
- `max_dim` (int): Maximum dimension in pixels. Default: 512
- `max_b64_chars` (int): Maximum base64 character count. Default: 100000

**Returns:**

**Mode: "thumb"** (default):
- Returns `FastMCPImage` object for inline display
- WebP format, automatically downscaled and optimized
- Size constrained to fit within `max_b64_chars` limit

**Mode: "metadata"**:
```json
{
  "asset_id": "uuid-string",
  "asset_url": "http://localhost:8188/view?filename=...",
  "mime_type": "image/png",
  "width": 512,
  "height": 512,
  "bytes_size": 497648,
  "workflow_id": "generate_image",
  "created_at": "2024-01-01T12:00:00",
  "expires_at": "2024-01-02T12:00:00"
}
```

**Supported Types:**
- Images only: PNG, JPEG, WebP, GIF
- Audio/video assets return error: use `asset_url` directly

**Error Responses:**
```json
{
  "error": "Asset not found or expired"
}
```

```json
{
  "error": "Asset type 'audio/mpeg' not supported for inline viewing. Supported types: image/png, image/jpeg, image/webp, image/gif"
}
```

**Examples:**
```python
# Generate and view
result = generate_image(prompt="a cat")
view_image(asset_id=result["asset_id"])

# Get metadata only
metadata = view_image(asset_id=result["asset_id"], mode="metadata")
```

## Job Management Tools

### get_queue_status

Check the current state of the ComfyUI job queue.

**Signature:**
```python
get_queue_status() -> dict
```

**Returns:**
```json
{
  "running_count": 1,
  "pending_count": 2,
  "running": [
    {
      "prompt_id": "uuid-string",
      "status": "running"
    }
  ],
  "pending": [
    {
      "prompt_id": "uuid-string",
      "status": "pending"
    }
  ]
}
```

**Use Cases:**
- Check if ComfyUI is busy before submitting new jobs
- Monitor queue depth for async awareness
- Determine if a job is still queued vs running

**Examples:**
```python
queue = get_queue_status()
if queue["pending_count"] > 5:
    print("Queue is backed up, consider waiting")
```

### get_job

Poll the completion status of a specific job by prompt ID.

**Signature:**
```python
get_job(prompt_id: str) -> dict
```

**Parameters:**
- `prompt_id` (str): Prompt ID returned from generation tools

**Returns:**
```json
{
  "status": "completed",
  "prompt_id": "uuid-string"
}
```

**Status Values:**
- `"pending"`: Job is queued but not yet running
- `"running"`: Job is currently executing
- `"completed"`: Job finished successfully
- `"error"`: Job failed (check ComfyUI logs)

**Examples:**
```python
result = generate_image(prompt="complex scene", steps=50)
job = get_job(prompt_id=result["prompt_id"])

while job["status"] in ["pending", "running"]:
    time.sleep(1)
    job = get_job(prompt_id=result["prompt_id"])

if job["status"] == "completed":
    view_image(asset_id=result["asset_id"])
```

### cancel_job

Cancel a queued or running job.

**Signature:**
```python
cancel_job(prompt_id: str) -> dict
```

**Parameters:**
- `prompt_id` (str): Prompt ID of the job to cancel

**Returns:**
```json
{
  "success": true,
  "message": "Job cancelled"
}
```

**Error Response:**
```json
{
  "error": "Job not found or already completed"
}
```

**Examples:**
```python
result = generate_image(prompt="long task")
# ... decide to cancel ...
cancel_job(prompt_id=result["prompt_id"])
```

## Asset Management Tools

### list_assets

Browse recently generated assets with optional filtering.

**Signature:**
```python
list_assets(
    limit: int | None = None,
    workflow_id: str | None = None,
    session_id: str | None = None
) -> dict
```

**Parameters:**
- `limit` (int, optional): Maximum number of assets to return. Default: 10
- `workflow_id` (str, optional): Filter by workflow ID (e.g., `"generate_image"`)
- `session_id` (str, optional): Filter by session ID for conversation isolation

**Returns:**
```json
{
  "assets": [
    {
      "asset_id": "uuid-string",
      "asset_url": "http://localhost:8188/view?filename=...",
      "filename": "ComfyUI_00265_.png",
      "workflow_id": "generate_image",
      "created_at": "2024-01-01T12:00:00",
      "mime_type": "image/png",
      "width": 512,
      "height": 512
    }
  ],
  "count": 1,
  "limit": 10
}
```

**Use Cases:**
- Browse recent generations for AI agent memory
- Filter by workflow to see only images or only audio
- Filter by session for conversation-scoped asset isolation

**Examples:**
```python
# List recent images
images = list_assets(workflow_id="generate_image", limit=5)

# List assets from current conversation
session_assets = list_assets(session_id="current-session-id")
```

### get_asset_metadata

Get complete provenance and parameters for a specific asset.

**Signature:**
```python
get_asset_metadata(asset_id: str) -> dict
```

**Parameters:**
- `asset_id` (str): Asset ID returned from generation tools

**Returns:**
```json
{
  "asset_id": "uuid-string",
  "asset_url": "http://localhost:8188/view?filename=...",
  "filename": "ComfyUI_00265_.png",
  "subfolder": "",
  "folder_type": "output",
  "workflow_id": "generate_image",
  "mime_type": "image/png",
  "width": 512,
  "height": 512,
  "bytes_size": 497648,
  "created_at": "2024-01-01T12:00:00",
  "expires_at": "2024-01-02T12:00:00",
  "submitted_workflow": {
    "3": {
      "inputs": {
        "text": "a beautiful sunset",
        "width": 512,
        "height": 512
      }
    }
  },
  "comfy_history": [
    {
      "prompt": [...],
      "outputs": {...}
    }
  ]
}
```

**Key Fields:**
- `submitted_workflow`: Exact workflow JSON that was submitted (enables `regenerate`)
- `comfy_history`: Complete ComfyUI execution history
- `created_at` / `expires_at`: Asset lifecycle timestamps

**Use Cases:**
- Inspect exact parameters used for an asset
- Retrieve workflow data for regeneration
- Debug generation issues with full provenance

**Examples:**
```python
metadata = get_asset_metadata(asset_id="abc123")
print(f"Generated with: {metadata['workflow_id']}")
print(f"Parameters: {metadata['submitted_workflow']}")
```

### regenerate

Regenerate an existing asset with optional parameter overrides.

**Signature:**
```python
regenerate(
    asset_id: str,
    param_overrides: dict | None = None,
    seed: int | None = None
) -> dict
```

**Parameters:**
- `asset_id` (str): Asset ID to regenerate
- `param_overrides` (dict, optional): Parameter overrides (e.g., `{"steps": 30, "cfg": 10.0}`)
- `seed` (int, optional): New random seed (use `-1` for auto-generated)

**Returns:**
Same schema as generation tools (new asset with new `asset_id`)

**Behavior:**
- Uses stored `submitted_workflow` from original asset
- Applies `param_overrides` to modify specific parameters
- All other parameters remain unchanged from original generation
- Returns a new asset (original is not modified)

**Error Response:**
```json
{
  "error": "No workflow data stored for this asset. Cannot regenerate."
}
```

**Examples:**
```python
# Generate initial image
result = generate_image(prompt="a sunset", steps=20)

# Regenerate with higher quality
regenerate_result = regenerate(
    asset_id=result["asset_id"],
    param_overrides={"steps": 30, "cfg": 10.0}
)

# Regenerate with different prompt
regenerate_result = regenerate(
    asset_id=result["asset_id"],
    param_overrides={"prompt": "a beautiful sunset, oil painting style"}
)

# Regenerate with new seed
regenerate_result = regenerate(
    asset_id=result["asset_id"],
    seed=-1
)
```

## Configuration Tools

### list_models

List all available checkpoint models in ComfyUI.

**Signature:**
```python
list_models() -> dict
```

**Returns:**
```json
{
  "models": [
    "v1-5-pruned-emaonly.ckpt",
    "sd_xl_base_1.0.safetensors",
    ...
  ],
  "count": 7,
  "default": "v1-5-pruned-emaonly.ckpt"
}
```

### get_defaults

Get current effective defaults for image, audio, and video generation.

**Signature:**
```python
get_defaults() -> dict
```

**Returns:**
```json
{
  "image": {
    "width": 512,
    "height": 512,
    "model": "v1-5-pruned-emaonly.ckpt",
    "steps": 20,
    "cfg": 8.0,
    "sampler_name": "euler",
    "scheduler": "normal",
    "denoise": 1.0,
    "negative_prompt": "text, watermark"
  },
  "audio": {
    "steps": 50,
    "cfg": 5.0,
    "model": "ace_step_v1_3.5b.safetensors",
    "seconds": 60,
    "lyrics_strength": 0.99
  },
  "video": {
    "width": 1280,
    "height": 720,
    "steps": 20,
    "cfg": 8.0,
    "model": "wan2.2_vae.safetensors",
    "duration": 5,
    "fps": 16
  }
}
```

### set_defaults

Set runtime defaults for image, audio, and/or video generation.

**Signature:**
```python
set_defaults(
    image: dict | None = None,
    audio: dict | None = None,
    video: dict | None = None,
    persist: bool = False
) -> dict
```

**Parameters:**
- `image` (dict): Default values for image generation
- `audio` (dict): Default values for audio generation
- `video` (dict): Default values for video generation
- `persist` (bool): If True, write to config file. Default: False

**Returns:**
```json
{
  "success": true,
  "updated": {
    "image": {"success": true, "updated": {...}},
    "audio": {"success": true, "updated": {...}}
  }
}
```

**Error Response:**
```json
{
  "success": false,
  "errors": [
    "Model 'invalid_model.ckpt' not found. Available models: ..."
  ]
}
```

**Examples:**
```python
# Set ephemeral defaults
set_defaults(
    image={"width": 1024, "height": 1024},
    audio={"seconds": 30}
)

# Persist to config file
set_defaults(
    image={"model": "sd_xl_base_1.0.safetensors"},
    persist=True
)
```

## Workflow Tools

### list_workflows

List all available workflows in the workflow directory.

**Signature:**
```python
list_workflows() -> dict
```

**Returns:**
```json
{
  "workflows": [
    {
      "id": "generate_image",
      "name": "Generate Image",
      "description": "Execute the 'generate_image' workflow.",
      "available_inputs": {
        "prompt": {"type": "str", "required": true, "description": "..."},
        "width": {"type": "int", "required": false, "description": "..."}
      },
      "defaults": {},
      "updated_at": null,
      "hash": null
    }
  ],
  "count": 2,
  "workflow_dir": "/path/to/workflows"
}
```

### run_workflow

Run any saved ComfyUI workflow with constrained parameter overrides.

**Signature:**
```python
run_workflow(
    workflow_id: str,
    overrides: dict | None = None,
    options: dict | None = None,
    return_inline_preview: bool = False
) -> dict
```

**Parameters:**
- `workflow_id` (str): Workflow ID (filename stem, e.g., "generate_image")
- `overrides` (dict): Parameter overrides
- `options` (dict): Reserved for future use
- `return_inline_preview` (bool): Include thumbnail. Default: False

**Returns:**
```json
{
  "asset_id": "uuid-string",
  "asset_url": "http://localhost:8188/view?filename=...",
  "workflow_id": "generate_image",
  "prompt_id": "..."
}
```

**Error Response:**
```json
{
  "error": "Workflow 'invalid_workflow' not found"
}
```

**Examples:**
```python
# Run workflow with overrides
run_workflow(
    workflow_id="generate_image",
    overrides={
        "prompt": "a cat",
        "width": 1024,
        "model": "sd_xl_base_1.0.safetensors"
    }
)
```

### Advanced: Workflow Metadata

For advanced control over workflow behavior, create a `.meta.json` file alongside your workflow JSON file.

**File Structure:**
```
workflows/
├── my_workflow.json
└── my_workflow.meta.json
```

**Metadata Schema:**
```json
{
  "name": "My Custom Workflow",
  "description": "Does something cool",
  "defaults": {
    "steps": 30,
    "cfg": 7.5
  },
  "constraints": {
    "width": {"min": 64, "max": 2048, "step": 64},
    "height": {"min": 64, "max": 2048, "step": 64},
    "steps": {"min": 1, "max": 100}
  }
}
```

**Fields:**
- `name` (str, optional): Human-readable workflow name
- `description` (str, optional): Workflow description shown in tool listings
- `defaults` (dict, optional): Default parameter values for this workflow
- `constraints` (dict, optional): Parameter validation constraints
  - `min` (number): Minimum allowed value
  - `max` (number): Maximum allowed value
  - `step` (number): Step size for numeric parameters

**Behavior:**
- Metadata defaults override global defaults for this workflow only
- Constraints validate parameter values when `run_workflow` is called
- If metadata file is missing, workflow still works with global defaults

## Parameters

### Type System

Parameters are typed and automatically coerced:

- **String parameters**: `str` (default if no type specified)
- **Integer parameters**: `PARAM_INT_*` → `int`
- **Float parameters**: `PARAM_FLOAT_*` → `float`
- **Boolean parameters**: `PARAM_BOOL_*` → `bool`

**Type Coercion:**
- JSON-RPC may pass numbers as strings: `"512"` → `512` (int)
- Automatic conversion handles both string and numeric inputs

### Required vs Optional

**Required Parameters:**
- `prompt` (for image workflows)
- `tags` and `lyrics` (for audio workflows)

**Optional Parameters:**
- All others have defaults or are auto-generated (e.g., `seed`)

### Default Precedence

1. **Per-call values** (highest priority) - Explicitly provided in tool calls
2. **Runtime defaults** (`set_defaults` tool) - Ephemeral, lost on restart
3. **Config file** (`~/.config/comfy-mcp/config.json`) - Persistent across restarts
4. **Environment variables** (`COMFY_MCP_DEFAULT_*`) - System-level configuration
5. **Hardcoded defaults** (lowest priority) - Built-in sensible values

### Configuration File

Create `~/.config/comfy-mcp/config.json` for persistent defaults:

```json
{
  "defaults": {
    "image": {
      "model": "sd_xl_base_1.0.safetensors",
      "width": 1024,
      "height": 1024,
      "steps": 30,
      "cfg": 7.5,
      "sampler_name": "dpmpp_2m",
      "scheduler": "normal",
      "denoise": 1.0,
      "negative_prompt": "blurry, low quality"
    },
    "audio": {
      "model": "ace_step_v1_3.5b.safetensors",
      "seconds": 30,
      "steps": 60,
      "cfg": 5.0,
      "lyrics_strength": 0.99
    },
    "video": {
      "width": 1280,
      "height": 720,
      "steps": 20,
      "cfg": 8.0,
      "duration": 5,
      "fps": 16
    }
  }
}
```

### Environment Variables

**Server Configuration:**
- `COMFYUI_URL`: ComfyUI server URL (default: `http://localhost:8188`)
- `COMFY_MCP_WORKFLOW_DIR`: Workflow directory path (default: `./workflows`)
- `COMFY_MCP_ASSET_TTL_HOURS`: Asset expiration time in hours (default: 24)

**Default Values:**
- `COMFY_MCP_DEFAULT_IMAGE_MODEL`: Default image model name
- `COMFY_MCP_DEFAULT_AUDIO_MODEL`: Default audio model name
- `COMFY_MCP_DEFAULT_VIDEO_MODEL`: Default video model name
- `COMFY_MCP_DEFAULT_IMAGE_WIDTH`: Default image width (integer)
- `COMFY_MCP_DEFAULT_IMAGE_HEIGHT`: Default image height (integer)
- `COMFY_MCP_DEFAULT_IMAGE_STEPS`: Default image steps (integer)
- `COMFY_MCP_DEFAULT_IMAGE_CFG`: Default image CFG scale (float)
- `COMFY_MCP_DEFAULT_AUDIO_SECONDS`: Default audio duration (integer)
- `COMFY_MCP_DEFAULT_AUDIO_STEPS`: Default audio steps (integer)

Environment variables take precedence over config file but are overridden by runtime defaults and per-call values.

## Return Values

### MCP Protocol Response Format

When calling tools via the MCP protocol (JSON-RPC), the response is wrapped in the MCP format:

```json
{
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{...tool return value as JSON string...}"
      }
    ],
    "isError": false
  }
}
```

The actual tool return value is serialized as a JSON string in `result.content[0].text`. You need to parse this JSON string to access the tool's return data.

**Note:** This documentation shows the unwrapped tool return values (what's inside the JSON string), not the MCP protocol wrapper.

### Generation Tools Return Schema

All generation tools (`generate_image`, `generate_song`, `regenerate`, `run_workflow`) return:

```json
{
  "asset_id": "uuid-string",
  "asset_url": "http://localhost:8188/view?filename=ComfyUI_00265_.png&subfolder=&type=output",
  "image_url": "http://localhost:8188/view?filename=ComfyUI_00265_.png&subfolder=&type=output",
  "filename": "ComfyUI_00265_.png",
  "subfolder": "",
  "folder_type": "output",
  "workflow_id": "generate_image",
  "prompt_id": "uuid-string",
  "tool": "generate_image",
  "mime_type": "image/png",
  "width": 512,
  "height": 512,
  "bytes_size": 497648,
  "inline_preview_base64": "data:image/webp;base64,..."
}
```

**Field Descriptions:**
- `asset_id` (str): Unique identifier for the asset, use with `view_image` and `regenerate`
- `asset_url` (str): Direct URL to access the asset from ComfyUI
- `image_url` (str): Alias for `asset_url` (for image assets)
- `filename` (str): Stable filename identifier (not URL-dependent)
- `subfolder` (str): Asset subfolder path (usually empty)
- `folder_type` (str): Asset type, typically `"output"`
- `workflow_id` (str): Workflow that generated this asset
- `prompt_id` (str): ComfyUI prompt ID, use with `get_job()` to poll completion
- `tool` (str): Tool name that generated this asset
- `mime_type` (str): MIME type of the asset (e.g., `"image/png"`, `"audio/mpeg"`)
- `width` (int, optional): Image width in pixels (images only)
- `height` (int, optional): Image height in pixels (images only)
- `bytes_size` (int): File size in bytes
- `inline_preview_base64` (str, optional): Base64-encoded thumbnail (if `return_inline_preview=true`)

**Key Points:**
- `asset_id` is the primary identifier for follow-up operations
- `filename`, `subfolder`, and `folder_type` form a stable identity that is stable across URL/base changes
- `prompt_id` enables job status polling via `get_job()`
- Asset URLs are computed from stable identity, making the system robust to configuration changes

## Error Handling

### Error Response Format

All tools return errors in consistent format:

```json
{
  "error": "Error message describing what went wrong"
}
```

### Common Errors

**Asset Not Found:**
```json
{
  "error": "Asset not found or expired"
}
```

**Invalid Workflow:**
```json
{
  "error": "Workflow 'invalid_workflow' not found"
}
```

**Invalid Model:**
```json
{
  "success": false,
  "errors": ["Model 'invalid.ckpt' not found. Available models: ..."]
}
```

**Unsupported Asset Type:**
```json
{
  "error": "Asset type 'audio/mpeg' not supported for inline viewing. Supported types: image/png, image/jpeg, image/webp, image/gif"
}
```

## Limits and Constraints

### Image Viewing

- **Maximum dimension**: 512px (default, configurable via `max_dim`)
- **Base64 budget**: 100KB (default, configurable via `max_b64_chars`)
- **Supported formats**: PNG, JPEG, WebP, GIF only
- **Automatic optimization**: Images are downscaled and re-encoded as WebP

### Asset Expiration

- **Default TTL**: 24 hours
- **Configurable**: `COMFY_MCP_ASSET_TTL_HOURS` environment variable
- **Automatic cleanup**: Expired assets are removed from registry

### Workflow Constraints

- **Path traversal protection**: Workflow IDs are sanitized
- **Directory restriction**: Only workflows in `workflows/` directory
- **Parameter validation**: Overrides constrained to declared parameters

### ComfyUI Integration

- **Polling interval**: 1 second
- **Maximum attempts**: 30 (configurable)
- **Timeout**: 30 seconds per request
