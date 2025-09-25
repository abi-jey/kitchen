"""
This module contains functions for managing a Kubernetes master node.
"""
from logging import getLogger
import re
from datetime import datetime
from typing import Tuple

import typer
import yaml

from kitchen.k8s.base_node import BaseNode
from kitchen.k8s.nodes.pre_check import MasterNodePreChecks
from kitchen.ssh import SSHSession


class VerificationError(Exception):
    """Custom exception for verification failures."""

    pass


logger = getLogger(__name__)


def _clean_ansi_codes(text: str) -> str:
    """Removes ANSI escape codes from a string."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


class MasterNode(BaseNode):
    """
    Manages operations on a Kubernetes master node, including pre-flight checks and configuration fixes.
    """

    def __init__(self, ssh_session: SSHSession, verbose: bool = False):
        super().__init__(ssh_session, verbose)

    def fix_apiserver_sans(self, tailscale_ip: str) -> bool:
        """
        Adds the Tailscale IP to the kube-apiserver certificate's Subject Alternative Names (SANs) using yq.
        """
        if not tailscale_ip:
            typer.secho("❌ Cannot fix SANs without a Tailscale IP.", fg=typer.colors.RED)
            return False

        if not self._check_yq_installed():
            self._install_yq()

        typer.secho("🔧 Attempting to fix kube-apiserver SANs...", fg=typer.colors.YELLOW)
        remote_config_path = ""  # Initialize to empty string
        try:
            # Step 1: Backup and remove old certificates
            timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            backup_dir = f"/etc/kubernetes/pki/backup/{timestamp}"
            backup_command = f"mkdir -p {backup_dir} && cp /etc/kubernetes/pki/apiserver.{{crt,key}} {backup_dir}/"
            self.session.run(backup_command, use_sudo=True)

            typer.secho("    - Deleting old certificate and key...", fg=typer.colors.YELLOW)
            delete_command = "rm /etc/kubernetes/pki/apiserver.crt /etc/kubernetes/pki/apiserver.key"
            self.session.run(delete_command, use_sudo=True)

            # Step 2: Extract ClusterConfiguration, save to a temporary file
            remote_config_path = f"/tmp/kubeadm_config_{timestamp}.yaml"
            extract_command = (
                f"kubectl get cm -n kube-system kubeadm-config -o jsonpath='{{.data.ClusterConfiguration}}' "
                f"> {remote_config_path}"
            )
            self.session.run(extract_command, use_sudo=True)

            # Step 3: Update the temporary file with the new SAN
            # fmt: off
            yq_command = (
                f"yq -i '(.apiServer.certSANs |= (. + [\"{tailscale_ip}\"] | unique))' {remote_config_path}"
            )
            # fmt: on
            self.session.run(yq_command, use_sudo=True)

            # Step 4: Regenerate certificates using the updated temporary config file
            typer.secho("    - Regenerating apiserver certificates with new SANs...", fg=typer.colors.YELLOW)
            kubeadm_command = f"kubeadm init phase certs apiserver --config {remote_config_path}"
            self.session.run(kubeadm_command, use_sudo=True)

            # Step 5: Update the kubeadm-config ConfigMap in the cluster
            typer.secho("    - Applying updated configuration to the cluster...", fg=typer.colors.YELLOW)
            apply_command = f"kubectl apply -f {remote_config_path}"
            self.session.run(apply_command, use_sudo=True)

            # Step 6: Restart kubelet
            typer.secho("    - Restarting kubelet to apply changes...", fg=typer.colors.YELLOW)
            restart_command = "systemctl restart kubelet"
            self.session.run(restart_command, use_sudo=True)

            # Final verification
            try:
                self._verify_sans_update(tailscale_ip)
                typer.secho("✅ Successfully fixed SANs issue.", fg=typer.colors.GREEN)
                return True
            finally:
                if remote_config_path:
                    self.session.run(f"rm {remote_config_path}", use_sudo=True)

        except Exception as e:
            typer.secho(f"❌ An error occurred during SANs fix: {e}", fg=typer.colors.RED)
            return False

    def get_join_command(self, tailscale_ip: str) -> Tuple[str, str, int]:
        """
        Generates a new token and returns the join command, ensuring it uses the Tailscale IP.
        """
        typer.secho("🔑 Generating new join token and command...", fg=typer.colors.CYAN)
        command = "kubeadm token create --print-join-command"
        stdout, stderr, code = self.session.run(command, use_sudo=True)

        if code != 0:
            return "", stderr, code

        # Replace the advertised IP with the Tailscale IP
        # The default command uses the node's primary IP, we want to override that.
        modified_join_command = re.sub(
            r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)",
            f"{tailscale_ip}:6443",
            stdout,
        )

        return modified_join_command.strip(), stderr, code

    def _check_yq_installed(self) -> bool:
        """
        Checks if yq is installed on the remote host.
        """
        stdout, _, _ = self.session.run("which yq", use_sudo=True)
        return stdout.strip() != ""

    def _install_yq(self) -> None:
        """Installs yq on the master node."""
        typer.echo("  - yq not found. Attempting to install...")
        if not typer.confirm("Do you want to proceed with yq installation on the master node?"):
            return

        # fmt: off
        install_command = (
            "wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -O /usr/bin/yq "
            "&& chmod +x /usr/bin/yq"
        )
        # fmt: on
        self.session.run(install_command, use_sudo=True)
        typer.secho("    ✅ yq installed successfully.", fg=typer.colors.GREEN)

    def _verify_sans_update(self, tailscale_ip: str) -> None:
        """
        Verifies that the Tailscale IP is present in the kube-apiserver certificate SANs.
        """
        verify_command = f"openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -text | grep {tailscale_ip}"
        stdout, _, _ = self.session.run(verify_command, use_sudo=True)
        if tailscale_ip not in stdout:
            raise VerificationError("Tailscale IP not found in SANs after update.")
