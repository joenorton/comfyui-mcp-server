import requests
import json
import time
import logging
from typing import Any, Dict, Optional, Sequence
from urllib.parse import quote

from asset_processor import get_image_metadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ComfyUIClient")

class ComfyUIClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.available_models = self._get_available_models()
    
    def refresh_models(self):
        """Re-fetch available models and update available_models list."""
        self.available_models = self._get_available_models()

    def _get_available_models(self):
        """Fetch list of available checkpoint models from ComfyUI"""
        try:
            response = requests.get(f"{self.base_url}/object_info/CheckpointLoaderSimple", timeout=10)
            if response.status_code != 200:
                logger.warning("Failed to fetch model list; using default handling")
                return []
            data = response.json()
            # Safe dictionary access with proper error handling
            try:
                checkpoint_info = data.get("CheckpointLoaderSimple", {})
                if not isinstance(checkpoint_info, dict):
                    logger.warning("Unexpected CheckpointLoaderSimple structure")
                    return []
                input_info = checkpoint_info.get("input", {})
                if not isinstance(input_info, dict):
                    logger.warning("Unexpected input structure")
                    return []
                required_info = input_info.get("required", {})
                if not isinstance(required_info, dict):
                    logger.warning("Unexpected required structure")
                    return []
                ckpt_name_info = required_info.get("ckpt_name", [])
                if not isinstance(ckpt_name_info, list) or len(ckpt_name_info) == 0:
                    logger.warning("No checkpoint models found in API response")
                    return []
                models = ckpt_name_info[0] if isinstance(ckpt_name_info[0], list) else ckpt_name_info
                logger.info(f"Available models: {models}")
                return models
            except (KeyError, IndexError, TypeError) as e:
                logger.warning(f"Unexpected API response structure: {e}")
                return []
        except requests.RequestException as e:
            logger.warning(f"Error fetching models: {e}")
            return []

    def run_custom_workflow(self, workflow: Dict[str, Any], preferred_output_keys: Sequence[str] | None = None, max_attempts: int = 30):
        if preferred_output_keys is None:
            preferred_output_keys = ("images", "image", "gifs", "gif", "audio", "audios", "files")

        prompt_id = self._queue_workflow(workflow)
        outputs = self._wait_for_prompt(prompt_id, max_attempts=max_attempts)

        # If outputs is None, the workflow is still running (timeout).
        # Return a job handle instead of raising an error.
        if outputs is None:
            return {
                "status": "running",
                "prompt_id": prompt_id,
                "message": (
                    f"Workflow still running after {max_attempts}s. "
                    f"Use get_job(prompt_id='{prompt_id}') to poll for completion."
                ),
            }

        # Extract asset info (filename, subfolder, type) - stable identity
        asset_info = self._extract_first_asset_info(outputs, preferred_output_keys)
        asset_url = asset_info["asset_url"]
        
        # Extract asset metadata (pass workflow to extract dimensions from it)
        asset_metadata = self._get_asset_metadata(asset_url, outputs, preferred_output_keys, workflow)
        
        # Get full history snapshot for this prompt
        try:
            history = self.get_history(prompt_id)
            comfy_history = history.get(prompt_id, {}) if history else {}
        except Exception as e:
            logger.warning(f"Failed to fetch history snapshot for {prompt_id}: {e}")
            comfy_history = None
        
        return {
            "asset_url": asset_url,
            "filename": asset_info["filename"],
            "subfolder": asset_info["subfolder"],
            "folder_type": asset_info["type"],
            "prompt_id": prompt_id,
            "raw_outputs": outputs,
            "asset_metadata": asset_metadata,
            "comfy_history": comfy_history,
            "submitted_workflow": workflow
        }
    
    def _get_asset_metadata(self, asset_url: str, outputs: Dict[str, Any], preferred_output_keys: Sequence[str], workflow: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Extract metadata about the generated asset"""
        metadata = {
            "mime_type": None,
            "width": None,
            "height": None,
            "bytes_size": None
        }
        
        # Try to extract from outputs first
        for node_id, node_output in outputs.items():
            if not isinstance(node_output, dict):
                continue
            for key in preferred_output_keys:
                assets = node_output.get(key)
                if assets and isinstance(assets, list) and len(assets) > 0:
                    asset = assets[0]
                    if isinstance(asset, dict):
                        # Infer mime type from filename extension
                        filename = asset.get("filename", "")
                        if filename.endswith((".png", ".PNG")):
                            metadata["mime_type"] = "image/png"
                        elif filename.endswith((".jpg", ".jpeg", ".JPG", ".JPEG")):
                            metadata["mime_type"] = "image/jpeg"
                        elif filename.endswith((".webp", ".WEBP")):
                            metadata["mime_type"] = "image/webp"
                        elif filename.endswith((".mp3", ".MP3")):
                            metadata["mime_type"] = "audio/mpeg"
                        elif filename.endswith((".mp4", ".MP4")):
                            metadata["mime_type"] = "video/mp4"
                        elif filename.endswith((".gif", ".GIF")):
                            metadata["mime_type"] = "image/gif"
                        break
        
        # Extract dimensions from workflow (EmptyLatentImage node) - much more efficient than analyzing image
        if workflow and (metadata["width"] is None or metadata["height"] is None):
            for node_id, node_data in workflow.items():
                if not isinstance(node_data, dict):
                    continue
                if node_data.get("class_type") == "EmptyLatentImage":
                    inputs = node_data.get("inputs", {})
                    if "width" in inputs and metadata["width"] is None:
                        metadata["width"] = inputs["width"]
                    if "height" in inputs and metadata["height"] is None:
                        metadata["height"] = inputs["height"]
                    if metadata["width"] and metadata["height"]:
                        break
        
        # Try to fetch headers to get size (non-blocking, best effort)
        try:
            response = requests.head(asset_url, timeout=5)
            if response.status_code == 200:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    metadata["bytes_size"] = int(content_length)
                content_type = response.headers.get("Content-Type")
                if content_type and not metadata["mime_type"]:
                    metadata["mime_type"] = content_type.split(";")[0].strip()
        except Exception as e:
            logger.debug(f"Could not fetch asset metadata: {e}")
        
        # Fallback: Extract image dimensions by analyzing image bytes (only if not found in workflow)
        # This should rarely be needed now, but kept as a fallback
        if metadata["mime_type"] and metadata["mime_type"].startswith("image/") and (metadata["width"] is None or metadata["height"] is None):
            try:
                # Fetch image bytes to extract dimensions
                img_response = requests.get(asset_url, timeout=10)
                if img_response.status_code == 200:
                    image_bytes = img_response.content
                    # Update bytes_size if we got it from the full response
                    if not metadata["bytes_size"]:
                        metadata["bytes_size"] = len(image_bytes)
                    # Extract dimensions
                    img_metadata = get_image_metadata(image_bytes)
                    if img_metadata.get("width") and img_metadata.get("height"):
                        metadata["width"] = img_metadata["width"]
                        metadata["height"] = img_metadata["height"]
            except Exception as e:
                logger.debug(f"Could not extract image dimensions: {e}")
        
        return metadata

    def _queue_workflow(self, workflow: Dict[str, Any]):
        logger.info("Submitting workflow to ComfyUI...")
        response = requests.post(f"{self.base_url}/prompt", json={"prompt": workflow}, timeout=30)
        if response.status_code != 200:
            raise Exception(f"Failed to queue workflow: {response.status_code} - {response.text}")
        try:
            response_data = response.json()
            prompt_id = response_data.get("prompt_id")
            if not prompt_id:
                raise Exception("Response missing prompt_id")
        except (KeyError, ValueError) as e:
            raise Exception(f"Invalid response format from ComfyUI: {e}")
        logger.info(f"Queued workflow with prompt_id: {prompt_id}")
        return prompt_id

    @staticmethod
    def _has_status_message(messages, target: str) -> bool:
        """Check if a status messages list contains a target message type.

        ComfyUI status messages come as either a list of [type, data] pairs
        or a dict with 'messages' key.
        """
        if not messages:
            return False
        for msg in messages:
            if isinstance(msg, list) and len(msg) > 0 and msg[0] == target:
                return True
            if isinstance(msg, str) and msg == target:
                return True
        return False

    @staticmethod
    def _extract_node_errors(prompt_data: dict) -> str:
        """Extract human-readable error details from ComfyUI history data.

        Looks in prompt_data['status']['messages'] for execution_error entries
        which contain node_id, node_type, exception_message, and
        exception_type. Falls back to other status fields when the structured
        error is not available.
        """
        parts: list[str] = []

        # Try structured status dict first (ComfyUI v2 history format)
        status = prompt_data.get("status", {})
        if isinstance(status, dict):
            messages = status.get("messages", [])
            for msg in messages:
                if isinstance(msg, list) and len(msg) >= 2 and msg[0] == "execution_error":
                    data = msg[1] if isinstance(msg[1], dict) else {}
                    node_type = data.get("node_type", "unknown")
                    node_id = data.get("node_id", "?")
                    exc_type = data.get("exception_type", "Error")
                    exc_msg = data.get("exception_message", "unknown error")
                    parts.append(f"Node {node_id} ({node_type}): [{exc_type}] {exc_msg}")
                    # Include traceback summary if available
                    traceback_lines = data.get("traceback", [])
                    if traceback_lines and isinstance(traceback_lines, list):
                        # Just the last meaningful line
                        for line in reversed(traceback_lines):
                            stripped = line.strip() if isinstance(line, str) else ""
                            if stripped and not stripped.startswith("Traceback") and not stripped.startswith("File"):
                                parts.append(f"  -> {stripped}")
                                break

        # Legacy list-of-lists format
        if not parts and isinstance(status, list):
            for entry in status:
                if isinstance(entry, list) and len(entry) >= 2 and entry[0] == "execution_error":
                    parts.append(f"Execution error: {entry[1]}")

        # Check for top-level 'error' key
        if not parts and "error" in prompt_data:
            parts.append(f"Error: {json.dumps(prompt_data['error'])}")

        if not parts:
            # Last resort: dump status for debugging
            status_summary = json.dumps(status, indent=2) if status else "no status info"
            parts.append(f"No detailed error info. Status: {status_summary}")

        return "; ".join(parts)

    def _wait_for_prompt(self, prompt_id: str, max_attempts: int = 30):
        for attempt in range(max_attempts):
            try:
                # Try both the specific prompt_id endpoint and the full history endpoint
                response = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=10)
                # If that doesn't work, we can also try: f"{self.base_url}/history"
                if response.status_code != 200:
                    logger.warning("History endpoint returned %s on attempt %s", response.status_code, attempt + 1)
                    time.sleep(1)
                    continue
                
                history = response.json()
                if not isinstance(history, dict):
                    logger.warning("Invalid history response format on attempt %s", attempt + 1)
                    time.sleep(1)
                    continue
                
                if prompt_id not in history:
                    # Workflow might still be running, wait and retry
                    if attempt < max_attempts - 1:
                        time.sleep(1)
                        continue
                    else:
                        # Last attempt - check if there's any history at all
                        logger.warning("Prompt ID not found in history. Available IDs: %s", list(history.keys())[:10])
                        time.sleep(1)
                        continue
                
                prompt_data = history[prompt_id]
                if not isinstance(prompt_data, dict):
                    logger.warning("Prompt data is not a dict on attempt %s", attempt + 1)
                    time.sleep(1)
                    continue
                
                # Check for workflow errors (top-level and status-embedded)
                if "error" in prompt_data:
                    error_info = prompt_data["error"]
                    raise Exception(f"Workflow failed with error: {json.dumps(error_info, indent=2)}")

                # Check if workflow status indicates failure
                status = prompt_data.get("status", {})
                if isinstance(status, dict):
                    if status.get("completed") == False:
                        error_msg = status.get("messages", ["Workflow failed"])
                        raise Exception(f"Workflow failed: {error_msg}")
                    # Check status_str for execution_error
                    if status.get("status_str") == "error":
                        node_errors = self._extract_node_errors(prompt_data)
                        raise Exception(f"Workflow execution error: {node_errors}")
                
                # Get outputs
                if "outputs" not in prompt_data:
                    # Check status to see if workflow completed
                    status = prompt_data.get("status", {})
                    status_str = status.get("status_str", "") if isinstance(status, dict) else ""
                    messages = status.get("messages", []) if isinstance(status, dict) else status if isinstance(status, list) else []

                    # Check for execution_error in status
                    if status_str == "error" or self._has_status_message(messages, "execution_error"):
                        node_errors = self._extract_node_errors(prompt_data)
                        raise Exception(f"Workflow execution failed: {node_errors}")

                    if self._has_status_message(messages, "execution_success"):
                        logger.info("Workflow execution succeeded, waiting for outputs to be available...")
                        time.sleep(3)
                        try:
                            full_history_response = requests.get(f"{self.base_url}/history", timeout=10)
                            if full_history_response.status_code == 200:
                                full_history = full_history_response.json()
                                if prompt_id in full_history:
                                    full_prompt_data = full_history[prompt_id]
                                    if "outputs" in full_prompt_data and full_prompt_data["outputs"]:
                                        logger.info("Found outputs in full history endpoint")
                                        return full_prompt_data["outputs"]
                        except Exception as e:
                            logger.debug("Could not fetch full history: %s", e)
                        continue

                    logger.warning("Prompt data missing outputs on attempt %s. Full data: %s", attempt + 1, json.dumps(prompt_data, indent=2))
                    time.sleep(1)
                    continue

                outputs = prompt_data["outputs"]
                if not outputs or not isinstance(outputs, dict):
                    status = prompt_data.get("status", {})
                    status_str = status.get("status_str", "") if isinstance(status, dict) else ""
                    messages = status.get("messages", []) if isinstance(status, dict) else status if isinstance(status, list) else []

                    # Check for errors first
                    if status_str == "error" or self._has_status_message(messages, "execution_error"):
                        node_errors = self._extract_node_errors(prompt_data)
                        raise Exception(f"Workflow execution failed: {node_errors}")

                    if self._has_status_message(messages, "execution_success"):
                        logger.warning("Workflow succeeded but outputs empty. Waiting longer...")
                        time.sleep(2)
                        continue

                    # Build diagnostic message from whatever status info we have
                    node_errors = self._extract_node_errors(prompt_data)
                    raise Exception(
                        f"Workflow completed but produced no outputs. "
                        f"Diagnostics: {node_errors}"
                    )
                
                logger.info("Workflow completed. Output nodes: %s", list(outputs.keys()))
                logger.debug("Full workflow outputs: %s", json.dumps(outputs, indent=2))
                logger.debug("Full prompt data: %s", json.dumps(prompt_data, indent=2))
                return outputs
            except requests.RequestException as e:
                logger.warning("Request error on attempt %s: %s", attempt + 1, e)
                time.sleep(1)
                continue
            except (ValueError, KeyError) as e:
                logger.warning("JSON parsing error on attempt %s: %s", attempt + 1, e)
                time.sleep(1)
                continue
        
        # Instead of raising, return a sentinel so callers can return a job handle
        logger.warning("Workflow %s still running after %s seconds", prompt_id, max_attempts)
        return None  # Signals timeout — caller should return a job handle

    def _extract_first_asset_url(self, outputs: Dict[str, Any], preferred_output_keys: Sequence[str]):
        # Log available outputs for debugging
        logger.debug("Available output keys in workflow: %s", list(outputs.keys()))
        for node_id, node_output in outputs.items():
            if not isinstance(node_output, dict):
                logger.debug("Node %s output is not a dict: %s", node_id, type(node_output))
                continue
            logger.debug("Node %s has keys: %s", node_id, list(node_output.keys()))
            for key in preferred_output_keys:
                assets = node_output.get(key)
                if assets and isinstance(assets, list) and len(assets) > 0:
                    asset = assets[0]
                    if not isinstance(asset, dict):
                        logger.debug("Asset in node %s, key %s is not a dict", node_id, key)
                        continue
                    filename = asset.get("filename")
                    if not filename:
                        logger.debug("Asset in node %s, key %s missing filename", node_id, key)
                        continue
                    subfolder = asset.get("subfolder", "")
                    output_type = asset.get("type", "output")
                    logger.info("Found asset: filename=%s, subfolder=%s, type=%s", filename, subfolder, output_type)
                    return f"{self.base_url}/view?filename={filename}&subfolder={subfolder}&type={output_type}"
        
        # Enhanced error message with actual output structure
        logger.error("No outputs matched preferred keys: %s", preferred_output_keys)
        logger.error("Actual outputs structure: %s", json.dumps(outputs, indent=2))
        raise Exception(
            f"No outputs matched preferred keys: {preferred_output_keys}. "
            f"Available outputs: {json.dumps({k: list(v.keys()) if isinstance(v, dict) else type(v).__name__ for k, v in outputs.items()}, indent=2)}"
        )
    
    def _extract_first_asset_info(self, outputs: Dict[str, Any], preferred_output_keys: Sequence[str]) -> Dict[str, Any]:
        """Extract first asset info (filename, subfolder, type) from outputs.
        
        Returns dict with 'filename', 'subfolder', 'type', and 'asset_url'.
        """
        logger.debug("Available output keys in workflow: %s", list(outputs.keys()))
        for node_id, node_output in outputs.items():
            if not isinstance(node_output, dict):
                continue
            for key in preferred_output_keys:
                assets = node_output.get(key)
                if assets and isinstance(assets, list) and len(assets) > 0:
                    asset = assets[0]
                    if not isinstance(asset, dict):
                        continue
                    filename = asset.get("filename")
                    if not filename:
                        continue
                    subfolder = asset.get("subfolder", "")
                    output_type = asset.get("type", "output")
                    
                    # URL encode for special characters
                    base_url = self.base_url.rstrip('/')
                    encoded_filename = quote(filename, safe='')
                    encoded_subfolder = quote(subfolder, safe='') if subfolder else ''
                    
                    if encoded_subfolder:
                        asset_url = f"{base_url}/view?filename={encoded_filename}&subfolder={encoded_subfolder}&type={output_type}"
                    else:
                        asset_url = f"{base_url}/view?filename={encoded_filename}&type={output_type}"
                    
                    return {
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": output_type,
                        "asset_url": asset_url
                    }
        
        raise Exception(
            f"No outputs matched preferred keys: {preferred_output_keys}. "
            f"Available outputs: {json.dumps({k: list(v.keys()) if isinstance(v, dict) else type(v).__name__ for k, v in outputs.items()}, indent=2)}"
        )
    
    def get_queue(self) -> Dict[str, Any]:
        """Get current queue status from ComfyUI.
        
        Returns the full /queue endpoint response.
        """
        try:
            response = requests.get(f"{self.base_url}/queue", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get queue status: {e}")
            raise Exception(f"Failed to get queue status: {e}")
    
    def get_history(self, prompt_id: Optional[str] = None) -> Dict[str, Any]:
        """Get history from ComfyUI.
        
        Args:
            prompt_id: Optional specific prompt ID. If None, returns full history.
        
        Returns:
            History dict. If prompt_id provided, returns {prompt_id: {...}} or {} if not found.
        """
        try:
            if prompt_id:
                url = f"{self.base_url}/history/{prompt_id}"
            else:
                url = f"{self.base_url}/history"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get history: {e}")
            raise Exception(f"Failed to get history: {e}")
    
    def cancel_prompt(self, prompt_id: str) -> Dict[str, Any]:
        """Cancel a queued or running prompt.
        
        Args:
            prompt_id: The prompt ID to cancel.
        
        Returns:
            Response from ComfyUI cancel endpoint.
        """
        try:
            response = requests.post(
                f"{self.base_url}/queue",
                json={"delete": [prompt_id]},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to cancel prompt {prompt_id}: {e}")
            raise Exception(f"Failed to cancel prompt: {e}")