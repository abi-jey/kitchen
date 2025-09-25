"""
Handlers package

Contains component-specific handlers for Kubernetes node setup and configuration.

Each handler is an object taking an `SSHSession` and exposing:
 - check_installed(): bool
 - check_config(): bool
 - install(): bool
"""

from .base import BaseComponentHandler  # re-export for convenience

__all__ = ["BaseComponentHandler"]
