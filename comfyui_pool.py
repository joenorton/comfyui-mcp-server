"""Multi-backend ComfyUI pool with least-queue load balancing."""

import logging
import os
from typing import Any, Dict, Optional, Sequence

import requests

from comfyui_client import ComfyUIClient

logger = logging.getLogger("ComfyUIPool")

MAX_FOREIGN_VRAM_GB = float(os.environ.get("POOL_MAX_FOREIGN_VRAM_GB", "4"))


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

    def _foreign_vram_gb(self, client: ComfyUIClient) -> float:
        """VRAM held by some other process on this backend's GPU (GB).

        Queries the foreign_vram custom_node endpoint, which uses pynvml to
        compute (total VRAM used on the GPU) - (VRAM used by ComfyUI's own PID).
        A value > MAX_FOREIGN_VRAM_GB means another process (e.g. llama.cpp) is
        squatting on the GPU and routing a workflow here will likely OOM.
        ComfyUI's own warm-loaded checkpoint is excluded so it does not
        disqualify the backend.

        Backends without the custom_node endpoint (e.g. older / external) return
        0 → treated as usable. The pool falls back gracefully.
        """
        try:
            r = requests.get(f"{client.base_url}/foreign_vram", timeout=2)
            if r.status_code != 200:
                return 0.0
            data = r.json()
            return data.get("foreign_vram_bytes", 0) / 1e9
        except Exception as e:
            logger.warning(f"foreign_vram check failed for {client.base_url}: {e}")
            return 0.0  # unknown → treat as usable

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
        # Filter out backends with foreign VRAM pressure (other process holding GPU)
        eligible = []
        for name, client in self.clients.items():
            foreign = self._foreign_vram_gb(client)
            if foreign >= MAX_FOREIGN_VRAM_GB:
                logger.info(f"Skipping {name}: foreign VRAM {foreign:.1f}GB >= {MAX_FOREIGN_VRAM_GB}GB")
            else:
                eligible.append((name, client))
        if not eligible:
            logger.warning("All backends VRAM-tight; routing to least-queue anyway")
            eligible = list(self.clients.items())
        # Least-queue among eligible
        chosen_name, chosen_client = min(
            eligible, key=lambda kv: self._queue_depth(kv[1])
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

    def get_queue(self) -> Dict[str, Any]:
        """Aggregate /queue across all backends.

        ComfyUI's /queue returns {queue_running: [...], queue_pending: [...]} per
        instance. Each entry is [priority, prompt_id, prompt_dict, ...]. We return
        a merged shape so callers see one queue across the pool.
        """
        running = []
        pending = []
        for name, client in self.clients.items():
            try:
                q = client.get_queue()
                for item in q.get('queue_running', []):
                    running.append({'backend': name, 'item': item})
                for item in q.get('queue_pending', []):
                    pending.append({'backend': name, 'item': item})
            except Exception as e:
                logger.warning(f'get_queue failed for {client.base_url}: {e}')
        return {'queue_running': running, 'queue_pending': pending}

    def get_history(self, prompt_id: Optional[str] = None) -> Dict[str, Any]:
        """Look up a prompt_id across all backends; return first match.

        ComfyUI history is per-instance and in-memory. The pool doesn't track
        which backend ran a given prompt_id, so we fan out and return whichever
        instance has it. If prompt_id is None, returns merged history (rarely useful).
        """
        if prompt_id:
            for name, client in self.clients.items():
                try:
                    h = client.get_history(prompt_id)
                    if h:
                        return h
                except Exception as e:
                    logger.warning(f'get_history({prompt_id}) failed on {client.base_url}: {e}')
            return {}
        merged = {}
        for client in self.clients.values():
            try:
                merged.update(client.get_history())
            except Exception:
                pass
        return merged

    def cancel_prompt(self, prompt_id: str) -> Dict[str, Any]:
        """Cancel by fanning out — only the backend running the prompt will succeed."""
        last_err = None
        for name, client in self.clients.items():
            try:
                return client.cancel_prompt(prompt_id)
            except Exception as e:
                last_err = e
        if last_err:
            raise Exception(f'cancel_prompt({prompt_id}) failed across pool: {last_err}')
        return {}

