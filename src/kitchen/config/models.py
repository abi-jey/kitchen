"""
Configuration models for Kitchen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass(slots=True)
class MasterNodeConfig:
    """Configuration for the master node.

    Attributes:
        hostname: The hostname of the master node.
        ips: A list of IP addresses for the master node (e.g., Tailscale, LAN).
        kubernetes_version: Desired Kubernetes version (e.g., "1.29"). Optional; latest stable if None.
    """

    hostname: str
    ips: List[str] = field(default_factory=list)
    kubernetes_version: Optional[str] = None


@dataclass(slots=True)
class ClusterSecrets:
    """Secrets associated with a cluster; stored locally per cluster in a separate file.

    Attributes:
        tailscale_auth_key: Auth key used for `tailscale up` on nodes.
        discovery_token_ca_cert_hash: kubeadm discovery token CA cert hash (sha256:...).
        kubeadm_token: Optional kubeadm bootstrap token (token[:].tokenid). Not required for all flows.
    """

    tailscale_auth_key: Optional[str] = None
    discovery_token_ca_cert_hash: Optional[str] = None
    kubeadm_token: Optional[str] = None
