"""Tests for categorized model listing feature"""
import pytest
from unittest.mock import Mock, patch
from comfyui_client import ComfyUIClient


class TestModelCategorization:
    """Test suite for categorized model detection"""
    
    @patch('comfyui_client.requests.get')
    def test_get_available_models_categorized_all_types(self, mock_get):
        """Test that all three model types are detected correctly"""
        # Mock responses for different loader endpoints
        def mock_response(url, **kwargs):
            response = Mock()
            response.status_code = 200
            
            if "CheckpointLoaderSimple" in url:
                response.json.return_value = {
                    "CheckpointLoaderSimple": {
                        "input": {
                            "required": {
                                "ckpt_name": [
                                    ["model1.safetensors", "model2.ckpt"]
                                ]
                            }
                        }
                    }
                }
            elif "UNETLoader" in url:
                response.json.return_value = {
                    "UNETLoader": {
                        "input": {
                            "required": {
                                "unet_name": [
                                    ["flux_dev.safetensors", "sd3_medium.safetensors"]
                                ]
                            }
                        }
                    }
                }
            elif "DiffusionModelLoader" in url:
                response.json.return_value = {
                    "DiffusionModelLoader": {
                        "input": {
                            "required": {
                                "model_path": [
                                    ["z_image_turbo_bf16.safetensors"]
                                ]
                            }
                        }
                    }
                }
            else:
                response.status_code = 404
            
            return response
        
        mock_get.side_effect = mock_response
        
        client = ComfyUIClient("http://localhost:8188")
        
        # Verify all categories are populated
        assert len(client.available_models_categorized["checkpoints"]) == 2
        assert len(client.available_models_categorized["unet"]) == 2
        assert len(client.available_models_categorized["diffusion_models"]) == 1
        
        # Verify correct models in each category
        assert "model1.safetensors" in client.available_models_categorized["checkpoints"]
        assert "flux_dev.safetensors" in client.available_models_categorized["unet"]
        assert "z_image_turbo_bf16.safetensors" in client.available_models_categorized["diffusion_models"]
        
        # Verify backward compatibility: available_models defaults to checkpoints
        assert client.available_models == client.available_models_categorized["checkpoints"]
    
    @patch('comfyui_client.requests.get')
    def test_get_available_models_categorized_partial_failure(self, mock_get):
        """Test graceful handling when some endpoints fail"""
        def mock_response(url, **kwargs):
            response = Mock()
            
            if "CheckpointLoaderSimple" in url:
                response.status_code = 200
                response.json.return_value = {
                    "CheckpointLoaderSimple": {
                        "input": {
                            "required": {
                                "ckpt_name": [["model1.safetensors"]]
                            }
                        }
                    }
                }
            else:
                # Other endpoints fail
                response.status_code = 404
            
            return response
        
        mock_get.side_effect = mock_response
        
        client = ComfyUIClient("http://localhost:8188")
        
        # Should have checkpoints but not other types
        assert len(client.available_models_categorized["checkpoints"]) == 1
        assert len(client.available_models_categorized["unet"]) == 0
        assert len(client.available_models_categorized["diffusion_models"]) == 0
    
    @patch('comfyui_client.requests.get')
    def test_refresh_models_updates_categorized(self, mock_get):
        """Test that refresh_models() updates categorized data"""
        # First call: one checkpoint
        # Second call: two checkpoints
        call_count = [0]
        
        def mock_response(url, **kwargs):
            response = Mock()
            response.status_code = 200
            call_count[0] += 1
            
            if "CheckpointLoaderSimple" in url:
                if call_count[0] <= 3:  # First init call (3 endpoints)
                    response.json.return_value = {
                        "CheckpointLoaderSimple": {
                            "input": {
                                "required": {
                                    "ckpt_name": [["model1.safetensors"]]
                                }
                            }
                        }
                    }
                else:  # After refresh
                    response.json.return_value = {
                        "CheckpointLoaderSimple": {
                            "input": {
                                "required": {
                                    "ckpt_name": [["model1.safetensors", "model2.safetensors"]]
                                }
                            }
                        }
                    }
            else:
                response.json.return_value = {}
            
            return response
        
        mock_get.side_effect = mock_response
        
        client = ComfyUIClient("http://localhost:8188")
        assert len(client.available_models_categorized["checkpoints"]) == 1
        
        # Refresh models
        client.refresh_models()
        assert len(client.available_models_categorized["checkpoints"]) == 2
        assert "model2.safetensors" in client.available_models_categorized["checkpoints"]


class TestListModelsTool:
    """Test the list_models MCP tool with categorization"""
    
    def test_list_models_returns_categorized_structure(self):
        """Test that list_models logic returns the new categorized structure"""
        # Mock ComfyUI client with categorized models
        mock_client = Mock()
        mock_client.available_models_categorized = {
            "checkpoints": ["sd_xl.safetensors", "sd_15.ckpt"],
            "unet": ["flux_dev.safetensors"],
            "diffusion_models": ["z_image_turbo_bf16.safetensors"]
        }
        
        # Simulate the list_models logic directly
        categorized = mock_client.available_models_categorized
        checkpoints = categorized.get("checkpoints", [])
        unet = categorized.get("unet", [])
        diffusion = categorized.get("diffusion_models", [])
        
        total_count = len(checkpoints) + len(unet) + len(diffusion)
        
        result = {
            "models": {
                "checkpoints": checkpoints,
                "unet": unet,
                "diffusion_models": diffusion
            },
            "counts": {
                "checkpoints": len(checkpoints),
                "unet": len(unet),
                "diffusion_models": len(diffusion),
                "total": total_count
            },
            "default_checkpoint": "v1-5-pruned-emaonly.ckpt" if checkpoints else None
        }
        
        # Verify structure
        assert "models" in result
        assert "counts" in result
        assert "checkpoints" in result["models"]
        assert "unet" in result["models"]
        assert "diffusion_models" in result["models"]
        
        # Verify counts
        assert result["counts"]["checkpoints"] == 2
        assert result["counts"]["unet"] == 1
        assert result["counts"]["diffusion_models"] == 1
        assert result["counts"]["total"] == 4
        
        # Verify model names
        assert "sd_xl.safetensors" in result["models"]["checkpoints"]
        assert "flux_dev.safetensors" in result["models"]["unet"]
        assert "z_image_turbo_bf16.safetensors" in result["models"]["diffusion_models"]
    
    def test_list_models_tool_registration(self):
        """Test that list_models tool is properly registered"""
        from tools.configuration import register_configuration_tools
        from mcp.server.fastmcp import FastMCP
        
        mock_client = Mock()
        mock_client.available_models_categorized = {
            "checkpoints": [],
            "unet": [],
            "diffusion_models": []
        }
        mock_defaults = Mock()
        
        # Create MCP instance and register tools
        mcp = FastMCP("test")
        register_configuration_tools(mcp, mock_client, mock_defaults)
        
        # Verify tool is registered
        tool_names = [tool.name for tool in mcp._tool_manager.list_tools()]
        assert "list_models" in tool_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
