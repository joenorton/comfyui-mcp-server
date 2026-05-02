"""Multi-backend ComfyUI pool with least-queue load balancing."""

import logging
from typing import Any, Dict, Optional, Sequence

import requests

from comfyui_client import ComfyUIClient

logger = logging.getLogger("ComfyUIPool")


def parse_backends(urls_str: str) -> dict[str, str]:
    """Parse COMFYUI_URLS env: name1=url1,name2=url2"""
    backends = {}
    for part in urls_str.split(","):
        part = part.strip()
        if "=" in part:
            name, url = part.split("=", 1)
            backends[name.strip()] = url.strip()
        else:
            backends[f"backend{len(backends)+1}"] = part
    return backends


class ComfyUIPool:
    """Drop-in replacement for ComfyUIClient supporting multiple backends.

    Routing:
    - backend=None (default): route to backend with shortest queue
    - backend="name": route to named backend explicitly
    """

    def __init__(self, backends: dict[str, str]):
        self.clients: dict[str, ComfyUIClient] = {
            name: ComfyUIClient(url) for name, url in backends.items()
        }
        self.names = list(self.clients.keys())
        logger.info(f"ComfyUIPool: {len(self.clients)} backends — {list(backends.keys())}")

    @property
    def base_url(self) -> str:
        """Primary backend URL (for compatibility with single-client code)."""
        return self.clients[self.names[0]].base_url

    @property
    def available_models(self) -> list:
        seen: set = set()
        result = []
        for client in self.clients.values():
            for m in client.available_models:
                normalized = m.replace("\\", "/")
                if normalized not in seen:
                    seen.add(normalized)
                    result.append(normalized)
        return result

    def refresh_models(self):
        for client in self.clients.values():
            client.refresh_models()

    def _queue_depth(self, client: ComfyUIClient) -> int:
        try:
            r = requests.get(f"{client.base_url}/queue", timeout=3)
            if r.status_code == 200:
                data = r.json()
                depth = len(data.get("queue_running", [])) + len(data.get("queue_pending", []))
                logger.debug(f"Queue depth {client.base_url}: {depth}")
                return depth
        except Exception as e:
            logger.warning(f"Queue check failed for {client.base_url}: {e}")
        return 999  # treat unreachable as full

    def _pick_client(self, backend: Optional[str] = None) -> ComfyUIClient:
        if backend:
            if backend in self.clients:
                logger.info(f"Routing to explicit backend: {backend}")
                return self.clients[backend]
            # partial match on URL
            for name, client in self.clients.items():
                if backend in client.base_url:
                    logger.info(f"Routing to URL-matched backend: {name}")
                    return client
            logger.warning(f"Unknown backend {backend}, falling back to least-queue")
        # Least-queue routing
        chosen_name, chosen_client = min(
            self.clients.items(), key=lambda kv: self._queue_depth(kv[1])
        )
        logger.info(f"Least-queue routing to: {chosen_name}")
        return chosen_client

    def run_custom_workflow(
        self,
        workflow: Dict[str, Any],
        backend: Optional[str] = None,
        preferred_output_keys: Optional[Sequence[str]] = None,
        max_attempts: int = 30,
    ) -> Dict[str, Any]:
        client = self._pick_client(backend)
        result = client.run_custom_workflow(
            workflow,
            preferred_output_keys=preferred_output_keys,
            max_attempts=max_attempts,
        )
        if isinstance(result, dict) and result.get("status") != "running":
            result["backend_url"] = client.base_url
        return result
