# ComfyUI MCP Server

A lightweight Python-based MCP (Model Context Protocol) server that interfaces with a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instance to generate images programmatically via AI agent requests.

## Overview

This project enables AI agents to send generation requests to ComfyUI using the MCP (Model Context Protocol) over HTTP. It supports:
- Flexible workflow selection (e.g., the bundled `generate_image.json` and `generate_song.json`).
- Dynamic parameters (text prompts, tags, lyrics, dimensions, etc.) inferred from workflow placeholders.
- Automatic asset URL routing—image workflows return PNG/JPEG URLs, audio workflows return MP3 URLs.
- Standard MCP protocol using streamable-http transport for cloud-ready scalability.

## Prerequisites

- **Python 3.10+**
- **ComfyUI**: Installed and running locally (e.g., on `localhost:8188`).
- **Dependencies**: `requests`, `mcp` (install via pip).

## Setup

1. **Clone the Repository**:
   git clone <your-repo-url>
   cd comfyui-mcp-server

2. **Install Dependencies**:

   pip install requests mcp


3. **Start ComfyUI**:
- Install ComfyUI (see [ComfyUI docs](https://github.com/comfyanonymous/ComfyUI)).
- Run it on port 8188:
  ```
  cd <ComfyUI_dir>
  python main.py --port 8188
  ```

4. **Prepare Workflows**:
- Place API-format workflow files (e.g., `generate_image.json`, `generate_song.json`, or your own) in the `workflows/` directory.
- Export workflows from ComfyUI’s UI with “Save (API Format)” (enable dev mode in settings).

## Usage

1. **Run the MCP Server**:
   ```bash
   python server.py
   ```

   The server will start and listen on `http://127.0.0.1:9000/mcp` using the streamable-http transport.

2. **Test with the Client**:
   ```bash
   python client.py
   ```

   The test client will:
   - List all available tools from the server
   - Call the `generate_image` tool (or first available tool) with test parameters
   - Display the generated asset URL

   Example output:
   ```
   Available tools (1):
     - generate_image: Execute the 'generate image' ComfyUI workflow.
   
   Calling tool 'generate_image' with arguments:
   {
     "prompt": "an english mastiff dog sitting on a large boulder, bright shiny day",
     "width": 512,
     "height": 512
   }
   
   Response from server:
   {
     "asset_url": "http://localhost:8188/view?filename=ComfyUI_00001_.png&subfolder=&type=output",
     "workflow_id": "generate_image",
     "tool": "generate_image"
   }
   ```

3. **Connect from Your Own Client**:

   The server uses standard HTTP with JSON-RPC protocol. You can connect using any HTTP client:

   ```python
   import requests
   
   response = requests.post(
       "http://127.0.0.1:9000/mcp",
       json={
           "jsonrpc": "2.0",
           "id": 1,
           "method": "tools/call",
           "params": {
               "name": "generate_image",
               "arguments": {
                   "prompt": "a beautiful landscape",
                   "width": 512,
                   "height": 512
               }
           }
       }
   )
   
   result = response.json()
   print(result["result"]["asset_url"])
   ```

   Or using curl:
   ```bash
   curl -X POST http://127.0.0.1:9000/mcp \
     -H "Content-Type: application/json" \
     -d '{
       "jsonrpc": "2.0",
       "id": 1,
       "method": "tools/call",
       "params": {
         "name": "generate_image",
         "arguments": {
           "prompt": "a cat in space",
           "width": 768,
           "height": 768
         }
       }
     }'
   ```

### Bundled example workflows

- `generate_image.json`: Stable Diffusion image generation workflow with flexible parameters:
  - **Required**: `prompt` (text description)
  - **Optional**: `seed`, `width`, `height`, `model`, `steps`, `cfg`, `sampler_name`, `scheduler`, `denoise`, `negative_prompt`
  - Produces PNG/JPEG URLs
  
- `generate_song.json`: AceStep audio text-to-song workflow with flexible parameters:
  - **Required**: `tags` (comma-separated tags), `lyrics` (full lyric text)
  - **Optional**: `seed`, `steps`, `cfg`, `seconds`, `lyrics_strength`
  - Produces MP3 URLs

Add additional API-format workflows following the placeholder convention below to expose new MCP tools automatically.

### Workflow-backed MCP tools

- Any workflow JSON placed in `workflows/` that contains placeholders such as `PARAM_PROMPT`, `PARAM_TAGS`, or `PARAM_LYRICS` is exposed automatically as an MCP tool.
- Placeholders live inside node inputs and follow the convention `PARAM_<TYPE?>_<NAME>` where `<TYPE?>` is optional. Supported type hints: `STR`, `STRING`, `TEXT`, `INT`, `FLOAT`, and `BOOL`.
- Example: `"tags": "PARAM_TAGS"` creates a `tags: str` argument, while `"steps": "PARAM_INT_STEPS"` becomes an `int` argument.
- The tool name defaults to the workflow filename (normalized to snake_case). Rename the JSON file if you want a friendlier MCP tool name.
- Outputs are inferred heuristically: workflows that contain audio nodes return audio URLs, otherwise image URLs are returned.
- **Default values**: Optional parameters automatically use sensible defaults when not provided. Defaults follow the precedence order (see [Defaults and Configuration](#defaults-and-configuration)).
- Add more workflows and they will show up without extra Python changes, provided they use the placeholder convention above.
- Use `list_workflows` to see all available workflows and `run_workflow` to execute any workflow with custom parameters.

### Available Parameters

#### generate_image Tool

**Required Parameters:**
- `prompt` (string): Text description of the image to generate

**Optional Parameters (with defaults):**
- `seed` (int): Random seed for generation. Auto-generated if not provided.
- `width` (int): Image width in pixels. Default: 512
- `height` (int): Image height in pixels. Default: 512
- `model` (string): Checkpoint model name. Default: "v1-5-pruned-emaonly.ckpt"
- `steps` (int): Number of sampling steps. Default: 20
- `cfg` (float): Classifier-free guidance scale. Default: 8.0
- `sampler_name` (string): Sampling method. Default: "euler"
- `scheduler` (string): Scheduler type. Default: "normal"
- `denoise` (float): Denoising strength (0.0-1.0). Default: 1.0
- `negative_prompt` (string): Negative prompt. Default: "text, watermark"

**Example:**
```python
# Minimal call (uses all defaults)
generate_image(prompt="a beautiful sunset")

# Custom parameters
generate_image(
    prompt="a cyberpunk cityscape",
    model="sd_xl_base_1.0.safetensors",
    width=1024,
    height=768,
    steps=30,
    cfg=7.5
)
```

#### generate_song Tool

**Required Parameters:**
- `tags` (string): Comma-separated descriptive tags for the audio style
- `lyrics` (string): Full lyric text that drives the audio generation

**Optional Parameters (with defaults):**
- `seed` (int): Random seed for generation. Auto-generated if not provided.
- `steps` (int): Number of sampling steps. Default: 50
- `cfg` (float): Classifier-free guidance scale. Default: 5.0
- `seconds` (int): Audio duration in seconds. Default: 60
- `lyrics_strength` (float): How strongly lyrics influence generation (0.0-1.0). Default: 0.99

**Example:**
```python
# Minimal call (uses all defaults - 60 second song)
generate_song(
    tags="electronic, ambient",
    lyrics="In the quiet of the night..."
)

# Custom parameters - 30 second clip with higher quality
generate_song(
    tags="rock, energetic",
    lyrics="Let's rock and roll tonight...",
    seconds=30,
    steps=60,
    cfg=6.0,
    lyrics_strength=0.95
)
```

## MCP Tools Reference

### Core Generation Tools

#### generate_image
Generate images using Stable Diffusion workflows. See [Available Parameters](#available-parameters) section for details.

#### generate_song
Generate audio using AceStep workflows. See [Available Parameters](#available-parameters) section for details.

### Configuration Tools

#### list_models
Returns a list of all available checkpoint models in ComfyUI.

**Returns:**
```json
{
  "models": ["v1-5-pruned-emaonly.ckpt", "sd_xl_base_1.0.safetensors", ...],
  "count": 7,
  "default": "v1-5-pruned-emaonly.ckpt"
}
```

#### get_defaults
Get current effective defaults for image and audio generation. Shows merged values from all sources (runtime, config, env, hardcoded).

**Returns:**
```json
{
  "image": {
    "width": 512,
    "height": 512,
    "model": "v1-5-pruned-emaonly.ckpt",
    "steps": 20,
    "cfg": 8.0,
    ...
  },
  "audio": {
    "steps": 50,
    "cfg": 5.0,
    "model": "ace_step_v1_3.5b.safetensors",
    "seconds": 60,
    ...
  }
}
```

#### set_defaults
Set runtime defaults for image and/or audio generation. Changes are ephemeral unless `persist=true`.

**Parameters:**
- `image` (optional): Dict of default values for image generation
- `audio` (optional): Dict of default values for audio generation
- `persist` (bool): If true, write to config file (`~/.config/comfy-mcp/config.json`)

**Example:**
```python
set_defaults(
    image={"model": "sd_xl_base_1.0.safetensors", "width": 1024},
    audio={"seconds": 30},
    persist=True
)
```

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

**Validation:**
- Model names are validated against available ComfyUI models
- Returns errors if invalid models are specified

### Workflow Registry Tools

#### list_workflows
List all available workflows in the workflow directory.

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
        "width": {"type": "int", "required": false, "description": "..."},
        ...
      },
      "defaults": {},
      "updated_at": null,
      "hash": null
    },
    ...
  ],
  "count": 2,
  "workflow_dir": "/path/to/workflows"
}
```

#### run_workflow
Run any saved ComfyUI workflow with constrained parameter overrides.

**Parameters:**
- `workflow_id` (str): The workflow ID (filename stem, e.g., "generate_image")
- `overrides` (optional): Dict of parameter overrides
- `options` (optional): Reserved for future execution options

**Example:**
```python
run_workflow(
    workflow_id="generate_image",
    overrides={"prompt": "a cat", "width": 1024, "model": "sd_xl_base_1.0.safetensors"}
)
```

**Returns:**
```json
{
  "asset_url": "http://localhost:8188/view?filename=...",
  "image_url": "http://localhost:8188/view?filename=...",
  "workflow_id": "generate_image",
  "prompt_id": "..."
}
```

**Security:**
- Workflow IDs are validated to prevent path traversal attacks
- Only workflows in the allowlisted directory can be executed
- Overrides are constrained to declared parameters (via metadata or PARAM_ placeholders)

## Defaults and Configuration

### Precedence Order

Defaults are resolved in the following order (highest to lowest priority):

1. **Per-call overrides** (highest) - Values explicitly provided in tool calls
2. **Runtime defaults** - Set via `set_defaults` tool (ephemeral)
3. **Config file defaults** - From `~/.config/comfy-mcp/config.json` (persistent)
4. **Environment variables** - `COMFY_MCP_DEFAULT_IMAGE_MODEL`, `COMFY_MCP_DEFAULT_AUDIO_MODEL`
5. **Hardcoded fallbacks** (lowest) - Built-in sensible defaults

### Environment Variables

- `COMFYUI_URL`: ComfyUI server URL (default: `http://localhost:8188`)
- `COMFY_MCP_DEFAULT_IMAGE_MODEL`: Default image model name
- `COMFY_MCP_DEFAULT_AUDIO_MODEL`: Default audio model name
- `COMFY_MCP_WORKFLOW_DIR`: Custom workflow directory path (default: `./workflows`)

### Config File

The server supports a config file at `~/.config/comfy-mcp/config.json`:

```json
{
  "defaults": {
    "image": {
      "model": "sd_xl_base_1.0.safetensors",
      "width": 1024,
      "height": 1024,
      "steps": 30
    },
    "audio": {
      "model": "ace_step_v1_3.5b.safetensors",
      "seconds": 30,
      "steps": 60
    }
  }
}
```

Config file defaults are loaded at startup and persist across server restarts.

### Workflow Metadata (Sidecar Files)

For advanced workflow control, you can create sidecar metadata files (e.g., `generate_image.meta.json`) alongside workflow JSON files:

```json
{
  "name": "Generate Image",
  "description": "Stable Diffusion image generation workflow",
  "defaults": {
    "width": 1024,
    "height": 1024
  },
  "override_mappings": {
    "prompt": [["3", "text"]],
    "width": [["5", "width"]],
    "height": [["5", "height"]]
  },
  "constraints": {
    "width": {"min": 64, "max": 2048, "step": 64},
    "height": {"min": 64, "max": 2048, "step": 64},
    "steps": {"min": 1, "max": 100},
    "cfg": {"min": 1.0, "max": 20.0}
  }
}
```

**Metadata fields:**
- `name`: Human-readable workflow name
- `description`: Workflow description
- `defaults`: Workflow-specific default values
- `override_mappings`: Maps parameter names to `[{node_id, input_name}]` bindings
- `constraints`: Validation rules (min, max, step, enum)

If no metadata file exists, the server automatically infers parameter mappings from `PARAM_*` placeholders in the workflow JSON.

## Project Structure

- `server.py`: MCP server with streamable-http transport and lifecycle support.
- `comfyui_client.py`: Interfaces with ComfyUI's API, handles workflow queuing.
- `client.py`: HTTP-based test client for sending MCP requests.
- `workflows/`: Directory for API-format workflow JSON files.

## Notes

- Ensure your chosen `model` (e.g., `v1-5-pruned-emaonly.ckpt`) exists in `<ComfyUI_dir>/models/checkpoints/`.
- The server uses **streamable-http** transport (HTTP-based, not WebSocket) for better scalability and cloud deployment.
- Server listens on `http://127.0.0.1:9000/mcp` by default (port 9000 for consistency).
- Workflows are automatically discovered from the `workflows/` directory - no code changes needed to add new workflows.
- The server uses JSON-RPC protocol (MCP standard) for all communication.
- For custom workflows, use `PARAM_*` placeholders in workflow JSON files to expose parameters as tool arguments.

## Contributing

Feel free to submit issues or PRs to enhance flexibility (e.g., dynamic node mapping, progress streaming).

## Author

Joe Norton (github.com/joenorton)

## License

Apache License