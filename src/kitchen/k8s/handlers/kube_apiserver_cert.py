"""Kube-apiserver certificate SANs handler."""
from __future__ import annotations

import re
from datetime import datetime

import typer

from kitchen.k8s.handlers.base import BaseComponentHandler, CheckOutcome


class KubeAPIServerCertHandler(BaseComponentHandler):
    """Verifies and updates kube-apiserver certificate SANs for a given IP (e.g., Tailscale IP)."""

    def __init__(self, session, verbose: bool = False, required_ip: str | None = None):
        super().__init__(session, verbose)
        self.required_ip = required_ip

    def check_installed(self) -> CheckOutcome:
        # Verify openssl presence as a basic capability
        stdout, _, _ = self.session.run("which openssl", use_sudo=True)
        if stdout.strip():
            return CheckOutcome(True, "openssl present")
        return CheckOutcome(False, "openssl not found")

    def check_config(self) -> CheckOutcome:
        if not self.required_ip:
            return CheckOutcome(False, "No required IP provided for SANs check")
        verify_cmd = (
            "openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -text | grep 'Subject Alternative Name' -A 1"
        )
        stdout, _, _ = self.session.run(verify_cmd, use_sudo=True)
        ok = self.required_ip in stdout
        return CheckOutcome(ok, "SANs contain required IP" if ok else "Required IP missing in SANs")

    def install(self) -> bool:
        if not self.required_ip:
            typer.secho("❌ No IP provided to add to SANs.", fg=typer.colors.RED)
            return False

        if not self._check_yq_installed():
            self._install_yq()

        typer.secho("🔧 Fixing kube-apiserver SANs...", fg=typer.colors.YELLOW)
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        backup_dir = f"/etc/kubernetes/pki/backup/{timestamp}"
        self.session.run(f"mkdir -p {backup_dir} && cp /etc/kubernetes/pki/apiserver.{{crt,key}} {backup_dir}/", use_sudo=True)

        self.session.run("rm /etc/kubernetes/pki/apiserver.crt /etc/kubernetes/pki/apiserver.key", use_sudo=True)

        remote_config_path = f"/tmp/kubeadm_config_{timestamp}.yaml"
        extract_command = (
            f"kubectl get cm -n kube-system kubeadm-config -o jsonpath='{{.data.ClusterConfiguration}}' > {remote_config_path}"
        )
        self.session.run(extract_command, use_sudo=True)

        # fmt: off
        yq_command = (
            f"yq -i '(.apiServer.certSANs |= (. + [\"{self.required_ip}\"] | unique))' {remote_config_path}"
        )
        # fmt: on
        self.session.run(yq_command, use_sudo=True)

        self.session.run(f"kubeadm init phase certs apiserver --config {remote_config_path}", use_sudo=True)
        self.session.run(f"kubectl apply -f {remote_config_path}", use_sudo=True)
        self.session.run("systemctl restart kubelet", use_sudo=True)
        self.session.run(f"rm {remote_config_path}", use_sudo=True)

        # final verification
        verify = self.check_config()
        if verify.ok:
            typer.secho("✅ SANs updated.", fg=typer.colors.GREEN)
            return True
        typer.secho("❌ SANs update verification failed.", fg=typer.colors.RED)
        return False

    def _check_yq_installed(self) -> bool:
        stdout, _, _ = self.session.run("which yq", use_sudo=True)
        return bool(stdout.strip())

    def _install_yq(self) -> None:
        typer.echo("  - yq not found. Attempting to install...")
        if not typer.confirm("Proceed with yq installation on the master node?"):
            return
        # fmt: off
        install_command = (
            "wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -O /usr/bin/yq "
            "&& chmod +x /usr/bin/yq"
        )
        # fmt: on
        self.session.run(install_command, use_sudo=True)
        typer.secho("    ✅ yq installed successfully.", fg=typer.colors.GREEN)

    def configure(self, **kwargs) -> bool:
        """Ensure SANs contains the provided IP; if missing, attempt to add it.

        Supported kwargs:
          - required_ip: str  # overrides constructor-provided IP
        """
        required_ip = kwargs.get("required_ip") or self.required_ip
        self.required_ip = required_ip
        if not self.required_ip:
            typer.secho("❌ No required_ip provided for SANs configuration.", fg=typer.colors.RED)
            return False
        res = self.check_config()
        if res.ok:
            typer.secho("✅ SANs already contain required IP.", fg=typer.colors.GREEN)
            return True
        return self.install()
