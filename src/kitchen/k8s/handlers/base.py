"""
Base interface for component handlers.

A component handler encapsulates installation and configuration checks for a specific
Kubernetes node component (e.g., Tailscale, CRI-O, kubelet/kubeadm, certificates).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

from kitchen.ssh import SSHSession


@dataclass(slots=True)
class CheckOutcome:
    """Structured result for a check operation."""

    ok: bool
    message: str


class BaseComponentHandler(ABC):
    """
        Abstract base for all component handlers.

        Contract:
            - `check_installed()`: verify binaries/services exist; return `CheckOutcome`.
            - `check_config()`: verify configuration state; return `CheckOutcome`.
            - `install()`: perform installation/configuration steps; return bool success.
            - `configure(**kwargs)`: apply component-specific configuration; return bool success.
    """

    def __init__(self, session: SSHSession, verbose: bool = False):
        self.session = session
        self.verbose = verbose

    @abstractmethod
    def check_installed(self) -> CheckOutcome:
        """Check whether the component is installed and reachable."""

    @abstractmethod
    def check_config(self) -> CheckOutcome:
        """Check whether the component is correctly configured."""

    @abstractmethod
    def install(self) -> bool:
        """Install and configure the component. Returns True on success."""

    @abstractmethod
    def configure(self, **kwargs) -> bool:
        """Apply configuration for the component. Keyword arguments are component-specific."""
