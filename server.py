import copy
import inspect
import json
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Sequence, Tuple

from mcp.server.fastmcp import FastMCP
from comfyui_client import ComfyUIClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MCP_Server")

PLACEHOLDER_PREFIX = "PARAM_"
PLACEHOLDER_TYPE_HINTS = {
    "STR": str,
    "STRING": str,
    "TEXT": str,
    "INT": int,
    "FLOAT": float,
    "BOOL": bool,
}
PLACEHOLDER_DESCRIPTIONS = {
    "prompt": "Main text prompt used inside the workflow.",
    "seed": "Random seed for image generation. If not provided, a random seed will be generated.",
    "width": "Image width in pixels. Default: 512.",
    "height": "Image height in pixels. Default: 512.",
    "model": "Checkpoint model name (e.g., 'v1-5-pruned-emaonly.ckpt', 'sd_xl_base_1.0.safetensors'). Default: 'v1-5-pruned-emaonly.ckpt'.",
    "steps": "Number of sampling steps. Higher = better quality but slower. Default: 20.",
    "cfg": "Classifier-free guidance scale. Higher = more adherence to prompt. Default: 8.0.",
    "sampler_name": "Sampling method (e.g., 'euler', 'dpmpp_2m', 'ddim'). Default: 'euler'.",
    "scheduler": "Scheduler type (e.g., 'normal', 'karras', 'exponential'). Default: 'normal'.",
    "denoise": "Denoising strength (0.0-1.0). Default: 1.0.",
    "negative_prompt": "Negative prompt to avoid certain elements. Default: 'text, watermark'.",
    "tags": "Comma-separated descriptive tags for the audio model.",
    "lyrics": "Full lyric text that should drive the audio generation.",
    "seconds": "Audio duration in seconds. Default: 60 (1 minute).",
    "lyrics_strength": "How strongly lyrics influence audio generation (0.0-1.0). Default: 0.99.",
}
DEFAULT_OUTPUT_KEYS = ("images", "image", "gifs", "gif")
AUDIO_OUTPUT_KEYS = ("audio", "audios", "sound", "files")
WORKFLOW_DIR = Path(__file__).parent / "workflows"


@dataclass
class WorkflowParameter:
    name: str
    placeholder: str
    annotation: type
    description: str
    bindings: list[Tuple[str, str]] = field(default_factory=list)
    required: bool = True


@dataclass
class WorkflowToolDefinition:
    workflow_id: str
    tool_name: str
    description: str
    template: Dict[str, Any]
    parameters: "OrderedDict[str, WorkflowParameter]"
    output_preferences: Sequence[str]


class WorkflowManager:
    def __init__(self, workflows_dir: Path):
        self.workflows_dir = workflows_dir
        self._tool_names: set[str] = set()
        self.tool_definitions = self._load_workflows()

    def _load_workflows(self):
        definitions: list[WorkflowToolDefinition] = []
        if not self.workflows_dir.exists():
            logger.info("Workflow directory %s does not exist yet", self.workflows_dir)
            return definitions

        for workflow_path in sorted(self.workflows_dir.glob("*.json")):
            try:
                with open(workflow_path, "r", encoding="utf-8") as handle:
                    workflow = json.load(handle)
            except json.JSONDecodeError as exc:
                logger.error("Skipping workflow %s due to JSON error: %s", workflow_path.name, exc)
                continue

            parameters = self._extract_parameters(workflow)
            if not parameters:
                logger.info(
                    "Workflow %s has no %s placeholders; skipping auto-tool registration",
                    workflow_path.name,
                    PLACEHOLDER_PREFIX,
                )
                continue

            tool_name = self._dedupe_tool_name(self._derive_tool_name(workflow_path.stem))
            definition = WorkflowToolDefinition(
                workflow_id=workflow_path.stem,
                tool_name=tool_name,
                description=self._derive_description(workflow_path.stem),
                template=workflow,
                parameters=parameters,
                output_preferences=self._guess_output_preferences(workflow),
            )
            logger.info(
                "Prepared workflow tool '%s' from %s with params %s",
                tool_name,
                workflow_path.name,
                list(parameters.keys()),
            )
            definitions.append(definition)

        return definitions

    def render_workflow(self, definition: WorkflowToolDefinition, provided_params: Dict[str, Any]):
        workflow = copy.deepcopy(definition.template)
        
        # Workflow-specific default values
        if definition.workflow_id == "generate_image":
            defaults = {
                "width": 512,
                "height": 512,
                "steps": 20,
                "cfg": 8.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": "v1-5-pruned-emaonly.ckpt",
                "negative_prompt": "text, watermark",
            }
        elif definition.workflow_id == "generate_song":
            defaults = {
                "steps": 50,
                "cfg": 5.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "seconds": 60,
                "lyrics_strength": 0.99,
                "model": "ace_step_v1_3.5b.safetensors",
            }
        else:
            defaults = {}
        
        for param in definition.parameters.values():
            if param.required and param.name not in provided_params:
                raise ValueError(f"Missing required parameter '{param.name}'")
            
            # Use provided value, default, or generate (for seed)
            raw_value = provided_params.get(param.name)
            if raw_value is None:
                if param.name == "seed" and param.annotation is int:
                    # Special handling for seed - generate random
                    import random
                    raw_value = random.randint(0, 2**32 - 1)
                    logger.debug(f"Generated random seed: {raw_value}")
                elif param.name in defaults:
                    # Use default value
                    raw_value = defaults[param.name]
                    logger.debug(f"Using default value for {param.name}: {raw_value}")
                else:
                    # Skip parameters without defaults
                    continue
            
            coerced_value = self._coerce_value(raw_value, param.annotation)
            for node_id, input_name in param.bindings:
                workflow[node_id]["inputs"][input_name] = coerced_value
        
        return workflow

    def _extract_parameters(self, workflow: Dict[str, Any]):
        parameters: "OrderedDict[str, WorkflowParameter]" = OrderedDict()
        for node_id, node in workflow.items():
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue
            for input_name, value in inputs.items():
                parsed = self._parse_placeholder(value)
                if not parsed:
                    continue
                param_name, annotation, placeholder_value = parsed
                description = PLACEHOLDER_DESCRIPTIONS.get(
                    param_name, f"Value for '{param_name}'."
                )
                parameter = parameters.get(param_name)
                if not parameter:
                    # Make seed and other optional parameters non-required
                    # Only 'prompt' should be required for generate_image
                    # Only 'tags' and 'lyrics' should be required for generate_song
                    optional_params = {
                        "seed", "width", "height", "model", "steps", "cfg",
                        "sampler_name", "scheduler", "denoise", "negative_prompt",
                        "seconds", "lyrics_strength"  # Audio-specific optional params
                    }
                    is_required = param_name not in optional_params
                    parameter = WorkflowParameter(
                        name=param_name,
                        placeholder=placeholder_value,
                        annotation=annotation,
                        description=description,
                        required=is_required,
                    )
                    parameters[param_name] = parameter
                parameter.bindings.append((node_id, input_name))
        return parameters

    def _parse_placeholder(self, value):
        if not isinstance(value, str) or not value.startswith(PLACEHOLDER_PREFIX):
            return None
        token = value[len(PLACEHOLDER_PREFIX) :]
        annotation = str
        if "_" in token:
            type_candidate, remainder = token.split("_", 1)
            type_hint = PLACEHOLDER_TYPE_HINTS.get(type_candidate.upper())
            if type_hint:
                annotation = type_hint
                token = remainder
        param_name = self._normalize_name(token)
        return param_name, annotation, value

    def _normalize_name(self, raw: str):
        cleaned = [
            (char.lower() if char.isalnum() else "_")
            for char in raw.strip()
        ]
        normalized = "".join(cleaned).strip("_")
        return normalized or "param"

    def _derive_tool_name(self, stem: str):
        return self._normalize_name(stem)

    def _dedupe_tool_name(self, base_name: str):
        name = base_name or "workflow_tool"
        if name not in self._tool_names:
            self._tool_names.add(name)
            return name
        suffix = 2
        while f"{name}_{suffix}" in self._tool_names:
            suffix += 1
        deduped = f"{name}_{suffix}"
        self._tool_names.add(deduped)
        return deduped

    def _derive_description(self, stem: str):
        readable = stem.replace("_", " ").replace("-", " ").strip()
        readable = readable if readable else stem
        return f"Execute the '{readable}' ComfyUI workflow."

    def _guess_output_preferences(self, workflow: Dict[str, Any]):
        for node in workflow.values():
            class_type = str(node.get("class_type", "")).lower()
            if "audio" in class_type:
                return AUDIO_OUTPUT_KEYS
        return DEFAULT_OUTPUT_KEYS

    def _coerce_value(self, value: Any, annotation: type):
        """Coerce a value to the specified type with proper error handling."""
        try:
            if annotation is str:
                return str(value)
            if annotation is int:
                return int(value)
            if annotation is float:
                return float(value)
            if annotation is bool:
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    return value.strip().lower() in {"1", "true", "yes", "y"}
                return bool(value)
            return value
        except (ValueError, TypeError) as e:
            raise ValueError(f"Cannot convert {value!r} to {annotation.__name__}: {e}")

# Global ComfyUI client (fallback since context isn’t available)
import os
comfyui_url = os.getenv("COMFYUI_URL", "http://localhost:8188")
comfyui_client = ComfyUIClient(comfyui_url)
workflow_manager = WorkflowManager(WORKFLOW_DIR)

# Define application context (for future use)
class AppContext:
    def __init__(self, comfyui_client: ComfyUIClient):
        self.comfyui_client = comfyui_client

# Lifespan management (placeholder for future context support)
@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle"""
    logger.info("Starting MCP server lifecycle...")
    try:
        # Startup: Could add ComfyUI health check here in the future
        logger.info("ComfyUI client initialized globally")
        yield AppContext(comfyui_client=comfyui_client)
    finally:
        # Shutdown: Cleanup (if needed)
        logger.info("Shutting down MCP server")

# Initialize FastMCP with lifespan and port configuration
# Using port 9000 for consistency with previous version
# Enable stateless_http to avoid requiring session management
mcp = FastMCP(
    "ComfyUI_MCP_Server",
    lifespan=app_lifespan,
    port=9000,
    stateless_http=True
)


@mcp.tool()
def list_available_models() -> dict:
    """List all available checkpoint models in ComfyUI.
    
    Returns a list of model names that can be used with the generate_image tool.
    This helps AI agents choose appropriate models for different use cases.
    """
    models = comfyui_client.available_models
    return {
        "models": models,
        "count": len(models),
        "default": "v1-5-pruned-emaonly.ckpt" if models else None
    }


def _register_workflow_tool(definition: WorkflowToolDefinition):
    def _tool_impl(*args, **kwargs):
        # Coerce parameter types before signature binding
        # MCP/JSON-RPC may pass numbers as strings, so we need to convert them
        coerced_kwargs = {}
        param_dict = {p.name: p for p in definition.parameters.values()}
        
        for key, value in kwargs.items():
            if key in param_dict:
                param = param_dict[key]
                # Coerce to correct type if needed
                if value is not None:
                    try:
                        # Handle string representations of numbers
                        if param.annotation is int:
                            if isinstance(value, str) and value.strip().isdigit():
                                coerced_kwargs[key] = int(value)
                            elif isinstance(value, (int, float)):
                                coerced_kwargs[key] = int(value)
                            else:
                                coerced_kwargs[key] = value
                        elif param.annotation is float:
                            if isinstance(value, str):
                                coerced_kwargs[key] = float(value)
                            elif isinstance(value, (int, float)):
                                coerced_kwargs[key] = float(value)
                            else:
                                coerced_kwargs[key] = value
                        else:
                            coerced_kwargs[key] = value
                    except (ValueError, TypeError) as e:
                        # If coercion fails, use original value and let validation handle it
                        logger.warning(f"Failed to coerce {key}={value!r} to {param.annotation.__name__}: {e}")
                        coerced_kwargs[key] = value
                else:
                    coerced_kwargs[key] = None
            else:
                # Unknown parameter, pass through
                coerced_kwargs[key] = value
        
        bound = _tool_impl.__signature__.bind(*args, **coerced_kwargs)
        bound.apply_defaults()
        try:
            workflow = workflow_manager.render_workflow(definition, dict(bound.arguments))
            result = comfyui_client.run_custom_workflow(
                workflow,
                preferred_output_keys=definition.output_preferences,
            )
            return {
                "asset_url": result["asset_url"],
                "image_url": result["asset_url"],  # Backward compatibility
                "workflow_id": definition.workflow_id,
                "tool": definition.tool_name,
            }
        except Exception as exc:
            logger.exception("Workflow '%s' failed", definition.workflow_id)
            return {"error": str(exc)}

    # Separate required and optional parameters to ensure correct ordering
    required_params = []
    optional_params = []
    annotations: Dict[str, Any] = {}
    
    for param in definition.parameters.values():
        # For numeric types, use Any to allow string coercion from JSON-RPC
        # FastMCP/Pydantic validation is strict, so we accept Any and validate/coerce ourselves
        if param.annotation in (int, float):
            # Use Any to bypass strict type checking, we'll coerce in the function
            annotation_type = Any
        else:
            annotation_type = param.annotation
        
        if param.required:
            parameter = inspect.Parameter(
                name=param.name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=annotation_type,
            )
            required_params.append(parameter)
        else:
            # Optional parameter with default value
            # For numeric types, use Any directly (not Optional[Any]) to allow string coercion
            if param.annotation in (int, float):
                final_annotation = Any
            else:
                final_annotation = Optional[annotation_type]
            parameter = inspect.Parameter(
                name=param.name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=final_annotation,
                default=None,
            )
            optional_params.append(parameter)
        annotations[param.name] = param.annotation
    
    # Combine: required parameters first, then optional
    parameters = required_params + optional_params
    annotations["return"] = dict
    _tool_impl.__signature__ = inspect.Signature(parameters, return_annotation=dict)
    _tool_impl.__annotations__ = annotations
    _tool_impl.__name__ = f"tool_{definition.tool_name}"
    _tool_impl.__doc__ = definition.description
    mcp.tool(name=definition.tool_name, description=definition.description)(_tool_impl)
    logger.info(
        "Registered MCP tool '%s' for workflow '%s'",
        definition.tool_name,
        definition.workflow_id,
    )


if workflow_manager.tool_definitions:
    for tool_definition in workflow_manager.tool_definitions:
        _register_workflow_tool(tool_definition)
else:
    logger.info(
        "No workflow placeholders found in %s; add %s markers to enable auto tools",
        WORKFLOW_DIR,
        PLACEHOLDER_PREFIX,
    )

if __name__ == "__main__":
    import sys
    # Check if running as MCP command (stdio) or standalone (streamable-http)
    # When run as command by MCP client (like Cursor), use stdio transport
    # When run standalone, use streamable-http for HTTP access
    if len(sys.argv) > 1 and sys.argv[1] == "--stdio":
        logger.info("Starting MCP server with stdio transport (for MCP clients)")
        mcp.run(transport="stdio")
    else:
        logger.info("Starting MCP server with streamable-http transport on http://127.0.0.1:9000/mcp")
        mcp.run(transport="streamable-http")
