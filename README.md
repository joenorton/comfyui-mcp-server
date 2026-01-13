# ComfyUI MCP Server

A lightweight MCP (Model Context Protocol) server that lets AI agents generate and iteratively refine images, audio, and video using a local ComfyUI instance.

You run the server, connect a client, and issue tool calls. Everything else is optional depth.

---

## Quick Start (2–3 minutes)

This proves everything is working.

### 1) Clone and set up

```bash
git clone https://github.com/joenorton/comfyui-mcp-server.git
cd comfyui-mcp-server
pip install -r requirements.txt
```

### 2) Start ComfyUI

Make sure ComfyUI is installed and running locally.

```bash
cd <ComfyUI_dir>
python main.py --port 8188
```

### 3) Run the MCP server

From the repository directory:

```bash
python server.py
```

The server listens at:

```
http://127.0.0.1:9000/mcp
```

### 3) Verify it works (no AI client required)

Run the included test client:

```bash
# Use default prompt
python test_client.py

# Or provide your own prompt
python test_client.py -p "a beautiful sunset over mountains"
python test_client.py --prompt "a cat on a mat"
```

`test_client.py` will:

* connect to the MCP server
* list available tools
* fetch and display server defaults (width, height, steps, model, etc.)
* run `generate_image` with your prompt (or a default)
* automatically use server defaults for all other parameters
* print the resulting asset information

If this step succeeds, the system is working.

**Note:** The test client respects server defaults configured via config files, environment variables, or `set_defaults` calls. Only the `prompt` parameter is required; all other parameters use server defaults automatically.

That’s it.

---

## Use with an AI Agent (Cursor / Claude / n8n)

Once the server is running, you can connect it to an AI client.

Create a project-scoped `.mcp.json` file:

```json
{
  "mcpServers": {
    "comfyui-mcp-server": {
      "type": "http",
      "url": "http://127.0.0.1:9000/mcp"
    }
  }
}
```

Restart your AI client. You can now call tools such as:

* `generate_image`
* `view_image`
* `regenerate`
* `get_job`
* `list_assets`

This is the primary intended usage mode.

---

## What You Can Do After It Works

Once you’ve confirmed the server runs and a client can connect, the system supports:

* Iterative refinement via `regenerate` (no re-prompting)
* Explicit asset identity for reliable follow-ups
* Job polling and cancellation for long-running generations
* Optional image injection into the AI’s context (`view_image`)
* Auto-discovered ComfyUI workflows with parameter exposure
* Configurable defaults to avoid repeating common settings

Everything below builds on the same basic loop you just tested.

## Migration Notes (Previous Versions)

If you’ve used earlier versions of this project, a few things have changed.

### What’s the Same
- You still run a local MCP server that delegates execution to ComfyUI
- Workflows are still JSON files placed in the `workflows/` directory
- Image generation behavior is unchanged at its core

### What’s New
- **Streamable HTTP transport** replaces the older WebSocket-based approach
- **Explicit job management** (`get_job`, `get_queue_status`, `cancel_job`)
- **Asset identity** instead of ad-hoc URLs (stable across hostname changes)
- **Iteration support** via `regenerate` (replay with parameter overrides)
- **Optional visual feedback** for agents via `view_image`
- **Configurable defaults** to avoid repeating common parameters

### What Changed Conceptually
Earlier versions were a thin request/response bridge.
The current version is built around **iteration** and **stateful control loops**.

You can still generate an image with a single call, but you now have the option to:
- refer back to specific outputs
- refine results without re-specifying everything
- poll and cancel long-running jobs
- let AI agents inspect generated images directly

### Looking for the Old Behavior?
If you want the minimal, single-shot behavior from earlier versions:
- run `test_client.py` (this mirrors the original usage pattern)
- call `generate_image` with just a prompt (server defaults handle the rest)
- ignore the additional tools

No migration is required unless you want the new capabilities.

## Available Tools

### Generation Tools

- **`generate_image`**: Generate images (requires `prompt`)
- **`generate_song`**: Generate audio (requires `tags` and `lyrics`)
- **`regenerate`**: Regenerate an existing asset with optional parameter overrides (requires `asset_id`)

### Viewing Tools

- **`view_image`**: View generated images inline (images only, not audio/video)

### Job Management Tools

- **`get_queue_status`**: Check ComfyUI queue state (running/pending jobs) - provides async awareness
- **`get_job`**: Poll job completion status by prompt_id - check if a job has finished
- **`list_assets`**: Browse recently generated assets - enables AI memory and iteration
- **`get_asset_metadata`**: Get full provenance and parameters for an asset - includes workflow history
- **`cancel_job`**: Cancel a queued or running job

### Configuration Tools

- **`list_models`**: List available ComfyUI models
- **`get_defaults`**: Get current default values
- **`set_defaults`**: Set default values (with optional persistence)

### Workflow Tools

- **`list_workflows`**: List all available workflows
- **`run_workflow`**: Run any workflow with custom parameters

## Custom Workflows

Add custom workflows by placing JSON files in the `workflows/` directory. Workflows are automatically discovered and exposed as MCP tools.

### Workflow Placeholders

Use `PARAM_*` placeholders in workflow JSON to expose parameters:

- `PARAM_PROMPT` → `prompt: str` (required)
- `PARAM_INT_STEPS` → `steps: int` (optional)
- `PARAM_FLOAT_CFG` → `cfg: float` (optional)

**Example:**
```json
{
  "3": {
    "inputs": {
      "text": "PARAM_PROMPT",
      "steps": "PARAM_INT_STEPS"
    }
  }
}
```

The tool name is derived from the filename (e.g., `my_workflow.json` → `my_workflow` tool).

---

## Configuration

The server supports configurable defaults to avoid repeating common parameters. Defaults can be set via:

- **Runtime defaults**: Use `set_defaults` tool (ephemeral, lost on restart)
- **Config file**: `~/.config/comfy-mcp/config.json` (persistent)
- **Environment variables**: `COMFY_MCP_DEFAULT_*` prefixed variables

Defaults are resolved in priority order: per-call values → runtime defaults → config file → environment variables → hardcoded defaults.

For complete configuration details, see [docs/REFERENCE.md](docs/REFERENCE.md#parameters).

---

## Detailed Reference

Complete parameter lists, return schemas, configuration options, and advanced workflow metadata are documented in:

- **[API Reference](docs/REFERENCE.md)** - Complete tool reference, parameters, return values, and configuration
- **[Architecture](docs/ARCHITECTURE.md)** - Design decisions and system overview

## Project Structure

```
comfyui-mcp-server/
├── server.py              # Main entry point
├── comfyui_client.py      # ComfyUI API client
├── asset_processor.py     # Image processing utilities
├── test_client.py         # Test client
├── managers/              # Core managers
│   ├── workflow_manager.py
│   ├── defaults_manager.py
│   └── asset_registry.py
├── tools/                 # MCP tool implementations
│   ├── generation.py
│   ├── asset.py
│   ├── job.py             # Job management tools
│   ├── configuration.py
│   └── workflow.py
├── models/                # Data models
│   ├── workflow.py
│   └── asset.py
└── workflows/             # Workflow JSON files
    ├── generate_image.json
    └── generate_song.json
```

## Notes

- Ensure your models exist in `<ComfyUI_dir>/models/checkpoints/`
- Server uses **streamable-http** transport (HTTP-based, not WebSocket)
- Workflows are auto-discovered - no code changes needed
- Assets expire after 24 hours (configurable)
- `view_image` only supports images (PNG, JPEG, WebP, GIF)
- Asset identity uses `(filename, subfolder, type)` instead of URL for robustness
- Full workflow history is stored for provenance and reproducibility
- `regenerate` uses stored workflow data to recreate assets with parameter overrides
- Session isolation: `list_assets` can filter by session for clean AI agent context

## Known Limitations (v1.0)

- **Ephemeral asset registry**: `asset_id` references are only valid while the MCP server is running (and until TTL expiry). After restart, previously-issued `asset_id`s can't be resolved.

## Contributing

Issues and pull requests are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## Acknowledgements

- [@venetanji](https://github.com/venetanji) - streamable-http rewrite foundation & PARAM_* system

## Maintainer
[@joenorton](https://github.com/joenorton)

## License

Apache License 2.0
