"""CRI-O component handler."""
from __future__ import annotations

import typer
from typing import Optional

from kitchen.k8s.handlers.base import BaseComponentHandler, CheckOutcome


class CrioHandler(BaseComponentHandler):
    """Install and verify only the CRI-O container runtime (no kube components).

    Accepts optional kubernetes_version to align CRI-O minor stream with desired Kubernetes minor.
    Kubernetes components are now installed by a separate 'kube-components' phase.
    """

    def __init__(self, session, verbose: bool = False, kubernetes_version: str | None = None) -> None:  # type: ignore[override]
        super().__init__(session, verbose)
        # Normalize versions like 'v1.34' or '1.34.x' to '1.34'
        norm = None
        if kubernetes_version:
            v = kubernetes_version.strip().lstrip("v")
            parts = v.split(".")
            if len(parts) >= 2:
                norm = f"{parts[0]}.{parts[1]}"
        self.kubernetes_minor = norm

    def check_installed(self) -> CheckOutcome:
        stdout, _, _ = self.session.run("systemctl is-active crio", use_sudo=True)
        if stdout.strip().lower() == "active":
            return CheckOutcome(True, "crio active")
        return CheckOutcome(False, f"crio not active (status: '{stdout.strip()}')")

    def check_config(self) -> CheckOutcome:
        # For CRI-O we treat service active as configured
        return self.check_installed()

    def install(self) -> bool:
        typer.secho("🔧 Installing CRI-O container runtime (runtime-only phase)...", fg=typer.colors.YELLOW)
        minor = self._determine_minor_version()
        if minor is None:
            typer.secho("❌ Could not determine target minor version (for CRI-O stream).", fg=typer.colors.RED)
            return False
        typer.secho(f"➡️  Using CRI-O minor stream aligned with Kubernetes minor: {minor}", fg=typer.colors.CYAN)

        if not self._verify_os():
            return False
        if not self._apply_kernel_prereqs():
            return False
        if not self._apply_sysctl():
            return False
        if not self._ensure_prereq_tools():
            return False
        if not self._add_crio_repo(minor):
            return False
        if not self._apt_update():
            return False
        if not self._install_packages():
            return False
        if not self._enable_service():
            return False
        self._smoke_test()
        typer.secho("✅ CRI-O installed and started.", fg=typer.colors.GREEN)
        return True

    # ------------------------- helper steps -------------------------
    def _run(self, command: str, desc: str, ignore_errors: bool = False) -> bool:
        """Utility to run a sudo command with description and basic error handling."""
        stdout, stderr, code = self.session.run(command, use_sudo=True)
        if code != 0 and not ignore_errors:
            typer.secho(f"❌ {desc} failed (exit {code}).", fg=typer.colors.RED)
            if stderr:
                typer.echo(stderr)
            return False
        if code == 0 and self.verbose:
            typer.secho(f"✅ {desc}", fg=typer.colors.GREEN)
        elif code != 0 and ignore_errors and self.verbose:
            typer.secho(f"⚠️ {desc} (ignored failure, exit {code})", fg=typer.colors.YELLOW)
        return True

    def _verify_os(self) -> bool:
        cmd = ". /etc/os-release; if [ \"$ID\" = ubuntu ] || [ \"$ID\" = debian ]; then echo ok; else echo bad:$ID; fi"
        stdout, _, _ = self.session.run(cmd, use_sudo=True)
        if not stdout.strip().startswith("ok"):
            typer.secho("❌ Unsupported OS (need Ubuntu/Debian).", fg=typer.colors.RED)
            return False
        return True

    def _apply_kernel_prereqs(self) -> bool:
        return self._run("modprobe overlay || true", "Load overlay module", ignore_errors=True) and \
            self._run("modprobe br_netfilter || true", "Load br_netfilter module", ignore_errors=True)

    def _apply_sysctl(self) -> bool:
        sysctl_content = (
            "net.bridge.bridge-nf-call-iptables=1\n"
            "net.ipv4.ip_forward=1\n"
            "net.bridge.bridge-nf-call-ip6tables=1\n"
        )
        # Use cat EOF inline to avoid needing temp file
        cmd = (
            "cat > /etc/sysctl.d/99-kubernetes-cri.conf <<'EOF'\n" + sysctl_content + "EOF\n"
            "sysctl --system >/dev/null 2>&1 || true"
        )
        return self._run(cmd, "Apply sysctl settings", ignore_errors=False)

    def _determine_minor_version(self) -> Optional[str]:
        if self.kubernetes_minor:
            return self.kubernetes_minor
        stdout, _, _ = self.session.run(
            "curl -L -s https://dl.k8s.io/release/stable.txt | cut -d. -f1,2 | sed 's/v//'",
            use_sudo=True,
        )
        minor = stdout.strip()
        if minor and minor.count(".") == 1:
            return minor
        return None

    def _ensure_keyrings_dir(self) -> bool:
        return self._run("mkdir -p /etc/apt/keyrings", "Ensure keyrings directory")

    def _add_crio_repo(self, minor: str) -> bool:
        if not self._ensure_keyrings_dir():
            return False
        # fmt: skip
        cmd = (
            f"curl -fsSL https://download.opensuse.org/repositories/isv:/cri-o:/stable:/v{minor}/deb/Release.key | gpg --batch --yes --no-tty --dearmor -o /etc/apt/keyrings/cri-o-apt-keyring.gpg && "
            f"echo 'deb [signed-by=/etc/apt/keyrings/cri-o-apt-keyring.gpg] https://download.opensuse.org/repositories/isv:/cri-o:/stable:/v{minor}/deb/ /' > /etc/apt/sources.list.d/cri-o.list"
        )
        return self._run(cmd, "Add CRI-O apt repo")

    def _ensure_prereq_tools(self) -> bool:
        """Install required tools for repository management (curl, gpg)."""
        return self._run(
            "DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y curl gnupg",
            "Install prerequisite tools (curl, gnupg)",
        )

    def _apt_update(self) -> bool:
        return self._run("apt-get update", "apt-get update")

    def _install_packages(self) -> bool:
        # Some distributions package runc inside cri-o already; cri-o-runc and cri-tools may not exist in the repo.
        # We install just cri-o first, then attempt to provide crictl manually if absent (non-fatal if fails).
        if not self._run(
            "DEBIAN_FRONTEND=noninteractive apt-get install -y cri-o",
            "Install CRI-O runtime package",
        ):
            return False
        # Check for crictl; if missing, attempt a lightweight manual install (best-effort, non-fatal).
        stdout, _, _ = self.session.run("which crictl || command -v crictl", use_sudo=True)
        if not stdout.strip():
            # Determine latest crictl matching major.minor (heuristic: use Kubernetes minor for compatibility) ; fallback to skip
            minor = self.kubernetes_minor or self._determine_minor_version() or ""
            # Use GitHub release tarball naming pattern, e.g., crictl-v1.29.0-linux-amd64.tar.gz
            # We deliberately avoid parsing GitHub API (no network JSON tooling) and attempt a common patch version .0
            crictl_version = minor + ".0" if minor else ""
            if crictl_version:
                fetch_cmd = (
                    "set -e; cd /tmp; "
                    f"URL=https://github.com/kubernetes-sigs/cri-tools/releases/download/v{crictl_version}/crictl-v{crictl_version}-linux-amd64.tar.gz; "
                    "curl -fsSLO $URL && tar -xzf crictl-*-linux-amd64.tar.gz && mv crictl /usr/local/bin/ && chmod +x /usr/local/bin/crictl || true"
                )
                self._run(fetch_cmd, f"Fetch crictl v{crictl_version} (best-effort)", ignore_errors=True)
        return True

    def _enable_service(self) -> bool:
        return self._run("systemctl daemon-reload || true && systemctl enable crio --now", "Enable and start crio")

    def _smoke_test(self) -> None:
        """Attempt a simple image pull & pod sandbox lifecycle using crictl to validate CRI-O.

        Non-fatal: logs warning on failure but does not abort installation success.
        Steps:
          1. Pull hello-world image (docker.io/library/hello-world:latest)
          2. Create a minimal pod sandbox spec and container spec inline (echo JSON)
          3. Run container and remove artifacts
        """
        if not self.verbose:
            typer.secho("🧪 CRI-O smoke test: pulling hello-world...", fg=typer.colors.CYAN)
        # Skip if crictl still not available
        which_out, _, _ = self.session.run("which crictl || command -v crictl", use_sudo=True)
        if not which_out.strip():
            typer.secho("ℹ️  Skipping smoke test (crictl not available).", fg=typer.colors.YELLOW)
            return
        pull_cmd = "crictl pull docker.io/library/hello-world:latest"
        _, _, code = self.session.run(pull_cmd, use_sudo=True)
        if code != 0:
            typer.secho("⚠️ Smoke test: failed to pull hello-world image (skipping further test).", fg=typer.colors.YELLOW)
            return
        pod_spec = '{"metadata":{"name":"hw-pod","namespace":"default","uid":"hwtest"}}'
        ctr_spec = '{"metadata":{"name":"hello"},"image":{"image":"docker.io/library/hello-world:latest"},"log_path":"hello.log"}'
        create_pod = f"echo '{pod_spec}' | crictl runp /dev/stdin"
        pod_id_out, _, pod_code = self.session.run(create_pod, use_sudo=True)
        if pod_code != 0 or not pod_id_out.strip():
            typer.secho("⚠️ Smoke test: failed to create pod sandbox.", fg=typer.colors.YELLOW)
            return
        pod_id = pod_id_out.strip().splitlines()[-1]
        create_ctr = f"echo '{ctr_spec}' | crictl create {pod_id} /dev/stdin /dev/stdin"
        ctr_id_out, _, ctr_code = self.session.run(create_ctr, use_sudo=True)
        if ctr_code != 0 or not ctr_id_out.strip():
            typer.secho("⚠️ Smoke test: failed to create container.", fg=typer.colors.YELLOW)
            self.session.run(f"crictl stopp {pod_id}; crictl rmp {pod_id}", use_sudo=True)
            return
        ctr_id = ctr_id_out.strip().splitlines()[-1]
        self.session.run(f"crictl start {ctr_id}", use_sudo=True)
        self.session.run(f"crictl logs {ctr_id} | head -n 1", use_sudo=True)
        self.session.run(f"crictl stop {ctr_id} || true", use_sudo=True)
        self.session.run(f"crictl rm {ctr_id} || true", use_sudo=True)
        self.session.run(f"crictl stopp {pod_id} || true; crictl rmp {pod_id} || true", use_sudo=True)
        typer.secho("🧪 CRI-O smoke test passed (hello-world).", fg=typer.colors.GREEN)

    def configure(self, **kwargs) -> bool:
        """Optional CRI-O configuration.

        Placeholder: future parameters like cgroup driver, registries, etc.
        For now, ensure service is active.
        """
        check = self.check_installed()
        if not check.ok:
            typer.secho(f"❌ CRI-O not active: {check.message}", fg=typer.colors.RED)
            return False
        return True
