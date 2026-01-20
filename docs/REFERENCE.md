# API Reference

Complete technical reference for ComfyUI MCP Server tools, parameters, and behavior.

## Table of Contents

- [Generation Tools](#generation-tools)
- [Viewing Tools](#viewing-tools)
- [Job Management Tools](#job-management-tools)
- [Asset Management Tools](#asset-management-tools)
- [Configuration Tools](#configuration-tools)
- [Workflow Tools](#workflow-tools)
- [Publish Tools](#publish-tools)
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

**User:** "Generate an image of a cat"

**Agent:** *Calls `generate_image(prompt="a cat")` → returns asset_id*

---

**User:** "Create a cyberpunk cityscape, 1024x768, high quality, 30 steps, using the SD XL model"

**Agent:** *Calls `generate_image(prompt="cyberpunk cityscape", width=1024, height=768, model="sd_xl_base_1.0.safetensors", steps=30, cfg=7.5, sampler_name="dpmpp_2m", negative_prompt="blurry, low quality")` → returns asset_id*

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

**User:** "Generate an image of a cat and show it to me"

**Agent:** 
- *Calls `generate_image(prompt="a cat")` → gets asset_id*
- *Calls `view_image(asset_id="...")` → displays thumbnail inline*

---

**User:** "What are the dimensions of that last image I generated?"

**Agent:** *Calls `view_image(asset_id="...", mode="metadata")` → returns width, height, size, etc.*

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

**User:** "Is ComfyUI busy right now? How many jobs are queued?"

**Agent:** *Calls `get_queue_status()` → reports queue depth and running jobs*

---

**User:** "Check if there are any jobs waiting before I submit a new one"

**Agent:** *Calls `get_queue_status()` → checks pending_count, informs user if queue is backed up*

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

**User:** "Generate a complex scene with 50 steps, and let me know when it's done"

**Agent:**
- *Calls `generate_image(prompt="complex scene", steps=50)` → gets prompt_id*
- *Periodically calls `get_job(prompt_id="...")` to check status*
- *When status is "completed", informs user and optionally calls `view_image()`*

---

**User:** "Is that image generation I started earlier finished yet?"

**Agent:** *Calls `get_job(prompt_id="...")` → reports current status (pending/running/completed/error)*

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

**User:** "I started a long image generation task earlier, but I want to cancel it now"

**Agent:** 
- *Calls `get_queue_status()` to find running jobs*
- *Calls `cancel_job(prompt_id="...")` to cancel the job*
- *Confirms cancellation to user*

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

**User:** "Show me the last 5 images I generated"

**Agent:** *Calls `list_assets(workflow_id="generate_image", limit=5)` → displays list of recent images*

---

**User:** "What assets have we created in this conversation?"

**Agent:** *Calls `list_assets(session_id="current-session-id")` → lists assets from current session*

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

**User:** "What parameters were used to generate that last image?"

**Agent:** *Calls `get_asset_metadata(asset_id="...")` → retrieves and reports workflow parameters, dimensions, etc.*

---

**User:** "I want to regenerate that image but with different settings - what were the original settings?"

**Agent:** *Calls `get_asset_metadata(asset_id="...")` → shows submitted_workflow data for regeneration*

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

**User:** "Generate a sunset image with 20 steps"

**Agent:** *Calls `generate_image(prompt="a sunset", steps=20)` → gets asset_id*

**User:** "Now regenerate that same image but with higher quality - 30 steps and cfg 10"

**Agent:** *Calls `regenerate(asset_id="...", param_overrides={"steps": 30, "cfg": 10.0})` → creates new version*

---

**User:** "Regenerate that image but change the prompt to 'a beautiful sunset, oil painting style'"

**Agent:** *Calls `regenerate(asset_id="...", param_overrides={"prompt": "a beautiful sunset, oil painting style"})` → creates variation*

---

**User:** "Generate a new variation of that image with a different random seed"

**Agent:** *Calls `regenerate(asset_id="...", seed=-1)` → creates new variation with different seed*

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

**Examples:**

**User:** "What models are available in ComfyUI?"

**Agent:** *Calls `list_models()` → reports available checkpoint models*

---

**User:** "I want to use a different model - show me what's available"

**Agent:** *Calls `list_models()` → lists models, user selects one, agent uses it in generation*

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
    "duration": 5,
    "fps": 16
  }
}
```

**Examples:**

**User:** "What are the current default settings for image generation?"

**Agent:** *Calls `get_defaults()` → reports current defaults (width, height, model, steps, etc.)*

---

**User:** "Show me all the default settings"

**Agent:** *Calls `get_defaults()` → shows defaults for image, audio, and video generation*

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

**User:** "Set the default image size to 1024x1024 for this session"

**Agent:** *Calls `set_defaults(image={"width": 1024, "height": 1024})` → sets ephemeral defaults*

---

**User:** "Save the SD XL model as the default image model permanently"

**Agent:** *Calls `set_defaults(image={"model": "sd_xl_base_1.0.safetensors"}, persist=True)` → saves to config file*

### Default Model Validation

The server automatically validates that default models exist in ComfyUI's checkpoints directory. This prevents errors at generation time and provides clear feedback about misconfiguration.

**Startup Validation:**
- On server startup, all default models (from hardcoded, config file, and environment variables) are validated
- Missing models are logged as warnings (non-fatal) - the server still starts successfully
- Warnings include the model name, source (hardcoded/config/env), and namespace (image/audio/video)

**Generation-Time Validation:**
- Before rendering a workflow, the resolved model (after applying precedence rules) is checked
- If the model is invalid, generation fails immediately with a clear error message
- Error messages include:
  - The model name that was requested
  - Where it came from (runtime/config/env/hardcoded)
  - A sample of available models (first 5)
  - Instructions to use `list_models` or `set_defaults`

**Refresh-on-Failure:**
- If ComfyUI returns an error suggesting a missing model, the server automatically:
  1. Refreshes the cached model list from ComfyUI
  2. Re-validates the model
  3. If still invalid, returns a clear error message
- This handles cases where models are added/removed after server startup

**Example Error Messages:**

```json
{
  "error": "Default model 'v1-5-pruned-emaonly.ckpt' (from hardcoded defaults) not found in ComfyUI checkpoints. Set a valid model via `set_defaults`, config file, or env var. Try `list_models` to see available checkpoints. Available models: ['sd_xl_base_1.0.safetensors', 'cyberrealisticPony_v8.safetensors', ...]"
}
```

**Best Practices:**
- Use `list_models` to see available checkpoints before setting defaults
- Set defaults via `set_defaults` with `persist=True` to save valid models
- Check server startup logs for validation warnings
- The validation system uses a cached model set for fast checks (no per-call overhead)

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

**Examples:**

**User:** "What workflows are available?"

**Agent:** *Calls `list_workflows()` → lists all available workflows with descriptions and parameters*

---

**User:** "Show me what custom workflows I can run"

**Agent:** *Calls `list_workflows()` → displays workflow catalog with available inputs*

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

**User:** "Run the generate_image workflow with a custom prompt and 30 steps"

**Agent:** *Calls `run_workflow(workflow_id="generate_image", overrides={"prompt": "...", "steps": 30})` → executes workflow*

---

**User:** "Use the generate_image workflow to create a 1024x1024 image of a cat with the SD XL model"

**Agent:** *Calls `run_workflow(workflow_id="generate_image", overrides={"prompt": "a cat", "width": 1024, "height": 1024, "model": "sd_xl_base_1.0.safetensors"})` → executes workflow*

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

## Publish Tools

Tools for safely publishing ComfyUI-generated assets to web project directories with automatic compression and manifest management.

**Key Concepts:**
- **Session-scoped assets**: `asset_id`s are valid only for the current server session; restart invalidates them
- **Zero-config in common cases**: Publish directory auto-detected (`public/gen`, `static/gen`, or `assets/gen`)
- **Two modes**: Demo mode (explicit filename) and Library mode (auto-generated filename with manifest)
- **Deterministic compression**: Images compressed using a fixed quality/downscale ladder to meet size limits

### get_publish_info

Get publish configuration and status information. Use this to debug configuration issues and verify setup before publishing.

**Signature:**
```python
get_publish_info() -> dict
```

**Returns:**
```json
{
  "project_root": {
    "path": "E:\\dev\\comfyui-mcp-server",
    "detection_method": "cwd"
  },
  "publish_root": {
    "path": "E:\\dev\\comfyui-mcp-server\\public\\gen",
    "exists": true,
    "writable": true
  },
  "comfyui_output_root": {
    "path": "E:\\comfyui-desktop\\output",
    "exists": true,
    "detection_method": "auto-detected",
    "configured": false
  },
  "comfyui_tried_paths": [
    {
      "path": "E:\\dev\\comfyui-mcp-server\\comfyui-desktop\\output",
      "exists": false,
      "is_valid": false,
      "source": "auto_detection"
    },
    {
      "path": "E:\\comfyui-desktop\\output",
      "exists": true,
      "is_valid": true,
      "source": "auto_detection"
    }
  ],
  "config_file": "C:\\Users\\user\\AppData\\Roaming\\comfyui-mcp-server\\publish_config.json",
  "status": "ready",
  "message": "Ready to publish",
  "warnings": []
}
```

**Field Descriptions:**
- `project_root`: Detected project root directory and detection method (`"cwd"` or `"auto-detected"`)
- `publish_root`: Publish directory path, existence, and writability
- `comfyui_output_root`: ComfyUI output root path, existence, detection method, and whether it's configured
- `comfyui_tried_paths`: List of paths checked during auto-detection with validation results
- `config_file`: Path to persistent configuration file
- `status`: `"ready"` | `"needs_comfyui_root"` | `"error"`
- `message`: Human-readable status message
- `warnings`: List of warnings (e.g., fallback detection used)

**Examples:**

**User:** "Check if the publish system is ready to use"

**Agent:** *Calls `get_publish_info()` → reports status, project root, publish directory, ComfyUI output root*

---

**User:** "I'm getting an error about ComfyUI output root not being found"

**Agent:** 
- *Calls `get_publish_info()` → sees status "needs_comfyui_root"*
- *Suggests using `set_comfyui_output_root()` with the path*
- *User provides path: "E:/comfyui-desktop/output"*
- *Agent calls `set_comfyui_output_root("E:/comfyui-desktop/output")` → configures and persists*

### set_comfyui_output_root

Set ComfyUI output root directory in persistent configuration. Recommended for Comfy Desktop and nonstandard installs.

**Signature:**
```python
set_comfyui_output_root(path: str) -> dict
```

**Required Parameters:**
- `path` (str): Absolute or relative path to ComfyUI output directory (e.g., `"E:/comfyui-desktop/output"` or `"/opt/ComfyUI/output"`)

**Returns (Success):**
```json
{
  "success": true,
  "path": "E:\\comfyui-desktop\\output",
  "config_file": "C:\\Users\\user\\AppData\\Roaming\\comfyui-mcp-server\\publish_config.json",
  "message": "ComfyUI output root configured: E:\\comfyui-desktop\\output"
}
```

**Returns (Error):**
```json
{
  "error": "COMFYUI_OUTPUT_ROOT_PATH_NOT_FOUND",
  "message": "Path does not exist: E:/nonexistent/output",
  "path": "E:/nonexistent/output"
}
```

**Error Codes:**
- `COMFYUI_OUTPUT_ROOT_PATH_NOT_FOUND`: Path does not exist
- `COMFYUI_OUTPUT_ROOT_NOT_DIRECTORY`: Path is not a directory
- `COMFYUI_OUTPUT_ROOT_INVALID`: Path doesn't appear to be a ComfyUI output directory
- `CONFIG_SAVE_FAILED`: Failed to save configuration file
- `INVALID_PATH`: Invalid path format

**Configuration Storage:**
- **Windows**: `%APPDATA%/comfyui-mcp-server/publish_config.json`
- **Mac**: `~/Library/Application Support/comfyui-mcp-server/publish_config.json`
- **Linux**: `~/.config/comfyui-mcp-server/publish_config.json`

**Examples:**

**User:** "Set the ComfyUI output directory to E:/comfyui-desktop/output"

**Agent:** *Calls `set_comfyui_output_root("E:/comfyui-desktop/output")` → validates path, saves to config, confirms success*

---

**User:** "Configure the output directory" *(if path is invalid)*

**Agent:** 
- *Calls `set_comfyui_output_root("...")` → receives error*
- *Reports error to user: "Path does not exist" or "Path doesn't appear to be a ComfyUI output directory"*
- *Suggests checking the path or using `get_publish_info()` to see tried paths*

### publish_asset

Publish a ComfyUI-generated asset to the project's web directory with automatic compression.

**Signature:**
```python
publish_asset(
    asset_id: str,
    target_filename: str | None = None,
    manifest_key: str | None = None,
    format: str = "webp",
    max_bytes: int = 600_000,
    overwrite: bool = True
) -> dict
```

**Required Parameters:**
- `asset_id` (str): Asset ID from generation tools (session-scoped, dies on server restart)

**Optional Parameters:**
- `target_filename` (str, optional): Target filename (e.g., `"hero.webp"`). If omitted, auto-generated (library mode). Must match regex: `^[a-z0-9][a-z0-9._-]{0,63}\.(webp|png|jpg|jpeg)$`
- `manifest_key` (str, optional): Manifest key (required if `target_filename` omitted). Must match regex: `^[a-z0-9][a-z0-9._-]{0,63}$`
- `format` (str): Target image format (default: `"webp"`). Ignored if `target_filename` has extension.
- `max_bytes` (int): Maximum file size in bytes (default: `600000`). Images are compressed if needed.
- `overwrite` (bool): Whether to overwrite existing file (default: `True`)

**Two Modes:**

**Demo Mode** (explicit filename):
- User provides `target_filename` (e.g., `"hero.webp"`)
- Agent calls: `publish_asset(asset_id="...", target_filename="hero.webp")`
- Manifest not updated unless `manifest_key` also provided

**Library Mode** (auto-generated with manifest):
- User provides `manifest_key`, omits `target_filename`
- Agent calls: `publish_asset(asset_id="...", manifest_key="hero-image")`
- Filename auto-generated as `asset_<shortid>.webp`
- Manifest automatically updated: `{"hero-image": "asset_0b3eacbc.webp"}`

**Returns (Success):**
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
    "original_dimensions": [512, 512],
    "quality": 85,
    "final_dimensions": [512, 512],
    "downscaled": false,
    "final_size": 37478
  }
}
```

**Returns (Error):**
```json
{
  "error": "Asset 0b3eacbc-25b0-497c-9d63-6d66d9e67387 not found or expired. Assets are session-scoped and die on server restart. Generate a new asset in the current session.",
  "error_code": "ASSET_NOT_FOUND_OR_EXPIRED"
}
```

**Error Codes:**
- `ASSET_NOT_FOUND_OR_EXPIRED`: Asset not in current session (session-scoped)
- `INVALID_TARGET_FILENAME`: Filename doesn't match regex pattern
- `INVALID_MANIFEST_KEY`: Manifest key doesn't match regex pattern
- `MANIFEST_KEY_REQUIRED`: `manifest_key` required when `target_filename` omitted (library mode)
- `SOURCE_PATH_OUTSIDE_ROOT`: Source file outside ComfyUI output root
- `PATH_TRAVERSAL_DETECTED`: Path traversal attempt detected
- `COMFYUI_OUTPUT_ROOT_NOT_FOUND`: ComfyUI output root not configured
- `PUBLISH_ROOT_NOT_WRITABLE`: Publish directory not writable
- `PUBLISH_FAILED`: Copy/compression operation failed
- `VALIDATION_ERROR`: General validation error

**Compression Details:**

Images are compressed using a deterministic compression ladder:

1. **Quality progression**: [85, 75, 65, 55, 45, 35]
2. **Downscale factors**: [1.0, 0.9, 0.75, 0.6, 0.5] (if needed)
3. **Format conversion**: PNG/JPEG → WebP (if `format="webp"`)
4. **Size limit**: Enforced via `max_bytes` (default: 600KB)

The compression ladder tries quality levels first, then downscaling if needed, until the size limit is met. If compression cannot meet the limit, an error is returned.

**Manifest Updates:**

The manifest (`<publish_root>/manifest.json`) is updated only when `manifest_key` is provided:

```json
{
  "hero-image": "asset_0b3eacbc.webp",
  "logo": "logo.png"
}
```

Manifest uses simple `key → filename` mapping (no arrays in v1). Updates are atomic (process-level locking).

**Examples:**

**Demo Mode:**

**User:** "Generate a sunset image and publish it as hero.webp, keep it under 500KB"

**Agent:**
- *Calls `generate_image(prompt="a sunset")` → gets asset_id*
- *Calls `publish_asset(asset_id="...", target_filename="hero.webp", format="webp", max_bytes=500_000)` → publishes with compression*
- *Reports: "Published to /gen/hero.webp (37478 bytes)"*

---

**Library Mode:**

**User:** "Generate a sunset image and add it to the manifest as 'hero-image'"

**Agent:**
- *Calls `generate_image(prompt="a sunset")` → gets asset_id*
- *Calls `publish_asset(asset_id="...", manifest_key="hero-image", format="webp")` → auto-generates filename, updates manifest*
- *Reports: "Published to /gen/asset_0b3eacbc.webp, added to manifest as 'hero-image'*

**Typical Workflow:**

**User:** "I want to publish an image to my website"

**Agent:**
- *Calls `get_publish_info()` to check configuration*
- *If status is not "ready", suggests using `set_comfyui_output_root()` if ComfyUI output root is missing*
- *User provides path or agent proceeds if ready*
- *Calls `generate_image()` or other generation tool*
- *Calls `publish_asset()` with user's requested filename or manifest key*
- *Confirms publication and provides URL*

**Safety Guarantees:**
- Only assets from current session can be published (asset_id must exist in registry)
- Source path must be within ComfyUI output root (validated with real path resolution)
- Target filename validated by strict regex (prevents path traversal)
- All paths are canonicalized to prevent symlink/traversal attacks
- Images automatically compressed to meet size limits

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
  "error": "Default model 'invalid.ckpt' (from hardcoded defaults) not found in ComfyUI checkpoints. Set a valid model via `set_defaults`, config file, or env var. Try `list_models` to see available checkpoints. Available models: ['sd_xl_base_1.0.safetensors', 'v1-5-pruned-emaonly.ckpt', ...]"
}
```

Or when using `set_defaults`:
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

**Publish Errors:**

All publish errors include both human-readable messages and machine-readable error codes:

```json
{
  "error": "Asset 0b3eacbc-25b0-497c-9d63-6d66d9e67387 not found or expired. Assets are session-scoped and die on server restart. Generate a new asset in the current session.",
  "error_code": "ASSET_NOT_FOUND_OR_EXPIRED"
}
```

**Common Publish Error Codes:**
- `ASSET_NOT_FOUND_OR_EXPIRED`: Asset not in current session
- `INVALID_TARGET_FILENAME`: Filename doesn't match validation regex
- `MANIFEST_KEY_REQUIRED`: `manifest_key` required when `target_filename` omitted
- `COMFYUI_OUTPUT_ROOT_NOT_FOUND`: ComfyUI output root not configured
- `PUBLISH_FAILED`: Copy/compression operation failed

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

### Publish Constraints

- **Session-scoped assets**: `asset_id`s are valid only for the current server session; restart invalidates them
- **Filename validation**: Target filenames must match regex `^[a-z0-9][a-z0-9._-]{0,63}\.(webp|png|jpg|jpeg)$`
- **Manifest key validation**: Manifest keys must match regex `^[a-z0-9][a-z0-9._-]{0,63}$`
- **Compression limits**: Images compressed to meet `max_bytes` limit (default: 600KB); fails with error if limit cannot be met
- **Path safety**: All paths canonicalized; source must be within ComfyUI output root; target must be within publish root
- **Project root detection**: Server should be started from repository root (cwd) for best results
