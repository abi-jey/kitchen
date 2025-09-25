"""
This module defines the pre-flight checks for a Kubernetes worker node.
"""
from typing import Any, Dict, List, Tuple
import time

import typer

from kitchen.ssh import SSHSession

CheckResult = Tuple[bool, str]


class WorkerNodePreChecks:
    """
    Runs a series of pre-flight checks on a potential Kubernetes worker node.
    """

    def __init__(self, session: SSHSession, verbose: bool = False):
        self.session = session
        self.verbose = verbose
        self.results: Dict[str, CheckResult] = {}
        self.checks: List[Dict[str, Any]] = [
            {
                "name": "Check for CRI-O service",
                "command": "systemctl is-active crio",
                "description": "Ensures the CRI-O container runtime service is running.",
                "validate": self._validate_is_active,
            },
            {
                "name": "Check for Tailscale service",
                "command": "systemctl is-active tailscaled",
                "description": "Verifies that the Tailscale service is active.",
                "validate": self._validate_is_active,
            },
            {
                "name": "Verify kubelet installation",
                "command": "which kubelet",
                "description": "Checks if kubelet is installed and in the system's PATH.",
                "validate": self._validate_path_exists,
            },
            {
                "name": "Verify kubeadm installation",
                "command": "which kubeadm",
                "description": "Checks if kubeadm is installed and in the system's PATH.",
                "validate": self._validate_path_exists,
            },
        ]

    def run_checks(self, use_sudo: bool = True) -> bool:
        """
        Executes all pre-flight checks on the worker node.
        Returns:
            bool: True if all checks pass, False otherwise.
        """
        typer.secho("Running pre-flight checks on the worker node...", fg=typer.colors.YELLOW)
        all_passed = True

        for check in self.checks:
            name = check["name"]
            command = check["command"]
            validate_func = check["validate"]

            if not self.verbose:
                typer.echo(f"  - {name}...")

            time.sleep(2)
            # For checks that are expected to fail on a fresh node, we don't want to pollute the output
            # with error messages if the command itself fails (e.g., service not found).
            stdout, _, _ = self.session.run(command, use_sudo=use_sudo)
            is_ok, message = validate_func(stdout)

            self.results[name] = (is_ok, message)

            if is_ok:
                if self.verbose:
                    typer.secho(f"  - {name}: ✔ OK", fg=typer.colors.GREEN)
                else:
                    typer.secho(f"    ✔ OK: {message}", fg=typer.colors.GREEN)
            else:
                if self.verbose:
                    typer.secho(f"  - {name}: ❌ FAIL", fg=typer.colors.RED)
                else:
                    typer.secho(f"    ❌ FAIL: {message}", fg=typer.colors.RED)
                all_passed = False

        return all_passed

    def _validate_is_active(self, output: str) -> CheckResult:
        """Validates that a service status is exactly 'active'."""
        status = output.strip().lower()
        if status == "active":
            return True, "Service is active."
        return False, f"Service is not active (status: '{status}')."

    def _validate_path_exists(self, output: str) -> CheckResult:
        """Validates that a command exists in the path."""
        lines = [line for line in output.strip().split("\n") if line.strip()]
        if not lines:
            return False, "No output from command."

        path = lines[-1].strip()
        if path.startswith("/") and "not found" not in path.lower():
            return True, f"Executable found at: {path}"
        return False, "Executable not found in PATH."
