"""Workflow management for loading and processing ComfyUI workflows"""

import copy
import json
import logging
import random
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from models.workflow import WorkflowParameter, WorkflowToolDefinition

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
    "duration": "Video duration in seconds. Default: 5.",
    "fps": "Frames per second for video output. Default: 16.",
}
DEFAULT_OUTPUT_KEYS = ("images", "image", "gifs", "gif")
AUDIO_OUTPUT_KEYS = ("audio", "audios", "sound", "files")
VIDEO_OUTPUT_KEYS = ("videos", "video", "mp4", "mov", "webm")




import re as _topic_re

_TOPIC_DATE_TOKEN = _topic_re.compile(r"(%date:[^%]+%-)")


def _slugify_topic(value: str) -> str:
    """Lower-case, alnum + underscore only, length-capped."""
    if not isinstance(value, str):
        return ""
    s = _topic_re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").lower()
    return s[:30]


_TOPIC_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "with", "for", "to",
    "is", "are", "was", "were", "be", "been", "being", "this", "that",
    "these", "those", "it", "its", "there", "by", "as", "from", "or",
    "and", "but", "not", "no", "into", "onto", "out", "up", "down",
    "over", "under", "some", "any", "all", "each", "very", "really",
    "realistic", "photo", "photograph", "image", "picture", "render",
    "generate", "create", "make", "give", "show",
}


def _auto_topic_from_text(text: str) -> str:
    """Derive a slug from a prompt-like string when the LLM skipped 'topic'.

    Strategy: lowercase, take alphabetic tokens, drop English stopwords + a few
    generic 'image'-type words, keep the first 2-3 surviving tokens.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    tokens = _topic_re.findall(r"[A-Za-z]+", text.lower())
    keep = [t for t in tokens if t not in _TOPIC_STOPWORDS]
    if not keep:
        return ""
    return _slugify_topic("_".join(keep[:3]))


def _inject_topic_into_filename_prefix(workflow: dict, topic: str, fallback_text: str = "") -> None:
    """Mutate workflow in place: insert `<topic>_` after the date token in
    every Save* node's filename_prefix.

    If `topic` is empty, derive a slug from `fallback_text` (typically the
    workflow's prompt / tags). No-op if both are empty or the pattern is missing.
    """
    slug = _slugify_topic(topic) or _auto_topic_from_text(fallback_text)
    if not slug:
        return
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inp = node.get("inputs", {})
        fp = inp.get("filename_prefix")
        if not isinstance(fp, str):
            continue
        if "%date:" not in fp:
            continue
        # Skip if slug is already there (idempotent)
        if f"{slug}_" in fp:
            continue
        inp["filename_prefix"] = _TOPIC_DATE_TOKEN.sub(rf"\1{slug}_", fp, count=1)




# Workflow IDs are appended at the end of legacy filenames; we strip them when
# back-deriving a slug from a source asset filename. Filled lazily by
# WorkflowManager when it loads workflows.
_KNOWN_WORKFLOW_IDS: list = []


def _topic_from_filename(fname: str) -> str:
    """Best-effort extraction of the topic slug from a source asset filename.

    Pattern emitted by this server: <date>-<topic>?<workflow_id>_comfyui<N>_<NNNNN>_.<ext>
    Strip the known suffixes and date prefix; whatever remains is the topic
    (or empty when none was baked in).
    """
    if not isinstance(fname, str) or not fname.strip():
        return ""
    import os as _os, re as _r
    base = _os.path.splitext(_os.path.basename(fname))[0]
    base = _r.sub(r"_\d+_$", "", base)            # drop _NNNNN_
    base = _r.sub(r"_comfyui\d+$", "", base)     # drop _comfyui<N>
    for wid in sorted(_KNOWN_WORKFLOW_IDS, key=len, reverse=True):
        if base.endswith("_" + wid):
            base = base[: -len(wid) - 1]
            break
    base = _r.sub(r"^\d{4}-\d{2}-\d{2}-", "", base)  # drop leading date
    return _slugify_topic(base)


def _topic_from_image_ref(value) -> str:
    """Extract a topic slug from an image / image_last / audio reference.

    Works whether the value has been resolved to a URL (?filename=...) or is
    still a bare filename / asset_id-converted URL. asset_id strings produce
    nothing here (they are UUIDs); resolution is expected to have happened
    before this point.
    """
    if not isinstance(value, str) or not value.strip():
        return ""
    import re as _r
    from urllib.parse import unquote as _unq
    m = _r.search(r"[?&]filename=([^&]+)", value)
    fname = _unq(m.group(1)) if m else value
    return _topic_from_filename(fname)


class WorkflowManager:
    def __init__(self, workflows_dir: Path):
        self.workflows_dir = Path(workflows_dir).resolve()
        self._tool_names: set[str] = set()
        self._workflow_cache: Dict[str, Dict[str, Any]] = {}
        self._workflow_mtime: Dict[str, float] = {}  # Track file modification times for cache invalidation
        self.tool_definitions = self._load_workflows()
        global _KNOWN_WORKFLOW_IDS
        _KNOWN_WORKFLOW_IDS = [d.workflow_id for d in self.tool_definitions]
    
    def _safe_workflow_path(self, workflow_id: str) -> Optional[Path]:
        """Resolve workflow ID to file path with path traversal protection"""
        # Normalize workflow_id (remove any path separators and dangerous characters)
        safe_id = workflow_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        # Remove any remaining path-like characters
        safe_id = "".join(c for c in safe_id if c.isalnum() or c in ("_", "-"))
        if not safe_id:
            logger.warning(f"Invalid workflow_id after sanitization: {workflow_id}")
            return None
        
        workflow_path = (self.workflows_dir / f"{safe_id}.json").resolve()
        
        # Ensure the resolved path is within workflows_dir
        try:
            workflow_path.relative_to(self.workflows_dir.resolve())
        except ValueError:
            logger.warning(f"Path traversal attempt detected: {workflow_id}")
            return None
        
        return workflow_path if workflow_path.exists() else None
    
    def _load_workflow_metadata(self, workflow_path: Path) -> Dict[str, Any]:
        """Load sidecar metadata file if it exists"""
        metadata_path = workflow_path.with_suffix(".meta.json")
        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load metadata for {workflow_path.name}: {e}")
        return {}
    
    def get_workflow_catalog(self) -> list[Dict[str, Any]]:
        """Get catalog of all available workflows"""
        catalog = []
        if not self.workflows_dir.exists():
            return catalog
        
        for workflow_path in sorted(self.workflows_dir.glob("*.json")):
            # Skip metadata files
            if workflow_path.name.endswith(".meta.json"):
                continue
            
            workflow_id = workflow_path.stem
            try:
                with open(workflow_path, "r", encoding="utf-8") as f:
                    workflow = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Skipping {workflow_path.name}: {e}")
                continue
            
            # Load metadata
            metadata = self._load_workflow_metadata(workflow_path)
            
            # Extract parameters
            parameters = self._extract_parameters(workflow)
            available_inputs = {
                name: {
                    "type": param.annotation.__name__,
                    "required": param.required,
                    "description": param.description
                }
                for name, param in parameters.items()
            }
            
            # Get workflow defaults from metadata or infer from workflow_id
            workflow_defaults = metadata.get("defaults", {})
            if not workflow_defaults and workflow_id in ["generate_image", "generate_song", "generate_video"]:
                # Use namespace-based defaults
                namespace = self._determine_namespace(workflow_id)
                # This will be populated by defaults_manager when needed
            
            catalog.append({
                "id": workflow_id,
                "name": metadata.get("name", workflow_id.replace("_", " ").title()),
                "description": metadata.get("description", f"Execute the '{workflow_id}' workflow."),
                "available_inputs": available_inputs,
                "defaults": workflow_defaults,
                "updated_at": metadata.get("updated_at"),
                "hash": metadata.get("hash"),  # Could compute file hash if needed
            })
        
        return catalog
    
    def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Load workflow by ID with mtime-based cache invalidation.

        Checks file modification time on each call. If the file has been
        modified since last load, the cache entry is invalidated and the
        workflow is reloaded from disk.
        """
        workflow_path = self._safe_workflow_path(workflow_id)
        if not workflow_path:
            return None

        # Check if cached version is still fresh
        try:
            current_mtime = workflow_path.stat().st_mtime
        except OSError:
            current_mtime = None

        if workflow_id in self._workflow_cache:
            cached_mtime = self._workflow_mtime.get(workflow_id)
            if current_mtime is not None and cached_mtime == current_mtime:
                return copy.deepcopy(self._workflow_cache[workflow_id])
            else:
                logger.info("Workflow '%s' changed on disk (mtime %s -> %s), reloading", workflow_id, cached_mtime, current_mtime)

        try:
            with open(workflow_path, "r", encoding="utf-8") as f:
                workflow = json.load(f)
            self._workflow_cache[workflow_id] = workflow
            if current_mtime is not None:
                self._workflow_mtime[workflow_id] = current_mtime
            return copy.deepcopy(workflow)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load workflow {workflow_id}: {e}")
            return None
    
    def apply_workflow_overrides(self, workflow: Dict[str, Any], workflow_id: str, overrides: Dict[str, Any], defaults_manager: Optional["DefaultsManager"] = None) -> Dict[str, Any]:
        """Apply constrained overrides to workflow based on metadata.

        The returned workflow dict contains an ``__override_report__`` key
        with 'overrides_applied' and 'overrides_dropped' dicts.  Callers
        should pop this key before submitting the workflow to ComfyUI.
        """
        from managers.defaults_manager import DefaultsManager

        workflow_path = self._safe_workflow_path(workflow_id)
        if not workflow_path:
            raise ValueError(f"Workflow {workflow_id} not found")

        metadata = self._load_workflow_metadata(workflow_path)
        override_mappings = metadata.get("override_mappings", {})
        constraints = metadata.get("constraints", {})

        # If no metadata, try to infer from PARAM_ placeholders
        if not override_mappings:
            parameters = self._extract_parameters(workflow)
            for param_name, param in parameters.items():
                if param_name not in override_mappings:
                    override_mappings[param_name] = param.bindings

        # Determine namespace for defaults
        namespace = self._determine_namespace(workflow_id)

        # Track which overrides were applied vs dropped
        overrides_applied = {}
        overrides_dropped = {}

        # Extract parameters once for type coercion
        parameters = self._extract_parameters(workflow)

        # Apply overrides with constraints
        for param_name, value in overrides.items():
            if param_name not in override_mappings:
                logger.warning(f"Override '{param_name}' has no matching PARAM_ placeholder in {workflow_id}, skipping")
                overrides_dropped[param_name] = f"No matching PARAM_{param_name.upper()} placeholder in workflow"
                continue

            # Apply constraints if defined
            if param_name in constraints:
                constraint = constraints[param_name]
                if "enum" in constraint and value not in constraint["enum"]:
                    raise ValueError(f"Value '{value}' for '{param_name}' not in allowed enum: {constraint['enum']}")
                if "min" in constraint and value < constraint["min"]:
                    raise ValueError(f"Value '{value}' for '{param_name}' below minimum: {constraint['min']}")
                if "max" in constraint and value > constraint["max"]:
                    raise ValueError(f"Value '{value}' for '{param_name}' above maximum: {constraint['max']}")

            # Get parameter type from extracted parameters
            if param_name in parameters:
                param = parameters[param_name]
                coerced_value = self._coerce_value(value, param.annotation)
            else:
                coerced_value = value

            # Apply to all bindings
            for node_id, input_name in override_mappings[param_name]:
                if node_id in workflow and "inputs" in workflow[node_id]:
                    workflow[node_id]["inputs"][input_name] = coerced_value
            overrides_applied[param_name] = value

        # Apply defaults for parameters not in overrides
        for param_name, param in parameters.items():
            if param_name not in overrides and not param.required:
                if defaults_manager:
                    default_value = defaults_manager.get_default(namespace, param.name, None)
                    if default_value is not None:
                        for node_id, input_name in param.bindings:
                            if node_id in workflow and "inputs" in workflow[node_id]:
                                workflow[node_id]["inputs"][input_name] = default_value


        # Topic-based filename slug (optional; supplied via overrides["topic"])
        try:
            _topic_explicit2 = overrides.get("topic") or ""
            _fallback = overrides.get("prompt") or overrides.get("tags") or ""
            if not (_topic_explicit2 or _fallback):
                for _img_key in ("image", "image_last", "audio"):
                    _img = overrides.get(_img_key)
                    _carry = _topic_from_image_ref(_img) if _img else ""
                    if _carry:
                        _fallback = _carry
                        break
            _inject_topic_into_filename_prefix(workflow, _topic_explicit2, _fallback)
        except Exception as _topic_err:
            import logging as _lg; _lg.getLogger(__name__).warning(f"topic injection failed: {_topic_err}")

        # Substitute %date:...% patterns in filename_prefix fields
        import re as _re
        from datetime import date as _date
        _today = _date.today().strftime('%Y-%m-%d')
        for _node in workflow.values():
            if not isinstance(_node, dict):
                continue
            _inp = _node.get('inputs', {})
            if 'filename_prefix' in _inp and isinstance(_inp['filename_prefix'], str):
                _inp['filename_prefix'] = _re.sub(r'%date:[^%]+%', _today, _inp['filename_prefix'])

        # Replace any PARAM_* placeholders not covered by overrides/defaults
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            for input_name, val in list(node.get("inputs", {}).items()):
                if not isinstance(val, str) or not val.startswith("PARAM_"):
                    continue
                upper = val.upper()
                if "SEED" in upper or ("INT" in upper and "SEED" in upper):
                    node["inputs"][input_name] = random.randint(0, 2**31 - 1)
                elif upper.startswith("PARAM_INT_"):
                    node["inputs"][input_name] = 0
                elif upper.startswith("PARAM_FLOAT_"):
                    node["inputs"][input_name] = 1.0
                # PARAM_PROMPT, PARAM_IMAGE etc. left as-is — required, will error properly

        # Store the report on the workflow dict so callers can access it
        # (using a private key that won't conflict with node IDs which are numeric strings)
        workflow["__override_report__"] = {
            "overrides_applied": overrides_applied,
            "overrides_dropped": overrides_dropped,
        }

        return workflow

    def _refresh_definition_if_stale(self, definition: WorkflowToolDefinition) -> None:
        """Reload a tool definition's template from disk if the file has been modified."""
        workflow_path = self._safe_workflow_path(definition.workflow_id)
        if not workflow_path:
            return

        try:
            current_mtime = workflow_path.stat().st_mtime
        except OSError:
            return

        cached_mtime = self._workflow_mtime.get(definition.workflow_id)
        if cached_mtime is not None and cached_mtime == current_mtime:
            return  # File hasn't changed

        logger.info("Refreshing tool definition '%s' from disk (mtime changed)", definition.workflow_id)
        try:
            with open(workflow_path, "r", encoding="utf-8") as f:
                workflow = json.load(f)
            definition.template = workflow
            definition.parameters = self._extract_parameters(workflow)
            definition.output_preferences = self._guess_output_preferences(workflow)
            self._workflow_cache[definition.workflow_id] = workflow
            self._workflow_mtime[definition.workflow_id] = current_mtime
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to refresh workflow %s: %s", definition.workflow_id, e)

    def _load_workflows(self):
        definitions: list[WorkflowToolDefinition] = []
        if not self.workflows_dir.exists():
            logger.info("Workflow directory %s does not exist yet", self.workflows_dir)
            return definitions

        for workflow_path in sorted(self.workflows_dir.glob("*.json")):
            if workflow_path.name.endswith(".meta.json"):
                continue
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
                description=(self._load_workflow_metadata(workflow_path).get("description") or self._derive_description(workflow_path.stem)) + " Always pass 'topic' (1-2 word slug derived from the user's request — e.g. 'giraffe', 'forest_scene', 'product_photo') so the output filename is searchable later. Response includes a 'markdown_preview' string — paste it verbatim into your reply to display the result inline.",
                template=workflow,
                parameters=parameters,
                output_preferences=self._guess_output_preferences(workflow),
            )
            # Store initial mtime for cache invalidation
            try:
                self._workflow_mtime[workflow_path.stem] = workflow_path.stat().st_mtime
            except OSError:
                pass
            logger.info(
                "Prepared workflow tool '%s' from %s with params %s",
                tool_name,
                workflow_path.name,
                list(parameters.keys()),
            )
            definitions.append(definition)

        return definitions

    def render_workflow(self, definition: WorkflowToolDefinition, provided_params: Dict[str, Any], defaults_manager: Optional["DefaultsManager"] = None):
        from managers.defaults_manager import DefaultsManager

        # Check if the workflow file has changed on disk and refresh the template
        self._refresh_definition_if_stale(definition)

        workflow = copy.deepcopy(definition.template)
        
        # Determine namespace (image, audio, or video)
        namespace = self._determine_namespace(definition.workflow_id)
        
        for param in definition.parameters.values():
            if param.required and param.name not in provided_params:
                raise ValueError(f"Missing required parameter '{param.name}'")
            
            # Use provided value, default, or generate (for seed)
            raw_value = provided_params.get(param.name)
            if raw_value is None:
                if param.name == "seed" and param.annotation is int:
                    # Special handling for seed - generate random
                    raw_value = random.randint(0, 2**31 - 1)
                    logger.debug(f"Generated random seed: {raw_value}")
                elif defaults_manager:
                    # Use defaults manager to get value with proper precedence
                    raw_value = defaults_manager.get_default(namespace, param.name, None)
                    if raw_value is not None:
                        logger.debug(f"Using default value for {param.name}: {raw_value}")
                    else:
                        # Skip parameters without defaults
                        continue
                else:
                    # Fallback to old behavior if no defaults manager
                    continue
            
            coerced_value = self._coerce_value(raw_value, param.annotation)
            for node_id, input_name in param.bindings:
                workflow[node_id]["inputs"][input_name] = coerced_value
        

        # Topic-based filename slug. Priority:
        #   1. LLM-supplied topic (best — semantic intent)
        #   2. Slug derived from prompt / tags
        #   3. Slug carried over from a source image / image_last / audio reference
        try:
            _topic_explicit = provided_params.get("topic", "") or ""
            _fallback_text = provided_params.get("prompt") or provided_params.get("tags") or ""
            if not (_topic_explicit or _fallback_text):
                for _img_key in ("image", "image_last", "audio"):
                    _img = provided_params.get(_img_key)
                    _carry = _topic_from_image_ref(_img) if _img else ""
                    if _carry:
                        _fallback_text = _carry
                        break
            _inject_topic_into_filename_prefix(workflow, _topic_explicit, _fallback_text)
        except Exception as _topic_err:
            logger.warning(f"render_workflow topic injection failed: {_topic_err}")

        # Substitute %date:...% patterns in filename_prefix fields
        import re as _re
        from datetime import date as _date
        _today = _date.today().strftime('%Y-%m-%d')
        for _node in workflow.values():
            if not isinstance(_node, dict):
                continue
            _inp = _node.get('inputs', {})
            if 'filename_prefix' in _inp and isinstance(_inp['filename_prefix'], str):
                _inp['filename_prefix'] = _re.sub(r'%date:[^%]+%', _today, _inp['filename_prefix'])

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
                    # Only 'prompt' should be required for generate_video
                    optional_params = {
                        "seed", "width", "height", "model", "steps", "cfg",
                        "sampler_name", "scheduler", "denoise", "negative_prompt",
                        "seconds", "lyrics_strength",  # Audio-specific optional params
                        "duration", "fps"  # Video-specific optional params
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

    def _determine_namespace(self, workflow_id: str) -> str:
        """Determine namespace based on workflow ID."""
        wid = workflow_id.lower()
        audio_patterns = ("_t2a", "_i2a", "song", "audio")
        video_patterns = ("_t2v", "_i2v", "_d2v", "_fl2v", "_vid", "video")
        if any(p in wid for p in audio_patterns):
            return "audio"
        elif any(p in wid for p in video_patterns):
            return "video"
        else:
            return "image"
    
    def _guess_output_preferences(self, workflow: Dict[str, Any]):
        for node in workflow.values():
            class_type = str(node.get("class_type", "")).lower()
            if "audio" in class_type:
                return AUDIO_OUTPUT_KEYS
            if "video" in class_type or "savevideo" in class_type or "videocombine" in class_type:
                return VIDEO_OUTPUT_KEYS
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
