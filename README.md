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
- **Default values**: Optional parameters automatically use sensible defaults when not provided. Defaults are workflow-specific (e.g., audio workflows use different step/cfg defaults than image workflows).
- Add more workflows and they will show up without extra Python changes, provided they use the placeholder convention above.

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

#### list_available_models Tool

- Returns a list of all available checkpoint models in ComfyUI
- Helps AI agents choose appropriate models for different tasks
- Returns: `{"models": [...], "count": N, "default": "..."}`

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

## License

Apache License