"""
This module contains the logic for setting up a Kubernetes worker node.
"""
import typer

from kitchen.k8s.base_node import BaseNode
from kitchen.ssh import SSHSession


class WorkerNode(BaseNode):
    """
    Manages the setup of a Kubernetes worker node.
    """

    def __init__(self, session: SSHSession, verbose: bool = False):
        super().__init__(session, verbose)

    def install_kubernetes_components(self) -> bool:
        """
        Installs kubeadm, kubelet, and kubectl.
        This is a simplified placeholder. A real implementation would need to handle
        adding apt/yum repositories, GPG keys, etc.
        """
        typer.secho("🔧 Installing Kubernetes components (kubeadm, kubelet)...", fg=typer.colors.YELLOW)
        # This command is illustrative. A robust implementation is more complex.
        install_cmd = (
            "apt-get update && "
            "apt-get install -y apt-transport-https ca-certificates curl && "
            "curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg && "
            "echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list && "
            "apt-get update && "
            "apt-get install -y kubelet kubeadm kubectl && "
            "apt-mark hold kubelet kubeadm kubectl"
        )
        output = self.session.run(install_cmd)
        if "error" in output.lower():
            typer.secho("❌ Failed to install Kubernetes components.", fg=typer.colors.RED)
            return False
        typer.secho("✅ Kubernetes components installed.", fg=typer.colors.GREEN)
        return True

    def install_crio(self) -> bool:
        """
        Installs and configures the CRI-O container runtime.
        """
        typer.secho("🔧 Installing CRI-O container runtime...", fg=typer.colors.YELLOW)
        # Placeholder for CRI-O installation steps
        # A real implementation would add the required repositories and install CRI-O.
        crio_cmd = (
            "modprobe overlay && modprobe br_netfilter && "
            "sysctl -w net.bridge.bridge-nf-call-iptables=1 && "
            "sysctl -w net.ipv4.ip_forward=1 && "
            "sysctl -w net.bridge.bridge-nf-call-ip6tables=1 && "
            "apt-get install -y cri-o cri-o-runc && "
            "systemctl daemon-reload && "
            "systemctl enable crio --now"
        )
        output = self.session.run(crio_cmd)
        if "error" in output.lower():
            typer.secho("❌ Failed to install CRI-O.", fg=typer.colors.RED)
            return False
        typer.secho("✅ CRI-O installed and started.", fg=typer.colors.GREEN)
        return True
