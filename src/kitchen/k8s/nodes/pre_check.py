"""
This module defines the pre-flight checks for a Kubernetes master node.
"""
import re
from typing import Any, Callable, Dict, List, Tuple

import typer

from kitchen.ssh import SSHSession

CheckResult = Tuple[bool, str]


class MasterNodePreChecks:
    """
    Runs a series of pre-flight checks on a Kubernetes master node to ensure
    it's ready for a new worker node to join, with a focus on Tailscale networking.
    """

    def __init__(self, session: SSHSession, verbose: bool = False):
        self.session = session
        self.verbose = verbose
        self.results: Dict[str, CheckResult] = {}
        self.tailscale_ip: str | None = None
        self.checks: List[Dict[str, Any]] = [
            {
                "name": "Check for kubelet service",
                "command": "systemctl is-active kubelet",
                "description": "Ensures the kubelet service is running on the master node.",
                "validate": self._validate_is_active,
            },
            {
                "name": "Check for Tailscale service",
                "command": "systemctl is-active tailscaled",
                "description": "Verifies that the Tailscale service is active.",
                "validate": self._validate_is_active,
            },
            {
                "name": "Get Tailscale IP address",
                "command": "tailscale ip -4",
                "description": "Fetches the Tailscale IPv4 address of the master node.",
                "validate": self._validate_ip_address,
            },
            {
                "name": "Verify kubeadm installation",
                "command": "which kubeadm",
                "description": "Checks if kubeadm is installed and in the system's PATH.",
                "validate": self._validate_path_exists,
            },
            {
                "name": "Verify Tailscale IP in kube-apiserver SANs",
                "command": "openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -text",
                "description": "Ensures the Tailscale IP is in the kube-apiserver certificate's Subject Alternative Names (SANs).",
                "validate": self._validate_sans,
            },
        ]

    def get_check_plan(self) -> List[str]:
        """Returns a list of descriptions for each check to be performed."""
        return [check["description"] for check in self.checks]

    def run_checks(self) -> bool:
        """
        Executes all pre-flight checks on the master node.

        Returns:
            bool: True if all checks pass, False otherwise.
        """
        typer.secho("Running pre-flight checks on the master node...", fg=typer.colors.YELLOW)
        all_passed = True

        for check in self.checks:
            name = check["name"]
            command = check["command"]
            validate_func = check["validate"]

            if not self.verbose:
                typer.echo(f"  - {name}...")

            stdout, _, _ = self.session.run(command)
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
                # If not verbose, show the full output on failure for context
                if not self.verbose:
                    typer.secho("    [REMOTE OUTPUT]", fg=typer.colors.CYAN)
                    typer.echo(self.session.last_output)
                    typer.secho("    [END REMOTE OUTPUT]", fg=typer.colors.CYAN)

        return all_passed

    def _validate_is_active(self, output: str) -> CheckResult:
        """Validates that a service status is 'active'."""
        if "active" in output.strip().lower():
            return True, "Service is active."
        return False, f"Service is not active. Full output: '{output.strip()}'"

    def _validate_ip_address(self, output: str) -> CheckResult:
        """Validates that the output contains a valid IP address."""
        # Use regex to find an IPv4 address in the output
        ip_match = re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", output)
        if ip_match:
            ip = ip_match.group(0)
            self.tailscale_ip = ip
            return True, f"Got IP: {ip}"
        return False, f"Could not find a valid IPv4 address in output: '{output.strip()}'"

    def _validate_path_exists(self, output: str) -> CheckResult:
        """Validates that a command exists in the path."""
        # The output might contain the command echo, so we take the last non-empty line
        lines = [line for line in output.strip().split("\n") if line.strip()]
        if not lines:
            return False, "No output from command."

        path = lines[-1].strip()
        if path.startswith("/") and "not found" not in path.lower():
            return True, f"Executable found at: {path}"
        return False, f"Executable not found in PATH. Command output: '{path}'"

    def _validate_sans(self, output: str) -> CheckResult:
        """Validates that the Tailscale IP is in the SANs of the kube-apiserver certificate."""
        if not self.tailscale_ip:
            return False, "Could not verify SANs because Tailscale IP was not found."

        # The SANs can be spread across multiple lines, so we search for the section.
        sans_match = re.search(r"X509v3 Subject Alternative Name:((?:.|\n)*?)(?:X509v3|$)", output)
        if not sans_match:
            return False, "Could not find 'Subject Alternative Name' section in certificate."

        sans_section = sans_match.group(1)
        # Check for the IP address within the SANs section
        if f"IP Address:{self.tailscale_ip}" in sans_section:
            return True, f"Tailscale IP ({self.tailscale_ip}) found in certificate SANs."

        return False, f"Tailscale IP ({self.tailscale_ip}) not found in certificate SANs."
