[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/joenorton-comfyui-mcp-server-badge.png)](https://mseep.ai/app/joenorton-comfyui-mcp-server)

# ComfyUI MCP Server

A lightweight Python-based MCP (Model Context Protocol) server that interfaces with a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instance to generate images programmatically via AI agent requests.

## Overview

This project enables AI agents to send image generation requests to ComfyUI using the MCP protocol over WebSocket. It supports:
- Flexible workflow selection (e.g., `basic_api_test.json`).
- Dynamic parameters: `prompt`, `width`, `height`, and `model`.
- Returns image URLs served by ComfyUI.

## Prerequisites

- **Python 3.10+**
- **ComfyUI**: Installed and running locally (e.g., on `localhost:8188`).
- **Dependencies**: `requests`, `websockets`, `mcp` (install via pip).

## Setup

1. **Clone the Repository**:
   git clone <your-repo-url>
   cd comfyui-mcp-server

2. **Install Dependencies**:

   pip install requests websockets mcp


3. **Start ComfyUI**:
- Install ComfyUI (see [ComfyUI docs](https://github.com/comfyanonymous/ComfyUI)).
- Run it on port 8188:
  ```
  cd <ComfyUI_dir>
  python main.py --port 8188
  ```

4. **Prepare Workflows**:
- Place API-format workflow files (e.g., `basic_api_test.json`) in the `workflows/` directory.
- Export workflows from ComfyUI’s UI with “Save (API Format)” (enable dev mode in settings).

## Usage

1. **Run the MCP Server**:
   python server.py

- Listens on `ws://localhost:9000`.

2. **Test with the Client**:
   python client.py

- Sends a sample request: `"a dog wearing sunglasses"` with `512x512` using `sd_xl_base_1.0.safetensors`.
- Output example:
  ```
  Response from server:
  {
    "image_url": "http://localhost:8188/view?filename=ComfyUI_00001_.png&subfolder=&type=output"
  }
  ```

3. **Custom Requests**:
- Modify `client.py`’s `payload` to change `prompt`, `width`, `height`, `workflow_id`, or `model`.
- Example:
  ```
  "params": json.dumps({
      "prompt": "a cat in space",
      "width": 768,
      "height": 768,
      "workflow_id": "basic_api_test",
      "model": "v1-5-pruned-emaonly.ckpt"
  })
  ```

## Project Structure

- `server.py`: MCP server with WebSocket transport and lifecycle support.
- `comfyui_client.py`: Interfaces with ComfyUI’s API, handles workflow queuing.
- `client.py`: Test client for sending MCP requests.
- `workflows/`: Directory for API-format workflow JSON files.

## Notes

- Ensure your chosen `model` (e.g., `v1-5-pruned-emaonly.ckpt`) exists in `<ComfyUI_dir>/models/checkpoints/`.
- The MCP SDK lacks native WebSocket transport; this uses a custom implementation.
- For custom workflows, adjust node IDs in `comfyui_client.py`’s `DEFAULT_MAPPING` if needed.

## Contributing

Feel free to submit issues or PRs to enhance flexibility (e.g., dynamic node mapping, progress streaming).

## License

Apache License