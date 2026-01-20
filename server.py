"""ComfyUI MCP Server - Main entry point"""

import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import requests

from mcp.server.fastmcp import FastMCP

from comfyui_client import ComfyUIClient
from managers.asset_registry import AssetRegistry
from managers.defaults_manager import DefaultsManager
from managers.publish_manager import PublishConfig, PublishManager
from managers.workflow_manager import WorkflowManager
from tools.asset import register_asset_tools
from tools.configuration import register_configuration_tools
from tools.generation import register_workflow_generation_tools, register_regenerate_tool
from tools.job import register_job_tools
from tools.publish import register_publish_tools
from tools.workflow import register_workflow_tools

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MCP_Server")

# Configuration paths
WORKFLOW_DIR = Path(os.getenv("COMFY_MCP_WORKFLOW_DIR", str(Path(__file__).parent / "workflows")))

# Asset registry configuration
ASSET_TTL_HOURS = int(os.getenv("COMFY_MCP_ASSET_TTL_HOURS", "24"))

# ComfyUI connection configuration
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188")
COMFYUI_MAX_RETRIES = 5  # Number of retry attempts
COMFYUI_INITIAL_DELAY = 2  # Initial delay in seconds
COMFYUI_MAX_DELAY = 16  # Maximum delay in seconds

# Publish configuration (optional env var for COMFYUI_OUTPUT_ROOT only)
COMFYUI_OUTPUT_ROOT = os.getenv("COMFYUI_OUTPUT_ROOT")


def print_startup_banner():
    """Print a nice startup banner for the server."""
    print("\n" + "=" * 70)
    print("[*] ComfyUI-MCP-Server".center(70))
    print("=" * 70)
    print(f"  Connecting to ComfyUI at: {COMFYUI_URL}")
    print(f"  Workflow directory: {WORKFLOW_DIR}")
    print(f"  Asset TTL: {ASSET_TTL_HOURS} hours")
    print("=" * 70 + "\n")


def check_comfyui_available(base_url: str) -> bool:
    """Check if ComfyUI is available by attempting to fetch model list.
    
    Returns True if ComfyUI is responding, False otherwise.
    """
    try:
        response = requests.get(f"{base_url}/object_info/CheckpointLoaderSimple", timeout=5)
        if response.status_code == 200:
            # Try to parse the response to ensure it's valid
            data = response.json()
            checkpoint_info = data.get("CheckpointLoaderSimple", {})
            if isinstance(checkpoint_info, dict):
                return True
        return False
    except (requests.RequestException, ValueError, KeyError):
        return False


def wait_for_comfyui(base_url: str, max_retries: int = COMFYUI_MAX_RETRIES, 
                     initial_delay: float = COMFYUI_INITIAL_DELAY,
                     max_delay: float = COMFYUI_MAX_DELAY) -> bool:
    """Wait for ComfyUI to become available with exponential backoff.
    
    Args:
        base_url: ComfyUI base URL
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay in seconds between retries
    
    Returns:
        True if ComfyUI becomes available, False if all retries exhausted
    """
    print("\n" + "=" * 70)
    print("[!]  ALERT: ComfyUI is not available!")
    print("=" * 70)
    print(f"  Checking for ComfyUI at: {base_url}")
    print(f"  Waiting for ComfyUI to start (will retry {max_retries} times)...")
    print("=" * 70 + "\n")
    
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        logger.info(f"ComfyUI availability check (attempt {attempt}/{max_retries})...")
        
        if check_comfyui_available(base_url):
            print("\n" + "=" * 70)
            print("[+] ComfyUI is now available!")
            print("=" * 70 + "\n")
            logger.info("ComfyUI is available, proceeding with server startup")
            return True
        
        if attempt < max_retries:
            print(f"[...] Attempt {attempt}/{max_retries} failed. Retrying in {delay:.1f} seconds...")
            time.sleep(delay)
            # Exponential backoff: double the delay, but cap at max_delay
            delay = min(delay * 2, max_delay)
        else:
            print(f"[X] Attempt {attempt}/{max_retries} failed. No more retries.")
    
    return False


# Print startup banner
print_startup_banner()

# Check ComfyUI availability before initializing clients
if not check_comfyui_available(COMFYUI_URL):
    if not wait_for_comfyui(COMFYUI_URL):
        print("\n" + "=" * 70)
        print("[X] ERROR: ComfyUI is not available after all retry attempts!")
        print("=" * 70)
        print(f"  Please ensure ComfyUI is running at: {COMFYUI_URL}")
        print("  Start ComfyUI first, then restart this server.")
        print("=" * 70 + "\n")
        sys.exit(1)

# Global ComfyUI client (fallback since context isn't available)
comfyui_client = ComfyUIClient(COMFYUI_URL)
workflow_manager = WorkflowManager(WORKFLOW_DIR)
defaults_manager = DefaultsManager(comfyui_client)
asset_registry = AssetRegistry(ttl_hours=ASSET_TTL_HOURS, comfyui_base_url=COMFYUI_URL)

# Publish manager (always initialized, uses auto-detection)
try:
    publish_config = PublishConfig(
        comfyui_output_root=COMFYUI_OUTPUT_ROOT,
        comfyui_url=COMFYUI_URL
    )
    publish_manager = PublishManager(publish_config)
    logger.info(f"Publish manager initialized with project_root={publish_config.project_root} (method: {publish_config.project_root_method})")
    logger.info(f"Publish root: {publish_config.publish_root}")
    if publish_config.comfyui_output_root:
        logger.info(f"ComfyUI output root: {publish_config.comfyui_output_root} (method: {publish_config.comfyui_output_method})")
    else:
        logger.info(f"ComfyUI output root: not configured (tried {len(publish_config.comfyui_tried_paths)} paths)")
except Exception as e:
    logger.warning(f"Failed to initialize publish manager: {e}. Publishing features may be unavailable.")
    # Still create a minimal manager so tools can register and return errors
    try:
        from managers.publish_manager import PublishConfig, PublishManager
        publish_config = PublishConfig(comfyui_url=COMFYUI_URL)
        publish_manager = PublishManager(publish_config)
    except Exception:
        publish_manager = None


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

# Register all MCP tools
register_configuration_tools(mcp, comfyui_client, defaults_manager)
register_workflow_tools(mcp, workflow_manager, comfyui_client, defaults_manager, asset_registry)
register_asset_tools(mcp, asset_registry)
register_workflow_generation_tools(mcp, workflow_manager, comfyui_client, defaults_manager, asset_registry)
register_regenerate_tool(mcp, comfyui_client, asset_registry)
register_job_tools(mcp, comfyui_client, asset_registry)
# Always register publish tools (unconditional)
if publish_manager:
    register_publish_tools(mcp, asset_registry, publish_manager)
else:
    logger.error("Publish manager not available - publish tools will not be registered")

if __name__ == "__main__":
    # Check if running as MCP command (stdio) or standalone (streamable-http)
    # When run as command by MCP client (like Cursor), use stdio transport
    # When run standalone, use streamable-http for HTTP access
    if len(sys.argv) > 1 and sys.argv[1] == "--stdio":
        print("\n" + "=" * 70)
        print("[+] Server Ready".center(70))
        print("=" * 70)
        print(f"  Transport: stdio (for MCP clients)")
        print(f"[+] ComfyUI verified at: {COMFYUI_URL}")
        print("=" * 70 + "\n")
        logger.info("Starting MCP server with stdio transport (for MCP clients)")
        logger.info(f"ComfyUI verified at: {COMFYUI_URL}")
        mcp.run(transport="stdio")
    else:
        print("\n" + "=" * 70)
        print("[+] Server Ready".center(70))
        print("=" * 70)
        print(f"  Transport: streamable-http")
        print(f"  Endpoint: http://127.0.0.1:9000/mcp")
        print(f"[+] ComfyUI verified at: {COMFYUI_URL}")
        print("=" * 70 + "\n")
        logger.info("Starting MCP server with streamable-http transport on http://127.0.0.1:9000/mcp")
        logger.info(f"ComfyUI verified at: {COMFYUI_URL}")
        mcp.run(transport="streamable-http")
