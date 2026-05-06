# Improvements in this fork

This branch (`feat/improvements`) is the integration trunk of an extensive
homelab deployment of [`joenorton/comfyui-mcp-server`](https://github.com/joenorton/comfyui-mcp-server).
It accumulates ~20 patches (workflow library, multi-backend pool,
LLM-friendly responses, async-completion hardening, more). Each is small
and self-contained; happy to split off individual upstream PRs on request.

Upstream version it tracks: `v1.1.1`.

---

## Headline features

### 1. Multi-backend pool with VRAM-aware routing

**Files**: `comfyui_pool.py` (new), `server.py`, `tools/*.py`

Drop-in replacement for the single `ComfyUIClient` lets one MCP server
front multiple ComfyUI instances. Routing modes:

- **Default**: least-queue across reachable backends; ties broken by env
  insertion order. Backends with `foreign_vram > POOL_MAX_FOREIGN_VRAM_GB`
  (default 4 GB) are excluded — distinguishes "ComfyUI's own warm
  checkpoint" (allowed, fast) from "another process is squatting" (skip).
- **Explicit**: `backend="..."` parameter on every workflow tool wins
  over the filter, useful for force-pinning a specific GPU.

VRAM signal sourced from a companion custom_node
[`ComfyUI-ForeignVRAM`](https://github.com/svilendotorg/ComfyUI-ForeignVRAM)
which exposes `/foreign_vram[?max_foreign_gb=N]` (returns 503 in
healthcheck mode so an upstream Traefik / NGINX can also kick busy
backends out of LB rotation).

Configured via `COMFYUI_URLS=<name1>=<url>,<name2>=<url>,...` env var.

### 2. Async-completion asset registration

**File**: `tools/job.py`

Workflows over the 30 s sync timeout return a `running` handle. Polling
`get_job(prompt_id)` previously returned outputs but never wrote anything
to the `AssetRegistry`, so `list_assets` / `view_image` couldn't see them.
Now `get_job` walks completed-prompt outputs and registers each via
`AssetRegistry.register_asset`. Pool stamps `_pool_backend_url` onto the
returned history dict so the registration uses the correct hostname (not
the localhost fallback).

### 3. LLM-friendly response shape

**Files**: `tools/helpers.py`, `tools/job.py`, `managers/workflow_manager.py`

Every workflow + `get_job` response now includes:

- **`markdown_preview`** — ready-to-paste markdown snippet. Image MIMEs
  → `![alt](url)` (Claude Desktop renders inline images in chat). Audio
  → `[🔊 filename](url)`. Video → `[🎬 filename](url)`. 3D → `[🎲 ...](url)`.
- **Tool description hints** — workflow tool descriptions now end with
  guidance: pass `topic` for searchable filenames, paste `markdown_preview`
  in the reply for inline display.

### 4. Optional `topic` param + auto-derive

**Files**: `managers/workflow_manager.py`, `tools/generation.py`

Every workflow tool now accepts an optional `topic: str` argument
(1–2 word slug, e.g. `giraffe`, `forest_scene`). Server slugifies
(lowercase, alnum + underscore, max 30 chars) and injects between the
date and workflow id in `filename_prefix`:

```
images/2026-05-03-giraffe_picture_sdxl_t2i_00001_.png
```

When the LLM skips `topic`, the server auto-derives a slug:

1. From `prompt` / `tags` (drop English stopwords + generic words like
   `realistic`, `image`, `photo`; take first 3 surviving tokens).
2. For prompt-less workflows (`hunyuan3d_*`, `sonic_a2v`), parse the
   source `image` / `image_last` / `audio` filename — strip
   `_NNNNN_` / known suffixes / leading date — carry that slug forward.
   Lets a chain like `sdxl_t2i → hunyuan3d_i2mesh` keep one coherent topic.

### 5. Friendlier image / audio inputs

**Files**: `tools/generation.py`, `tools/workflow.py`, `tools/helpers.py`

`image`, `image_last`, and `audio` parameters now accept any of:

- A full URL (existing behaviour — auto-uploaded to ComfyUI's `input/`).
- An `asset_id` returned by a previous tool call (resolved via
  `AssetRegistry.get_asset` → asset URL → uploaded).
- A bare output filename (resolved via
  `AssetRegistry.get_asset_by_identity` scan over the known output
  subfolders → URL → uploaded).

Lets the LLM chain workflows naturally without manually constructing
URLs.

### 6. `upload_file` MCP tool

**File**: `tools/upload.py` (new)

A new MCP tool for pushing arbitrary binary files (images / audio / video)
into ComfyUI's input folder via base64. Single-shot for ≤ 100 KB; chunked
mode (`chunk_index` + `total_chunks` + `upload_id`) for larger files
(≤ 100 MB total) so the LLM doesn't have to stuff multi-MB base64 into a
single tool call.

### 7. Workflow library

**Files**: `workflows/*.json`, `workflows/*.meta.json`

42 workflow JSONs covering image / audio / video / 3D mesh tasks plus
matching `<id>.meta.json` sidecars (timing, resolution, best-for, key
params). Each `*.meta.json` is read by `_load_workflow_metadata` and
becomes the MCP tool description.

`*.json` filename → MCP tool ID (`wan22_i2v.json` → `wan22_i2v`).

Naming convention: `{model}_{task}[_{variant}]` — tasks include `t2i`
`i2i` `t2v` `i2v` `d2v` `fl2v` `t2a` `t2mv` `i2mesh` `a2v`. Namespace
(image / video / audio / mesh) auto-detected from the task suffix.

### 8. Output subfolder convention

Every workflow's `filename_prefix` writes into a typed subfolder of
`output/`:

| Subfolder | Workflows |
|-----------|-----------|
| `images/` | `*_t2i*`, `*_i2i*` |
| `audio/`  | `*_t2a*` |
| `video/`  | `*_t2v*`, `*_i2v*`, `*_fl2v*`, `*_d2v*`, `sonic_a2v` |
| `mesh/`   | `hunyuan3d_*` |

Combined with topic injection + per-instance `COMFYUI_OUTPUT_SUFFIX`,
filenames look like
`images/2026-05-03-giraffe_sdxl_t2i_comfyui1_00001_.png` — typed
location + topic + GPU-of-origin in the name itself.

### 9. Mesh / 3D output keys

**Files**: `managers/workflow_manager.py`, `comfyui_client.py`

Output-key matching previously knew only `images / image / gifs / gif /
audio / audios / files`. Hunyuan3D workflows emit a `3d` key that didn't
match — files landed on disk but the MCP raised an exception and the LLM
never saw the asset. Adds `MESH_OUTPUT_KEYS = ("3d", "mesh", "glb",
"gltf", "obj")` and extends `_guess_output_preferences` to detect
mesh-class workflows (any `hy3d` / `hunyuan3d` / `mesh` / `3d` substring
in the node `class_type`).

### 10. `render_workflow` `%date:...%` substitution + cross-platform path
separator + asset-URL backend stamping

**File**: `managers/workflow_manager.py`, `comfyui_client.py`,
`tools/helpers.py`

Misc fixes that surface only when running real workflows:

- Substitute `%date:yyyy-MM-dd%` patterns in `filename_prefix` at submit
  time (ComfyUI's native `SaveImage` doesn't do it).
- Translate model paths between Windows (backslash) and Linux (forward
  slash) so the same workflow JSON runs on either backend.
- Pool stamps `result["backend_url"] = client.base_url` after submit so
  asset URLs returned to the caller point at the actual backend hostname,
  not the registry's localhost default.
- `workflow_manager._load_workflows` skips `*.meta.json` sidecars when
  globbing `*.json` (otherwise they were loaded as workflows, raising
  `AttributeError: 'str' object has no attribute 'get'`).

### 11. Workflow JSON fixes

A pile of small `*.json` corrections: `EmptyFlux2LatentImage` /
`EmptyLTXVLatentVideo` `batch_size` copy-paste bugs (set to `1`),
`ResizeImageMaskNode` DynamicCombo dot-prefix sub-fields,
`ComfyMathExpression` `values.a` / `values.b` re-binding, removed
`ClownSampler` paths from LTX-2.3 workflows (custom node not installed),
`PARAM_AUDIO` injection for `LoadAudio` nodes that previously had
hard-coded filenames, second `LoadImage` node in `wan22_fl2v` correctly
bound to `PARAM_IMAGE_LAST` (was duplicating `PARAM_IMAGE`).

Detailed per-fix notes live in the corresponding commit messages.

### 12. Per-workflow tool registration is now opt-in

**File**: `server.py`

Every `*.json` in `workflows/` was previously registered both as a typed
MCP tool *and* via the existing `run_workflow` / `list_workflows`
dispatcher. With ~40 workflows that doubles up to ~20k tokens of MCP
tool-schema context every time a client connects — a meaningful cost on
top of the dispatcher that already exposes the same capability.

Behavior is now gated on `COMFY_MCP_REGISTER_PER_WORKFLOW_TOOLS` (default
`false`):

- **`false` (default)**: workflows are reachable through the dispatcher
  pair only — `list_workflows()` returns the catalog with each workflow's
  `available_inputs` (name, type, required, description), and
  `run_workflow(workflow_id, overrides={...})` executes them. Saves
  ~500 tokens per workflow in client context.
- **`true`**: legacy layout — every workflow JSON registers as its own
  typed MCP tool (`sdxl_t2i`, `flux_klein_9b_t2i`, ...) with full
  parameter schema. Use this if your client benefits from the explicit
  per-workflow function signatures.

`regenerate` is unaffected and always registered. The dispatcher
(`run_workflow` / `list_workflows`) is unchanged and was already part of
the upstream surface — this patch just stops doubling up by default.

---

## How to install this fork

```bash
git clone https://github.com/svilendotorg/ComfyUI-MCP-Server
cd ComfyUI-MCP-Server
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
COMFYUI_URLS="local=http://127.0.0.1:8188" python server.py
```

Default branch is `feat/improvements`, so cloning lands on the patched
code automatically.

To track upstream:

```bash
git remote add upstream https://github.com/joenorton/comfyui-mcp-server.git
git fetch upstream
git rebase upstream/main
git push --force-with-lease
```

Most likely conflicts are in `managers/workflow_manager.py` (touched by
several patches). Resolve, then `git rebase --continue`.

---

## Splitting into smaller upstream PRs

If you'd rather pull individual fixes / features into upstream, the
approach is:

```bash
git checkout -b pr/<topic> upstream/main
git cherry-pick <sha>          # one or more
git push origin pr/<topic>
gh pr create --repo joenorton/comfyui-mcp-server
```

The commit history on this branch is roughly grouped by feature, so
`git log --oneline upstream/main..feat/improvements` gives a reasonable
starting point.
