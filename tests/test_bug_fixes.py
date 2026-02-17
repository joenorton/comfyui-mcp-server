"""Tests for bug fixes: cache invalidation, model validation, error diagnostics,
timeout handling, and override mismatch reporting.

These tests reproduce the five bugs that were fixed and verify the correct
behaviour without requiring a running ComfyUI instance.
"""

import copy
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from comfyui_client import ComfyUIClient
from managers.workflow_manager import WorkflowManager, AUDIO_OUTPUT_KEYS

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Bug 1 – Workflow cache staleness (mtime-based invalidation)
# ---------------------------------------------------------------------------
class TestWorkflowCacheMtime:
    """Editing a workflow JSON on disk should be picked up without restart."""

    def test_load_workflow_detects_file_change(self, tmp_path):
        """load_workflow returns fresh data after a file is modified on disk."""
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()

        wf_file = wf_dir / "test_wf.json"
        original = {"1": {"inputs": {"prompt": "PARAM_PROMPT"}, "class_type": "A"}}
        wf_file.write_text(json.dumps(original))

        mgr = WorkflowManager(wf_dir)

        # First load — should cache
        loaded1 = mgr.load_workflow("test_wf")
        assert loaded1 is not None
        assert loaded1["1"]["class_type"] == "A"

        # Modify on disk (ensure mtime actually changes)
        time.sleep(0.05)
        modified = {"1": {"inputs": {"prompt": "PARAM_PROMPT"}, "class_type": "B"}}
        wf_file.write_text(json.dumps(modified))

        # Second load — should detect mtime change and reload
        loaded2 = mgr.load_workflow("test_wf")
        assert loaded2["1"]["class_type"] == "B"

    def test_render_workflow_refreshes_stale_definition(self, tmp_path):
        """render_workflow should pick up file changes for dedicated tools."""
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()

        wf_file = wf_dir / "my_tool.json"
        original = {"1": {"inputs": {"prompt": "PARAM_PROMPT"}, "class_type": "X"}}
        wf_file.write_text(json.dumps(original))

        mgr = WorkflowManager(wf_dir)
        assert len(mgr.tool_definitions) == 1
        defn = mgr.tool_definitions[0]
        assert defn.template["1"]["class_type"] == "X"

        # Modify on disk
        time.sleep(0.05)
        modified = {"1": {"inputs": {"prompt": "PARAM_PROMPT"}, "class_type": "Y"}}
        wf_file.write_text(json.dumps(modified))

        # render_workflow should refresh the definition first
        workflow = mgr.render_workflow(defn, {"prompt": "hello"})
        assert workflow["1"]["class_type"] == "Y"

    def test_cache_hit_when_file_unchanged(self, tmp_path):
        """When the file hasn't changed, cache should be used (no extra read)."""
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()

        wf_file = wf_dir / "cached.json"
        wf_file.write_text(json.dumps({"1": {"inputs": {}, "class_type": "C"}}))

        mgr = WorkflowManager(wf_dir)
        loaded1 = mgr.load_workflow("cached")
        loaded2 = mgr.load_workflow("cached")

        # Both should succeed and return deep copies
        assert loaded1 == loaded2
        assert loaded1 is not loaded2  # deep copy


# ---------------------------------------------------------------------------
# Bug 2 – Model validation fires on workflows without a PARAM_MODEL
# ---------------------------------------------------------------------------
class TestModelValidationSkip:
    """Workflows without a 'model' PARAM_ placeholder should NOT trigger
    checkpoint model validation, regardless of namespace or workflow name."""

    def test_audio_workflow_has_no_model_param(self):
        """The custom_audio_workflow fixture has no PARAM_MODEL — verify detection."""
        wf_path = FIXTURES / "custom_audio_workflow.json"
        assert wf_path.exists(), f"Fixture missing: {wf_path}"

        # Copy to a temp workflow dir with a name that does NOT match 'generate_song'
        with tempfile.TemporaryDirectory() as tmp:
            wf_dir = Path(tmp) / "workflows"
            wf_dir.mkdir()
            dest = wf_dir / "my_custom_sfx.json"
            dest.write_text(wf_path.read_text())

            mgr = WorkflowManager(wf_dir)
            assert len(mgr.tool_definitions) == 1
            defn = mgr.tool_definitions[0]

            # Key assertion: no 'model' in the extracted parameters
            assert "model" not in defn.parameters, (
                f"Expected no 'model' param but got: {list(defn.parameters.keys())}"
            )

    def test_output_preferences_detected_as_audio(self):
        """A workflow with SaveAudioMP3 output should get AUDIO_OUTPUT_KEYS."""
        wf_path = FIXTURES / "custom_audio_workflow.json"
        with tempfile.TemporaryDirectory() as tmp:
            wf_dir = Path(tmp) / "workflows"
            wf_dir.mkdir()
            (wf_dir / "custom_sfx.json").write_text(wf_path.read_text())

            mgr = WorkflowManager(wf_dir)
            defn = mgr.tool_definitions[0]
            assert defn.output_preferences == AUDIO_OUTPUT_KEYS


# ---------------------------------------------------------------------------
# Bug 3 – Error diagnostics from ComfyUI history
# ---------------------------------------------------------------------------
class TestErrorDiagnostics:
    """_extract_node_errors should surface useful info from ComfyUI history."""

    def test_extract_structured_execution_error(self):
        """Structured execution_error with node details."""
        prompt_data = {
            "status": {
                "status_str": "error",
                "completed": False,
                "messages": [
                    ["execution_started", {"prompt_id": "abc"}],
                    ["execution_error", {
                        "node_id": "3",
                        "node_type": "KSampler",
                        "exception_type": "RuntimeError",
                        "exception_message": "mat1 and mat2 shapes cannot be multiplied (512x7680 and 15360x6144)",
                        "traceback": [
                            "Traceback (most recent call last):\n",
                            "  File \"execution.py\", line 300, in execute\n",
                            "RuntimeError: mat1 and mat2 shapes cannot be multiplied (512x7680 and 15360x6144)\n"
                        ]
                    }]
                ]
            }
        }
        result = ComfyUIClient._extract_node_errors(prompt_data)
        assert "Node 3 (KSampler)" in result
        assert "RuntimeError" in result
        assert "mat1 and mat2" in result

    def test_extract_top_level_error(self):
        """Fallback to top-level 'error' key."""
        prompt_data = {"error": {"message": "something broke"}}
        result = ComfyUIClient._extract_node_errors(prompt_data)
        assert "something broke" in result

    def test_extract_no_info_fallback(self):
        """When there's no error info at all, should still produce output."""
        prompt_data = {"status": {}}
        result = ComfyUIClient._extract_node_errors(prompt_data)
        assert "No detailed error info" in result

    def test_has_status_message_list_format(self):
        """_has_status_message works with [type, data] pair format."""
        msgs = [["execution_started", {}], ["execution_error", {"node_id": "1"}]]
        assert ComfyUIClient._has_status_message(msgs, "execution_error") is True
        assert ComfyUIClient._has_status_message(msgs, "execution_success") is False

    def test_has_status_message_empty(self):
        assert ComfyUIClient._has_status_message([], "anything") is False
        assert ComfyUIClient._has_status_message(None, "anything") is False


# ---------------------------------------------------------------------------
# Bug 4 – Timeout returns job handle instead of error
# ---------------------------------------------------------------------------
class TestTimeoutJobHandle:
    """When _wait_for_prompt times out, run_custom_workflow should return a
    job handle dict instead of raising an exception."""

    def test_wait_for_prompt_returns_none_on_timeout(self):
        """_wait_for_prompt should return None after max_attempts exhausted."""
        client = ComfyUIClient("http://localhost:8188")

        # Mock requests.get to always return "not ready yet" (empty history)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch("comfyui_client.requests.get", return_value=mock_response):
            with patch("comfyui_client.time.sleep"):  # Skip actual sleeps
                result = client._wait_for_prompt("fake-id", max_attempts=2)

        assert result is None

    def test_run_custom_workflow_returns_running_on_timeout(self):
        """run_custom_workflow should return status='running' on timeout."""
        client = ComfyUIClient("http://localhost:8188")

        with patch.object(client, "_queue_workflow", return_value="test-prompt-id"):
            with patch.object(client, "_wait_for_prompt", return_value=None):
                result = client.run_custom_workflow({"test": "workflow"}, max_attempts=1)

        assert result["status"] == "running"
        assert result["prompt_id"] == "test-prompt-id"
        assert "get_job" in result["message"]

    def test_helpers_pass_through_running_status(self):
        """register_and_build_response should pass through 'running' results."""
        from tools.helpers import register_and_build_response

        running_result = {
            "status": "running",
            "prompt_id": "test-id",
            "message": "Still running"
        }
        response = register_and_build_response(
            running_result, "test_workflow", MagicMock()
        )
        assert response["status"] == "running"
        assert response["prompt_id"] == "test-id"


# ---------------------------------------------------------------------------
# Bug 5 – Override mismatch reporting
# ---------------------------------------------------------------------------
class TestOverrideMismatchReporting:
    """When run_workflow passes overrides that don't match any PARAM_
    placeholder, the response should report them as dropped."""

    def test_unmatched_overrides_are_reported(self, tmp_path):
        """Overrides for non-existent parameters should appear in dropped."""
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()

        wf = {"1": {"inputs": {"prompt": "PARAM_PROMPT"}, "class_type": "A"}}
        (wf_dir / "test.json").write_text(json.dumps(wf))

        mgr = WorkflowManager(wf_dir)
        workflow = mgr.load_workflow("test")

        result = mgr.apply_workflow_overrides(
            workflow, "test",
            overrides={"prompt": "hello", "nonexistent_param": 42}
        )

        report = result.get("__override_report__")
        assert report is not None
        assert "prompt" in report["overrides_applied"]
        assert "nonexistent_param" in report["overrides_dropped"]
        assert "PARAM_NONEXISTENT_PARAM" in report["overrides_dropped"]["nonexistent_param"]

    def test_all_matched_overrides_no_drop_report(self, tmp_path):
        """When all overrides match, overrides_dropped should be empty."""
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()

        wf = {"1": {"inputs": {"prompt": "PARAM_PROMPT", "seed": "PARAM_INT_SEED"}, "class_type": "A"}}
        (wf_dir / "test.json").write_text(json.dumps(wf))

        mgr = WorkflowManager(wf_dir)
        workflow = mgr.load_workflow("test")

        result = mgr.apply_workflow_overrides(
            workflow, "test",
            overrides={"prompt": "hello", "seed": 123}
        )

        report = result.get("__override_report__")
        assert report is not None
        assert len(report["overrides_dropped"]) == 0
        assert "prompt" in report["overrides_applied"]
        assert "seed" in report["overrides_applied"]
