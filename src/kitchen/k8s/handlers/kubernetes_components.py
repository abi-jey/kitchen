"""Kubernetes components handler (kubeadm, kubelet, kubectl)."""
from __future__ import annotations

import typer

from kitchen.k8s.handlers.base import BaseComponentHandler, CheckOutcome


class KubernetesComponentsHandler(BaseComponentHandler):
    """Install and configure core Kubernetes binaries (kubeadm, kubelet, kubectl).

    This phase is now separate from the container runtime phase. It installs only Kubernetes
    components and can be aligned with a desired minor version if provided.
    """

    def __init__(self, session, verbose: bool = False, kubernetes_version: str | None = None) -> None:  # type: ignore[override]
        super().__init__(session, verbose)
        norm = None
        if kubernetes_version:
            v = kubernetes_version.strip().lstrip("v")
            parts = v.split('.')
            if len(parts) >= 2:
                norm = f"{parts[0]}.{parts[1]}"
        self.kubernetes_minor = norm

    def check_installed(self) -> CheckOutcome:
        stdout, _, _ = self.session.run("which kubeadm", use_sudo=True)
        path = stdout.strip().splitlines()[-1] if stdout.strip() else ""
        if path.startswith("/") and "not found" not in path.lower():
            return CheckOutcome(True, f"kubeadm at {path}")
        return CheckOutcome(False, "kubeadm not found in PATH")

    def check_config(self) -> CheckOutcome:
        stdout, _, _ = self.session.run("systemctl is-active kubelet", use_sudo=True)
        status = stdout.strip().lower()
        if status == "active":
            return CheckOutcome(True, "kubelet active")
        # Determine if this is a pre-join state: binaries installed but not yet configured by kubeadm join/init
        # If no kubelet config files exist yet, we treat this as a permissible 'pending-join' state so that
        # kube-components phase can succeed prior to actual cluster join.
        cfg_present_stdout, _, _ = self.session.run(
            "test -f /etc/kubernetes/kubelet.conf || test -f /var/lib/kubelet/config.yaml && echo present || echo absent",
            use_sudo=True,
        )
        cfg_present = cfg_present_stdout.strip().lower() == "present"
        if not cfg_present:
            # Service inactive but expected before join; pass with note.
            return CheckOutcome(True, f"kubelet pending join (service status: {status or 'unknown'})")
        return CheckOutcome(False, f"kubelet not active (status: '{status}')")

    def install(self) -> bool:
        typer.secho("🔧 Installing Kubernetes components (kubeadm, kubelet, kubectl)...", fg=typer.colors.YELLOW)
        # Build minor version target
        override_minor = self.kubernetes_minor or ""
        # Avoid Python str.format() conflicts with shell ${VAR} by building via f-string and doubling braces where literal.
        script = f"""
set -e
apt-get update
apt-get install -y apt-transport-https ca-certificates curl gnupg
mkdir -p /etc/apt/keyrings
TARGET_MINOR="{override_minor}"
if [ -z "$TARGET_MINOR" ]; then
  STABLE=$(curl -L -s https://dl.k8s.io/release/stable.txt)
  TARGET_MINOR=$(echo "$STABLE" | cut -d. -f1,2 | sed 's/v//')
fi
echo "Using Kubernetes repo for ${{TARGET_MINOR}}"  # fmt: skip
curl -fsSL "https://pkgs.k8s.io/core:/stable:/v${{TARGET_MINOR}}/deb/Release.key" | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
chmod 0644 /etc/apt/keyrings/kubernetes-apt-keyring.gpg
cat >/etc/apt/sources.list.d/kubernetes.list <<EOF
deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v${{TARGET_MINOR}}/deb/ /
EOF
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl
"""
        _, stderr, code = self.session.run(script, use_sudo=True)
        if code != 0:
            typer.secho(f"❌ Failed to install Kubernetes components. STDERR: {stderr}", fg=typer.colors.RED)
            return False
        typer.secho("✅ Kubernetes components installed.", fg=typer.colors.GREEN)
        return True

    def configure(self, **kwargs) -> bool:
        """Configure kubelet and related components.

        Supported kwargs (optional, safe defaults if omitted):
          - cgroup_driver: "systemd" | "cgroupfs"
          - unhold: bool  # temporarily unhold packages to allow upgrades
        """
        cgroup_driver: str | None = kwargs.get("cgroup_driver")
        unhold: bool = bool(kwargs.get("unhold", False))

        if unhold:
            self.session.run("apt-mark unhold kubelet kubeadm kubectl", use_sudo=True)

        if cgroup_driver in {"systemd", "cgroupfs"}:
            dropin = "/etc/systemd/system/kubelet.service.d/10-kitchen.conf"
            # fmt: skip
            cmd = f"""
set -e
mkdir -p /etc/systemd/system/kubelet.service.d
cat >{dropin} <<EOF
[Service]
Environment="KUBELET_KUBEADM_ARGS=--cgroup-driver={cgroup_driver}"
EOF
systemctl daemon-reload
systemctl restart kubelet
"""
            _, stderr, code = self.session.run(cmd, use_sudo=True)
            if code != 0:
                typer.secho(f"❌ Failed to set kubelet cgroup driver. STDERR: {stderr}", fg=typer.colors.RED)
                return False

        if unhold:
            self.session.run("apt-mark hold kubelet kubeadm kubectl", use_sudo=True)

        # Verify service is up
        check = self.check_config()
        if not check.ok:
            typer.secho(f"❌ kubelet not active after configuration: {check.message}", fg=typer.colors.RED)
            return False
        typer.secho("✅ Kubernetes components configured.", fg=typer.colors.GREEN)
        return True
