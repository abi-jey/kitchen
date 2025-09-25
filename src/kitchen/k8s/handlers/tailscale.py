"""Tailscale component handler."""
from __future__ import annotations

from typing import Any
import json

import typer

from kitchen.k8s.handlers.base import BaseComponentHandler, CheckOutcome


class TailscaleHandler(BaseComponentHandler):
    """Handles installation and configuration checks for Tailscale."""

    def check_installed(self) -> CheckOutcome:
        stdout, _, _ = self.session.run("which tailscale", use_sudo=True)
        lines = [ln for ln in stdout.strip().split("\n") if ln.strip()]
        if lines and lines[-1].startswith("/") and "not found" not in lines[-1].lower():
            return CheckOutcome(True, f"tailscale at {lines[-1]}")
        return CheckOutcome(False, "tailscale not found in PATH")

    def check_config(self) -> CheckOutcome:
        # Ensure service active first
        active_out, _, _ = self.session.run("systemctl is-active tailscaled", use_sudo=True)
        if active_out.strip().lower() != "active":
            return CheckOutcome(False, f"tailscaled not active (status: '{active_out.strip()}')")
        backend_state = self._backend_state()
        if backend_state is None:
            return CheckOutcome(False, "unable to determine backend state")
        if backend_state not in {"Running", "NoState"}:
            return CheckOutcome(False, f"backend state: {backend_state}")
        return CheckOutcome(True, f"backend state: {backend_state}")

    def install(self) -> bool:
        typer.secho("🔧 Installing and starting Tailscale...", fg=typer.colors.YELLOW)
        install_cmd = "curl -fsSL https://tailscale.com/install.sh | sh"
        _, stderr, code = self.session.run(install_cmd, use_sudo=True)
        if code != 0:
            typer.secho(f"❌ Failed to install Tailscale. STDERR: {stderr}", fg=typer.colors.RED)
            return False
        # Let configure() handle bringing it up with auth key
        return True

    def configure(
        self,
        **kwargs,
    ) -> bool:
        """Configure Tailscale.

        Supported kwargs:
          - auth_key: str | None
          - hostname: str | None
          - accept_routes: bool | None
          - advertise_routes: list[str] | None
          - advertise_tags: list[str] | None
        """
        auth_key: str | None = kwargs.get("auth_key")
        hostname: str | None = kwargs.get("hostname")
        accept_routes: bool | None = kwargs.get("accept_routes")
        advertise_routes: list[str] | None = kwargs.get("advertise_routes")
        advertise_tags: list[str] | None = kwargs.get("advertise_tags")

        # Determine current backend state to decide if we need an auth key
        # Use compact extraction for speed / reduced output
        backend_state = self._backend_state(full_fallback= self.verbose)
        needs_login = backend_state not in {"Running", "NoState"}

        if needs_login and not auth_key:
            typer.secho(
                f"🔑 Tailscale backend state is {backend_state or 'unknown'} and requires authentication.",
                fg=typer.colors.YELLOW,
            )
            auth_key = typer.prompt("Enter Tailscale auth key", hide_input=True)
            if not auth_key:
                typer.secho("❌ No auth key provided. Aborting configuration.", fg=typer.colors.RED)
                return False

        args: list[str] = ["tailscale", "up"]
        if auth_key:
            args.append(f"--authkey={auth_key}")
        if hostname:
            args.append(f"--hostname={hostname}")
        if accept_routes is True:
            args.append("--accept-routes=true")
        if advertise_routes:
            routes = ",".join(advertise_routes)
            args.append(f"--advertise-routes={routes}")
        if advertise_tags:
            tags = ",".join(advertise_tags)
            args.append(f"--advertise-tags={tags}")

        cmd = " ".join(args)
        stdout, stderr, code = self.session.run(cmd, use_sudo=True)
        if code != 0:
            typer.secho(f"❌ Failed to configure Tailscale. STDERR: {stderr}", fg=typer.colors.RED)
            if stdout:
                typer.secho(f"   STDOUT: {stdout}", fg=typer.colors.YELLOW)
            return False
        typer.secho("✅ Tailscale configured.", fg=typer.colors.GREEN)
        return True

    # Internal helpers
    def _parse_backend_state(self, raw: str) -> str | None:
        try:
            data: Any = json.loads(raw)
        except Exception:
            return None
        # Common field path: BackendState
        state = data.get("BackendState") if isinstance(data, dict) else None
        if isinstance(state, str):
            return state
        return None

    def _backend_state(self, full_fallback: bool = False) -> str | None:
        """Return tailscale backend state with minimal command output.

        Uses grep/awk pipeline to avoid dumping entire JSON. If pipeline fails and full_fallback
        is True, performs a single full JSON retrieval and parse; otherwise returns None.
        """
        compact_cmd = (
            "tailscale status --json 2>/dev/null | grep -m1 'BackendState' | "
            "awk -F ':' '{print $2}' | tr -d ' \"{},'"
        )
        state_out, _, _ = self.session.run(compact_cmd, use_sudo=True)
        state = state_out.strip()
        if state:
            return state
        if full_fallback:
            raw_json, _, _ = self.session.run("tailscale status --json", use_sudo=True)
            return self._parse_backend_state(raw_json)
        return None
