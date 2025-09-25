"""Config manager for reading and writing Kitchen configs under ~/.kube/kitchen/.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import List, Tuple

import typer
import yaml

from .models import MasterNodeConfig, ClusterSecrets


KITCHEN_BASE_DIR = Path.home() / ".kube" / "kitchen"
CONFIG_ROOT_DIR = KITCHEN_BASE_DIR / "config"
DEFAULT_FILE = CONFIG_ROOT_DIR / "default"
LEGACY_MASTER_CONFIG_FILE = KITCHEN_BASE_DIR / "master.yaml"
SECRETS_FILE_NAME = "secrets.yaml"


class ConfigManager:
    """Helper for loading and saving Kitchen configuration files."""

    _CLUSTER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{0,62}$")

    @staticmethod
    def validate_cluster_name(cluster: str) -> Tuple[bool, str]:
        """Validate a cluster name is safe for filesystem use.

        Rules:
          - lowercase letters, digits, hyphen, underscore
          - 1-63 characters
          - must not contain path separators or sequences like '..'
        """
        if not cluster:
            return False, "Cluster name cannot be empty"
        if "/" in cluster or "\\" in cluster or ".." in cluster:
            return False, "Cluster name must not contain path separators or '..'"
        if not ConfigManager._CLUSTER_NAME_RE.match(cluster):
            return False, "Invalid cluster name: use lowercase a-z, 0-9, '-', '_' (1-63 chars)"
        return True, "OK"

    @staticmethod
    def ensure_dir(path: Path = KITCHEN_BASE_DIR) -> None:
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_cluster_dir(cluster: str) -> Path:
        return CONFIG_ROOT_DIR / cluster

    @staticmethod
    def get_master_config_file(cluster: str) -> Path:
        return ConfigManager.get_cluster_dir(cluster) / "master.yaml"

    @staticmethod
    def get_cluster_secrets_file(cluster: str) -> Path:
        return ConfigManager.get_cluster_dir(cluster) / SECRETS_FILE_NAME

    @staticmethod
    def list_clusters() -> List[str]:
        if not CONFIG_ROOT_DIR.exists():
            return []
        clusters: List[str] = []
        for child in CONFIG_ROOT_DIR.iterdir():
            if child.is_dir() and (child / "master.yaml").exists():
                ok, _ = ConfigManager.validate_cluster_name(child.name)
                if ok:
                    clusters.append(child.name)
        clusters.sort()
        return clusters

    @staticmethod
    def get_default_cluster() -> Tuple[str | None, str]:
        """Read the default cluster name from the default file."""
        try:
            if not DEFAULT_FILE.exists():
                return None, "No default cluster set"
            name = DEFAULT_FILE.read_text(encoding="utf-8").strip()
            return (name if name else None), ("OK" if name else "Default file empty")
        except Exception as e:
            return None, f"Failed to read default: {e}"

    @staticmethod
    def set_default_cluster(cluster: str) -> Tuple[bool, str]:
        """Set the default cluster name (ensures cluster dir exists)."""
        try:
            ok, msg = ConfigManager.validate_cluster_name(cluster)
            if not ok:
                return False, msg
            # Ensure config root exists
            ConfigManager.ensure_dir(CONFIG_ROOT_DIR)
            # Optionally ensure the cluster directory exists
            (CONFIG_ROOT_DIR / cluster).mkdir(parents=True, exist_ok=True)
            DEFAULT_FILE.write_text(cluster + "\n", encoding="utf-8")
            return True, f"Default cluster set to '{cluster}'"
        except Exception as e:
            return False, f"Failed to set default: {e}"

    @staticmethod
    def load_master_config(cluster: str | None = None) -> Tuple[MasterNodeConfig | None, str]:
        """Load master config.

        Priority:
          1) If cluster provided, load ~/.kube/kitchen/config/<cluster>/master.yaml
          2) Else, if default file exists, load that cluster
        """
        cfg_path, _, err = ConfigManager.resolve_config_path(cluster)
        if cfg_path is None:
            return None, err

        if not cfg_path.exists():
            return None, f"Config not found at {cfg_path}"

        try:
            with cfg_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            hostname = data.get("hostname", "")
            ips = list(map(str, data.get("ips", [])))
            version = data.get("kubernetes_version")
            if not hostname:
                return None, "Missing 'hostname' in config"
            return MasterNodeConfig(hostname=hostname, ips=ips, kubernetes_version=version), "OK"
        except Exception as e:
            return None, f"Failed to read config: {e}"

    @staticmethod
    def load_cluster_secrets(cluster: str | None = None) -> Tuple[ClusterSecrets | None, str]:
        """Load secrets for a cluster from secrets.yaml in the cluster directory (or default cluster).

        Returns (ClusterSecrets|None, message)
        """
        cfg_path, eff_cluster, err = ConfigManager.resolve_config_path(cluster)
        if cfg_path is None or eff_cluster is None:
            return None, err
        secrets_path = ConfigManager.get_cluster_secrets_file(eff_cluster)
        if not secrets_path.exists():
            return ClusterSecrets(), "OK (no secrets file; returning empty)"
        try:
            with secrets_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return ClusterSecrets(
                tailscale_auth_key=data.get("tailscale_auth_key"),
                discovery_token_ca_cert_hash=data.get("discovery_token_ca_cert_hash"),
                kubeadm_token=data.get("kubeadm_token"),
            ), "OK"
        except Exception as e:
            return None, f"Failed to read secrets: {e}"

    @staticmethod
    def resolve_config_path(cluster: str | None = None) -> Tuple[Path | None, str | None, str]:
        """Resolve the config path and effective cluster.

        Returns (path|None, effective_cluster|None, message).
        """
        if cluster:
            ok, msg = ConfigManager.validate_cluster_name(cluster)
            if not ok:
                return None, None, msg
            path = ConfigManager.get_master_config_file(cluster)
            return path, cluster, "OK"
        default_cluster, _ = ConfigManager.get_default_cluster()
        if default_cluster:
            path = ConfigManager.get_master_config_file(default_cluster)
            return path, default_cluster, "OK"
        return None, None, "No cluster specified and no default set"

    @staticmethod
    def save_master_config(
        cfg: MasterNodeConfig,
        cluster: str | None = None,
        overwrite: bool = False,
        merge: bool = True,
    ) -> Tuple[bool, str]:
        """Persist master config.

        If `cluster` is provided, saves under ~/.kube/kitchen/config/<cluster>/master.yaml.
        Otherwise writes legacy ~/.kube/kitchen/master.yaml for backward compatibility.
        """
        try:
            if cluster:
                ok, msg = ConfigManager.validate_cluster_name(cluster)
                if not ok:
                    return False, msg
                cluster_dir = ConfigManager.get_cluster_dir(cluster)
                ConfigManager.ensure_dir(cluster_dir)
                path = ConfigManager.get_master_config_file(cluster)
            else:
                ConfigManager.ensure_dir(KITCHEN_BASE_DIR)
                path = LEGACY_MASTER_CONFIG_FILE

            final_data = asdict(cfg)

            if path.exists() and not overwrite and merge:
                with path.open("r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
                # merge semantics: replace hostname/version if provided; union ips
                if cfg.hostname:
                    existing["hostname"] = cfg.hostname
                if cfg.kubernetes_version is not None:
                    existing["kubernetes_version"] = cfg.kubernetes_version
                old_ips = set(map(str, existing.get("ips", []) or []))
                new_ips = set(cfg.ips or [])
                existing["ips"] = sorted(old_ips.union(new_ips))
                final_data = existing

            # fmt: skip
            with path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(final_data, f, sort_keys=False)
            return True, f"Saved: {path}"
        except Exception as e:
            return False, f"Failed to save config: {e}"

    @staticmethod
    def save_cluster_secrets(
        secrets: ClusterSecrets,
        cluster: str | None = None,
        overwrite: bool = True,
        merge: bool = True,
    ) -> Tuple[bool, str]:
        """Persist cluster secrets to ~/.kube/kitchen/config/<cluster>/secrets.yaml.

        - Ensures directory exists.
        - Writes with mode 0600 for local safety.
        - If merge and file exists, merges non-empty fields.
        """
        try:
            cfg_path, eff_cluster, err = ConfigManager.resolve_config_path(cluster)
            if cfg_path is None and not eff_cluster:
                return False, err
            if not eff_cluster:
                return False, "No cluster specified and no default set"
            ok, msg = ConfigManager.validate_cluster_name(eff_cluster)
            if not ok:
                return False, msg
            cluster_dir = ConfigManager.get_cluster_dir(eff_cluster)
            ConfigManager.ensure_dir(cluster_dir)
            path = ConfigManager.get_cluster_secrets_file(eff_cluster)

            new_data = {
                "tailscale_auth_key": secrets.tailscale_auth_key,
                "discovery_token_ca_cert_hash": secrets.discovery_token_ca_cert_hash,
                "kubeadm_token": secrets.kubeadm_token,
            }

            if path.exists() and merge and not overwrite:
                with path.open("r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
                for k, v in new_data.items():
                    if v is not None and v != "":
                        existing[k] = v
                new_data = existing

            # Write file and set 0600 perms
            with path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(new_data, f, sort_keys=False)
            os.chmod(path, 0o600)
            return True, f"Saved: {path}"
        except Exception as e:
            return False, f"Failed to save secrets: {e}"
