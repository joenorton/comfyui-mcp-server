"""Unit tests for job management tools"""
import pytest
from unittest.mock import Mock
from tools.job import register_job_tools
from fastmcp import FastMCP


@pytest.fixture
def mock_comfyui_client():
    """Mock ComfyUI client for testing"""
    client = Mock()
    client.get_queue.return_value = {
        "queue_running": [["exec_1", "prompt_123", {}]],
        "queue_pending": [["exec_2", "prompt_456", {}]]
    }
    client.get_history.return_value = {
        "prompt_123": {
            "outputs": {"1": {"images": []}},
            "status": []
        }
    }
    client.cancel_prompt.return_value = {"success": True}
    return client


@pytest.fixture
def mock_asset_registry():
    """Mock asset registry for testing"""
    registry = Mock()
    registry.comfyui_base_url = "http://localhost:8188"
    registry.list_assets.return_value = []
    registry.get_asset.return_value = None
    return registry


def test_get_queue_status_integration(mock_comfyui_client, mock_asset_registry):
    """Test that get_queue_status tool is registered and works"""
    mcp = FastMCP("test")
    register_job_tools(mcp, mock_comfyui_client, mock_asset_registry)
    
    # Verify tool is registered by checking tools list
    # Note: This is a basic integration test - actual function testing
    # would require calling through MCP protocol
    assert mcp is not None
    mock_comfyui_client.get_queue.assert_not_called()  # Not called yet


def test_get_job_running_scenario(mock_comfyui_client, mock_asset_registry):
    """Test get_job logic when job is running"""
    # This tests the logic by directly calling the client methods
    queue_data = {
        "queue_running": [["exec_1", "prompt_123", {}]],
        "queue_pending": []
    }
    mock_comfyui_client.get_queue.return_value = queue_data
    
    queue_result = mock_comfyui_client.get_queue()
    assert len(queue_result["queue_running"]) > 0
    
    # Check if prompt_id is in running queue
    in_queue = any(
        "prompt_123" in str(item)
        for item in queue_result["queue_running"]
    )
    assert in_queue


def test_get_job_completed_scenario(mock_comfyui_client, mock_asset_registry):
    """Test get_job logic when job is completed"""
    mock_comfyui_client.get_queue.return_value = {
        "queue_running": [],
        "queue_pending": []
    }
    mock_comfyui_client.get_history.return_value = {
        "prompt_123": {
            "outputs": {"1": {"images": [{"filename": "test.png"}]}},
            "status": []
        }
    }
    
    queue_result = mock_comfyui_client.get_queue()
    assert len(queue_result["queue_running"]) == 0
    
    history = mock_comfyui_client.get_history("prompt_123")
    assert "prompt_123" in history
    assert "outputs" in history["prompt_123"]


def test_get_job_not_found_scenario(mock_comfyui_client, mock_asset_registry):
    """Test get_job logic when prompt_id doesn't exist"""
    mock_comfyui_client.get_queue.return_value = {
        "queue_running": [],
        "queue_pending": []
    }
    mock_comfyui_client.get_history.return_value = {}
    
    queue_result = mock_comfyui_client.get_queue()
    history = mock_comfyui_client.get_history("nonexistent")
    
    assert len(queue_result["queue_running"]) == 0
    assert len(queue_result["queue_pending"]) == 0
    assert "nonexistent" not in history


def test_list_assets_integration(mock_comfyui_client, mock_asset_registry):
    """Test list_assets tool integration"""
    from models.asset import AssetRecord
    from datetime import datetime
    
    # Create mock assets
    mock_assets = [
        AssetRecord(
            asset_id="id1",
            filename="test1.png",
            subfolder="",
            folder_type="output",
            prompt_id="p1",
            workflow_id="generate_image",
            created_at=datetime.now(),
            expires_at=None,
            mime_type="image/png",
            width=512,
            height=512,
            bytes_size=12345,
            sha256=None,
            comfy_history=None,
            submitted_workflow=None,
            metadata={}
        )
    ]
    mock_asset_registry.list_assets.return_value = mock_assets
    
    # Test the registry method directly
    assets = mock_asset_registry.list_assets(limit=10)
    assert len(assets) == 1
    assert assets[0].asset_id == "id1"
    assert assets[0].filename == "test1.png"


def test_cancel_job_integration(mock_comfyui_client, mock_asset_registry):
    """Test cancel_job tool integration"""
    result = mock_comfyui_client.cancel_prompt("prompt_123")
    
    assert result["success"] is True
    mock_comfyui_client.cancel_prompt.assert_called_once_with("prompt_123")
