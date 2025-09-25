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

    def install_and_start_tailscale(self) -> bool:
        """
        Installs and starts the Tailscale service using the official install script
        and prompts the user for an auth key to bring the service up.
        """
        typer.secho("🔧 Installing and starting Tailscale...", fg=typer.colors.YELLOW)

        # Use the official Tailscale installation script
        install_cmd = "curl -fsSL https://tailscale.com/install.sh | sh"
        stdout, stderr, code = self.session.run(install_cmd, use_sudo=True)
        if code != 0:
            typer.secho(
                f"❌ Failed to install Tailscale using install.sh. STDERR: {stderr}", fg=typer.colors.RED
            )
            return False
        typer.secho("✅ Tailscale installed successfully via install.sh.", fg=typer.colors.GREEN)

        # Prompt user for the auth key
        auth_key = typer.prompt("🔑 Please enter your Tailscale auth key", hide_input=True)
        if not auth_key:
            typer.secho("❌ No auth key provided. Cannot bring Tailscale up.", fg=typer.colors.RED)
            return False

        # Activate Tailscale with the provided auth key
        activate_cmd = f"tailscale up --authkey={auth_key}"
        stdout, stderr, code = self.session.run(activate_cmd, use_sudo=True)
        if code != 0:
            typer.secho(f"❌ Failed to bring Tailscale up. STDERR: {stderr}", fg=typer.colors.RED)
            # Also print stdout for more context, as tailscale sometimes prints errors there
            if stdout:
                typer.secho(f"   STDOUT: {stdout}", fg=typer.colors.YELLOW)
            return False

        typer.secho("✅ Tailscale is now up and running.", fg=typer.colors.GREEN)
        return True

    def install_kubernetes_components(self) -> bool:
        """
        Installs the latest stable version of kubeadm, kubelet, and kubectl.
        """
        typer.secho(
            "🔧 Installing latest stable Kubernetes components (kubeadm, kubelet)...",
            fg=typer.colors.YELLOW,
        )
        install_cmd = r"""
set -e
apt-get update
apt-get install -y apt-transport-https ca-certificates curl gnupg

# Ensure keyrings directory exists
mkdir -p /etc/apt/keyrings

# Fetch the latest stable Kubernetes version string (e.g., v1.29.0)
K8S_LATEST_STABLE_VERSION=$(curl -L -s https://dl.k8s.io/release/stable.txt)

# Extract the minor version from it (e.g., v1.29)
K8S_MINOR_VERSION=$(echo "$K8S_LATEST_STABLE_VERSION" | cut -d. -f1,2)

echo "Found latest stable Kubernetes version: ${K8S_LATEST_STABLE_VERSION}, using repository for ${K8S_MINOR_VERSION}"

# Download the public signing key for the Kubernetes package repositories.
curl -fsSL "https://pkgs.k8s.io/core:/stable:/${K8S_MINOR_VERSION}/deb/Release.key" \
    | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
chmod 0644 /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# Add the appropriate Kubernetes apt repository.
cat >/etc/apt/sources.list.d/kubernetes.list <<EOF
deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_MINOR_VERSION}/deb/ /
EOF

# Remove any invalid Kubic CRI-O lists that could break apt-get update
rm -f /etc/apt/sources.list.d/devel:kubic:libcontainers:stable:cri-o:*.list || true

# Update the apt package index, install kubelet, kubeadm and kubectl, and pin their version.
apt-get update
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl
"""
        stdout, stderr, code = self.session.run(install_cmd, use_sudo=True)
        if code != 0:
            typer.secho(f"❌ Failed to install Kubernetes components. STDERR: {stderr}", fg=typer.colors.RED)
            return False
        typer.secho("✅ Kubernetes components installed.", fg=typer.colors.GREEN)
        return True

    def install_crio(self) -> bool:
        """
        Installs and configures the CRI-O container runtime.
        """
        typer.secho("🔧 Installing CRI-O container runtime...", fg=typer.colors.YELLOW)

        # Build a robust shell script that:
        # - Detects OS (Ubuntu/Debian) and constructs correct Kubic repo path
        # - Aligns CRI-O minor version with latest stable Kubernetes minor
        # - Validates repo existence and falls back to older minors if needed
        # - Cleans up any invalid Kubic repo files left from previous attempts
        # fmt: skip
        crio_cmd = r"""
set -e
modprobe overlay
modprobe br_netfilter

cat <<EOF | tee /etc/sysctl.d/99-kubernetes-cri.conf
net.bridge.bridge-nf-call-iptables  = 1
net.ipv4.ip_forward                 = 1
net.bridge.bridge-nf-call-ip6tables = 1
EOF

sysctl --system

# Fetch the latest stable Kubernetes version to align CRI-O version
K8S_LATEST_STABLE_VERSION=$(curl -L -s https://dl.k8s.io/release/stable.txt)
CRIO_VERSION=$(echo "$K8S_LATEST_STABLE_VERSION" | cut -d. -f1,2 | sed 's/v//')

echo "Aligning CRI-O with latest stable Kubernetes version: ${CRIO_VERSION}"

# Detect OS release string expected by Kubic repos (xUbuntu_YY.MM or Debian_MM)
. /etc/os-release
OS_RELEASE=""
if [ "${ID}" = "ubuntu" ]; then
    # Use full version for Ubuntu (e.g., 24.04)
    OS_RELEASE="xUbuntu_${VERSION_ID}"
elif [ "${ID}" = "debian" ]; then
    # Kubic expects full major (e.g., Debian_12)
    OS_RELEASE="Debian_${VERSION_ID%%.*}"
else
    echo "Unsupported OS ID: ${ID}. Only Ubuntu/Debian are supported." >&2
    exit 1
fi

# Clean up old/invalid Kubic list files from previous attempts to avoid apt failures
rm -f \
    /etc/apt/sources.list.d/devel:kubic:libcontainers:stable.list \
    /etc/apt/sources.list.d/devel:kubic:libcontainers:stable:cri-o:*.list || true

mkdir -p /usr/share/keyrings

# Base repo (libcontainers stable)
LIBCONTAINERS_KEY_URL="https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/${OS_RELEASE}/Release.key"
LIBCONTAINERS_KEYRING="/usr/share/keyrings/libcontainers-archive-keyring.gpg"
LIBCONTAINERS_LIST="/etc/apt/sources.list.d/devel:kubic:libcontainers:stable.list"

# Candidate CRI-O minors to try: align to K8s minor, then decrement up to 2 more if not found
CRIO_MINOR_CANDIDATES=("${CRIO_VERSION}")
for i in 1 2; do
    MAJOR=${CRIO_VERSION%%.*}
    MINOR=${CRIO_VERSION#*.}
    MINOR=$((MINOR - i))
    if [ ${MINOR} -ge 0 ]; then
        CRIO_MINOR_CANDIDATES+=("${MAJOR}.${MINOR}")
    fi
done

# Resolve a working CRI-O repo version for this OS
RESOLVED_CRIO_MINOR=""
for CANDIDATE in "${CRIO_MINOR_CANDIDATES[@]}"; do
    CAND_KEY_URL="https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable:/cri-o:/${CANDIDATE}/${OS_RELEASE}/Release.key"
    if curl -fsI "${CAND_KEY_URL}" >/dev/null 2>&1; then
        RESOLVED_CRIO_MINOR="${CANDIDATE}"
        break
    fi
done

if [ -z "${RESOLVED_CRIO_MINOR}" ]; then
    echo "Failed to locate a valid CRI-O repo for OS=${OS_RELEASE} aligned with K8s minor=${CRIO_VERSION}" >&2
    echo "Tried: ${CRIO_MINOR_CANDIDATES[*]}" >&2
    exit 1
fi

CRIO_KEY_URL="https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable:/cri-o:/${RESOLVED_CRIO_MINOR}/${OS_RELEASE}/Release.key"
CRIO_KEYRING="/usr/share/keyrings/libcontainers-crio-archive-keyring.gpg"
CRIO_LIST="/etc/apt/sources.list.d/devel:kubic:libcontainers:stable:cri-o:${RESOLVED_CRIO_MINOR}.list"

echo "Using CRI-O minor stream: ${RESOLVED_CRIO_MINOR} for OS ${OS_RELEASE}"

curl -fsSL "${LIBCONTAINERS_KEY_URL}" | gpg --dearmor -o "${LIBCONTAINERS_KEYRING}"
curl -fsSL "${CRIO_KEY_URL}" | gpg --dearmor -o "${CRIO_KEYRING}"

echo "deb [signed-by=${LIBCONTAINERS_KEYRING}] https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/${OS_RELEASE}/ /" \
    | tee "${LIBCONTAINERS_LIST}" >/dev/null
echo "deb [signed-by=${CRIO_KEYRING}] https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable:/cri-o:/${RESOLVED_CRIO_MINOR}/${OS_RELEASE}/ /" \
    | tee "${CRIO_LIST}" >/dev/null

apt-get update
apt-get install -y cri-o cri-o-runc

systemctl daemon-reload
systemctl enable crio --now
"""
        stdout, stderr, code = self.session.run(crio_cmd, use_sudo=True)
        if code != 0:
            typer.secho(f"❌ Failed to install CRI-O. STDERR: {stderr}", fg=typer.colors.RED)
            return False
        typer.secho("✅ CRI-O installed and started.", fg=typer.colors.GREEN)
        return True
