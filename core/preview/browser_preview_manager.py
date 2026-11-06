"""Browser Preview Dev Server Manager.

Manages isolated Vite development servers within run sandboxes, providing
real live browser preview capabilities and deterministic process lifecycle management.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional


class BrowserPreviewManager:
    """Manages sandboxed Vite dev server subprocesses for live preview in the dashboard."""

    def __init__(self):
        # Maps run_id -> dict with 'process', 'port', 'url', 'sandbox_path', 'logs'
        self._servers: Dict[str, Dict[str, Any]] = {}

    def is_port_in_use(self, port: int, host: str = "127.0.0.1") -> bool:
        """Checks if a local TCP port is already open/listening."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0

    def find_free_port(self, start_port: int = 5173, max_attempts: int = 20) -> int:
        """Finds an available local port starting from start_port."""
        for port in range(start_port, start_port + max_attempts):
            if not self.is_port_in_use(port):
                return port
        return start_port

    def check_server_health(self, port: int, timeout: float = 1.0) -> bool:
        """Sends an HTTP GET probe to verify that the Vite dev server is responsive."""
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/",
                headers={"User-Agent": "DevPilot-HealthCheck/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status in (200, 304)
        except Exception:
            return False

    def start_preview(
        self,
        sandbox_path: str,
        run_id: str,
        preferred_port: int = 5173,
        timeout_seconds: int = 15,
    ) -> Dict[str, Any]:
        """Starts a sandboxed Vite dev server and waits for readiness probe."""
        path = Path(sandbox_path).resolve()
        if not path.exists():
            return {
                "success": False,
                "error": f"Sandbox path '{sandbox_path}' does not exist.",
                "url": None,
            }

        # If already running for this run_id, verify health and return
        if run_id in self._servers:
            info = self._servers[run_id]
            proc = info.get("process")
            if proc and proc.poll() is None and self.check_server_health(info["port"]):
                return {
                    "success": True,
                    "url": info["url"],
                    "port": info["port"],
                    "run_id": run_id,
                    "pid": proc.pid,
                    "already_running": True,
                    "message": f"Dev server already active at {info['url']}",
                }
            else:
                self.stop_preview(run_id)

        # Detect package manager
        pkg_mgr = "npm"
        if (path / "yarn.lock").exists():
            pkg_mgr = "yarn"
        elif (path / "pnpm-lock.yaml").exists():
            pkg_mgr = "pnpm"
        elif (path / "bun.lockb").exists() or (path / "bun.lock").exists():
            pkg_mgr = "bun"

        # Check if node / npm exists
        if not shutil.which(pkg_mgr):
            return {
                "success": False,
                "error": f"Package manager '{pkg_mgr}' not found on host PATH.",
                "url": None,
            }

        target_port = self.find_free_port(preferred_port)

        # Command to start Vite dev server on specific port and local host
        cmd = [pkg_mgr, "run", "dev", "--", "--port", str(target_port), "--strictPort", "--host", "127.0.0.1"]

        try:
            # Spawn in isolated subprocess without blocking
            proc = subprocess.Popen(
                cmd,
                cwd=str(path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=(sys.platform == "win32"),
            )

            # Wait for readiness probe
            start_time = time.time()
            is_ready = False
            while time.time() - start_time < timeout_seconds:
                # Check if process terminated prematurely
                ret_code = proc.poll()
                if ret_code is not None:
                    _, stderr_out = proc.communicate(timeout=2)
                    return {
                        "success": False,
                        "error": f"Dev server process exited prematurely with code {ret_code}: {stderr_out[:300]}",
                        "url": None,
                    }

                if self.check_server_health(target_port, timeout=0.8):
                    is_ready = True
                    break
                time.sleep(0.5)

            if not is_ready:
                # Timed out waiting for server probe
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                return {
                    "success": False,
                    "error": f"Vite dev server failed to respond on http://127.0.0.1:{target_port} within {timeout_seconds}s.",
                    "url": None,
                }

            url = f"http://127.0.0.1:{target_port}"
            self._servers[run_id] = {
                "process": proc,
                "port": target_port,
                "url": url,
                "sandbox_path": str(path),
                "started_at": time.time(),
            }

            return {
                "success": True,
                "url": url,
                "port": target_port,
                "run_id": run_id,
                "pid": proc.pid,
                "message": f"Live Vite server ready at {url}",
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to spawn preview server: {str(e)}",
                "url": None,
            }

    def get_preview_status(self, run_id: str) -> Dict[str, Any]:
        """Returns the live status of the preview server for a run."""
        if run_id not in self._servers:
            return {"active": False, "url": None, "port": None}

        info = self._servers[run_id]
        proc = info.get("process")
        is_alive = proc is not None and proc.poll() is None
        is_healthy = is_alive and self.check_server_health(info["port"])

        return {
            "active": is_healthy,
            "url": info["url"] if is_healthy else None,
            "port": info["port"] if is_healthy else None,
            "pid": proc.pid if proc else None,
        }

    def stop_preview(self, run_id: str) -> Dict[str, Any]:
        """Safely stops and cleans up a preview server subprocess."""
        if run_id not in self._servers:
            return {"success": True, "message": "No active server for this run."}

        info = self._servers.pop(run_id)
        proc = info.get("process")
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        return {
            "success": True,
            "message": f"Preview server on port {info.get('port')} terminated successfully.",
        }

    def stop_all(self) -> None:
        """Terminates all active preview server subprocesses."""
        run_ids = list(self._servers.keys())
        for r_id in run_ids:
            self.stop_preview(r_id)


# Global singleton instance
preview_manager = BrowserPreviewManager()

