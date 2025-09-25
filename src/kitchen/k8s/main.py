"""
Kubernetes cluster management utilities.
This module focuses on node-oriented operations (check, prepare) and config management.
"""

from logging import getLogger
from typing import Dict, Optional, Tuple, Union, List
import getpass

import typer

from kitchen.k8s.master import MasterNode
from kitchen.k8s.nodes.pre_check import MasterNodePreChecks
from kitchen.k8s.nodes.worker_pre_check import WorkerNodePreChecks
from kitchen.k8s.worker import WorkerNode
from kitchen.ssh import SSHSession
from kitchen.config import ConfigManager, MasterNodeConfig
from kitchen.config.models import ClusterSecrets
import yaml
from kitchen.k8s.handlers.tailscale import TailscaleHandler
from kitchen.k8s.handlers.crio import CrioHandler
from kitchen.k8s.handlers.kubernetes_components import KubernetesComponentsHandler
from kitchen.k8s.handlers.kube_apiserver_cert import KubeAPIServerCertHandler

logger = getLogger(__name__)


def _parse_host_string(host_string: str, user_override: Optional[str] = None) -> Tuple[str, str]:
    """Parses a host string which can be in the format 'user@host' or just 'host'."""
    if user_override:
        return user_override, host_string
    if "@" in host_string:
        user, host = host_string.split("@", 1)
        return user, host
    # Fallback for localhost or if user is expected to be handled by ssh config
    return getpass.getuser() or "root", host_string  # Sensible default to current user


# Removed local shell runner; cluster-wide commands are out of scope for node-centric CLI.


# Type aliases for better code clarity
NodeStatus = Dict[str, Union[bool, int, str, None]]  # Master node status

# Typer app definitions
k8s_app = typer.Typer(help="Kubernetes cluster management commands")
node_app = typer.Typer(help="Manage a single Kubernetes node (check, prepare).")
k8s_config_app = typer.Typer(
    help=(
        "Manage Kitchen k8s configs stored under ~/.kube/kitchen/config/<cluster>/master.yaml "
        "(with legacy fallback)."
    )
)
k8s_app.add_typer(node_app, name="node")
k8s_app.add_typer(k8s_config_app, name="config")


@k8s_config_app.command(
    "init",
    # fmt: skip
    help=(
        "Create or update master config. Default location is legacy ~/.kube/kitchen/master.yaml; "
        "use --cluster to save under ~/.kube/kitchen/config/<cluster>/master.yaml. "
        "Accepts multiple --ip flags or a comma-separated list. Merges by default; use --overwrite to replace."
    ),
)
def config_init(
    hostname: str = typer.Option(..., "--hostname", help="Master node hostname"),
    ip: list[str] = typer.Option(
        [],
        "--ip",
        help="Master node IP(s); repeat --ip or pass comma-separated list",
    ),
    version: str | None = typer.Option(None, "--version", help="Desired Kubernetes version (e.g., 1.29)"),
    cluster: str | None = typer.Option(None, "--cluster", help="Cluster name for namespaced config"),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Overwrite existing file instead of merging fields"
    ),
) -> None:
    # Accept both repeated --ip flags and comma-separated lists
    normalized_ips: list[str] = []
    for v in ip:
        parts = [p.strip() for p in v.split(",")]
        normalized_ips.extend([p for p in parts if p])

    cfg = MasterNodeConfig(hostname=hostname, ips=normalized_ips, kubernetes_version=version)
    ok, msg = ConfigManager.save_master_config(cfg, cluster=cluster, overwrite=overwrite, merge=not overwrite)
    if ok:
        typer.secho(f"✅ {msg}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"❌ {msg}", fg=typer.colors.RED)


@k8s_config_app.command(
    "set-secrets",
    help=(
        "Save cluster secrets (stored locally) such as tailscale auth key and kubeadm discovery hash. "
        "If --cluster is omitted, uses the default cluster."
    ),
)
def config_set_secrets(
    tailscale_auth_key: str | None = typer.Option(None, "--tailscale-auth-key", help="Tailscale auth key"),
    discovery_token_ca_cert_hash: str | None = typer.Option(
        None, "--discovery-hash", help="kubeadm discovery-token-ca-cert-hash (sha256:...)"
    ),
    kubeadm_token: str | None = typer.Option(None, "--kubeadm-token", help="kubeadm bootstrap token (optional)"),
    cluster: str | None = typer.Option(None, "--cluster", help="Cluster name"),
) -> None:
    secrets = ClusterSecrets(
        tailscale_auth_key=tailscale_auth_key,
        discovery_token_ca_cert_hash=discovery_token_ca_cert_hash,
        kubeadm_token=kubeadm_token,
    )
    ok, msg = ConfigManager.save_cluster_secrets(secrets, cluster=cluster, overwrite=False, merge=True)
    if ok:
        typer.secho(f"✅ {msg}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"❌ {msg}", fg=typer.colors.RED)


@k8s_config_app.command(
    "show-secrets",
    help=(
        "Show which secrets are set for the cluster (redacts values). If --cluster omitted, uses default cluster."
    ),
)
def config_show_secrets(cluster: str | None = typer.Option(None, "--cluster", help="Cluster name")) -> None:
    secrets, msg = ConfigManager.load_cluster_secrets(cluster=cluster)
    if secrets is None:
        typer.secho(f"❌ {msg}", fg=typer.colors.RED)
        raise typer.Exit(1)
    def red(v: str | None) -> str:
        if not v:
            return "<unset>"
        if len(v) <= 8:
            return "********"
        return v[:4] + "********" + v[-4:]
    typer.secho("🔐 Cluster Secrets:", fg=typer.colors.CYAN)
    typer.echo(f"  tailscale_auth_key: {red(secrets.tailscale_auth_key)}")
    typer.echo(f"  discovery_token_ca_cert_hash: {red(secrets.discovery_token_ca_cert_hash)}")
    typer.echo(f"  kubeadm_token: {red(secrets.kubeadm_token)}")


@k8s_config_app.command(
    "show",
    # fmt: skip
    help=(
        "Show master config. Precedence: 1) --cluster -> ~/.kube/kitchen/config/<cluster>/master.yaml, "
        "2) default cluster (if set)."
    ),
)
def config_show(
    cluster: str | None = typer.Option(None, "--cluster", help="Cluster name"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug details"),
) -> None:
    path, eff_cluster, err = ConfigManager.resolve_config_path(cluster)
    if verbose:
        if path is not None:
            typer.secho(f"🔎 Resolved config path: {path}", fg=typer.colors.CYAN)
            if eff_cluster:
                typer.secho(f"   Effective cluster: {eff_cluster}", fg=typer.colors.CYAN)
        else:
            typer.secho(f"❌ {err}", fg=typer.colors.RED)
    cfg, msg = ConfigManager.load_master_config(cluster=cluster)
    if not cfg:
        typer.secho(f"❌ {msg}", fg=typer.colors.RED)
        raise typer.Exit(1)
    # Summary output
    typer.secho("📄 Master Config (summary):", fg=typer.colors.CYAN)
    typer.echo(f"  Hostname: {cfg.hostname}")
    if cfg.ips:
        for a in cfg.ips:
            typer.echo(f"  IP: {a}")
    else:
        typer.echo("  IPs: []")
    typer.echo(f"  Kubernetes Version: {cfg.kubernetes_version or 'latest stable'}")

    # Also print available configs
    clusters = ConfigManager.list_clusters()
    default_name, _ = ConfigManager.get_default_cluster()
    if clusters:
        typer.secho("\n📚 Available cluster configs:", fg=typer.colors.CYAN)
        for c in clusters:
            marker = " (default)" if default_name and c == default_name else ""
            typer.echo(f"  - {c}{marker}")

    # Print YAML representation
    typer.secho("\n🧾 YAML:", fg=typer.colors.CYAN)
    # fmt: skip
    typer.echo(yaml.safe_dump({
        "hostname": cfg.hostname,
        "ips": cfg.ips,
        "kubernetes_version": cfg.kubernetes_version
    }, sort_keys=False).rstrip())


@k8s_config_app.command(
    "list",
    help="List clusters with configs under ~/.kube/kitchen/config/ and mark the default (if set)",
)
def config_list() -> None:
    clusters = ConfigManager.list_clusters()
    default_name, _ = ConfigManager.get_default_cluster()
    if not clusters:
        typer.secho("ℹ️  No cluster configs found.", fg=typer.colors.YELLOW)
        return
    typer.secho("📚 Clusters:", fg=typer.colors.CYAN)
    for c in clusters:
        marker = " (default)" if default_name and c == default_name else ""
        typer.echo(f"  - {c}{marker}")


@k8s_config_app.command(
    "set-default",
    help=(
        "Set the default cluster name (stored in ~/.kube/kitchen/config/default). "
        "Used when --cluster is omitted."
    ),
)
def config_set_default(cluster: str = typer.Option(..., "--cluster", help="Cluster name")) -> None:
    if not cluster.strip():
        typer.secho("❌ Cluster name cannot be empty.", fg=typer.colors.RED)
        raise typer.Exit(1)
    ok, msg = ConfigManager.set_default_cluster(cluster.strip())
    if ok:
        typer.secho(f"✅ {msg}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"❌ {msg}", fg=typer.colors.RED)


@k8s_config_app.command(
    "default",
    help="Show the current default cluster name (from ~/.kube/kitchen/config/default)",
)
def config_default() -> None:
    name, msg = ConfigManager.get_default_cluster()
    if name:
        typer.secho("⭐ Default cluster:", fg=typer.colors.CYAN)
        typer.echo(f"  {name}")
    else:
        typer.secho(f"ℹ️  {msg}", fg=typer.colors.YELLOW)


PHASE_ALIASES: dict[str, str] = {
    "crio": "container-runtime",
    "kubernetes": "kube-components",
    "apiserver": "apiserver-cert",
    "cert": "apiserver-cert",
}

ROLE_DEFAULTS: dict[str, list[str]] = {
    "master": ["tailscale", "container-runtime", "kube-components", "apiserver-cert"],
    "worker": ["tailscale", "container-runtime", "kube-components"],
}

VALID_PHASES = {"tailscale", "container-runtime", "kube-components", "apiserver-cert"}


def _normalize_phases(raw: List[str] | None) -> List[str]:
    if not raw:
        return []
    collected: list[str] = []
    for entry in raw:
        if not entry:
            continue
        for token in entry.split(","):
            t = token.strip().lower()
            if not t:
                continue
            mapped = PHASE_ALIASES.get(t, t)
            collected.append(mapped)
    dedup: list[str] = []
    seen: set[str] = set()
    for p in collected:
        if p not in seen:
            seen.add(p)
            dedup.append(p)
    return dedup


def _resolve_default_phases(role: str, requested: List[str]) -> List[str]:
    if requested:
        return requested
    return ROLE_DEFAULTS[role][:]


@node_app.command("check", help="Run pre-flight checks on a node. Can target one or multiple component phases.")
def node_check(
    role: str = typer.Option(..., "--role", help="'master' or 'worker'"),
    host: str = typer.Option(..., "--host", help="The user@host for the node"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
    ssh_key_path: str = typer.Option(None, "--ssh-key", help="Path to the SSH private key."),
    user: Optional[str] = typer.Option(None, "--user", help="SSH user (overrides user@host)"),
    phases: List[str] = typer.Option(
        None,
        "--phases",
        help=(
            "Repeatable. Accepts comma-separated values. Defaults per role if omitted. "
            "Valid: tailscale,container-runtime,kube-components,apiserver-cert (master only)."
        ),
    ),
):
    if role not in {"master", "worker"}:
        typer.secho("❌ --role must be 'master' or 'worker'", fg=typer.colors.RED)
        raise typer.Exit(1)

    user, node_host = _parse_host_string(host, user_override=user)
    with SSHSession(user, node_host, ssh_key_path, verbose) as ssh_session:
        requested_phases = _normalize_phases(phases)
        resolved_phases = _resolve_default_phases(role, requested_phases)
        if not requested_phases:
            typer.secho(
                f"ℹ️  No phases specified. Using default phase set for role '{role}': {', '.join(resolved_phases)}",
                fg=typer.colors.CYAN,
            )

        if resolved_phases:
            overall_ok = True
            for ph in resolved_phases:
                handler_result = False
                if ph == "tailscale":
                    handler = TailscaleHandler(ssh_session, verbose)
                    inst = handler.check_installed()
                    cfg = handler.check_config()
                    handler_result = inst.ok and cfg.ok
                    _print_phase("tailscale", inst.message, cfg.message, inst.ok, cfg.ok)
                elif ph == "container-runtime":
                    cfg_loaded, _ = ConfigManager.load_master_config()
                    kver = cfg_loaded.kubernetes_version if cfg_loaded and cfg_loaded.kubernetes_version else None
                    handler = CrioHandler(ssh_session, verbose, kubernetes_version=kver)
                    inst = handler.check_installed()
                    cfg = handler.check_config()
                    handler_result = inst.ok and cfg.ok
                    _print_phase("container-runtime", inst.message, cfg.message, inst.ok, cfg.ok, extra=(f"k8s_ver={kver}" if kver else None))
                elif ph == "kube-components":
                    cfg_loaded, _ = ConfigManager.load_master_config()
                    kver = cfg_loaded.kubernetes_version if cfg_loaded and cfg_loaded.kubernetes_version else None
                    handler = KubernetesComponentsHandler(ssh_session, verbose, kubernetes_version=kver)
                    inst = handler.check_installed()
                    cfg = handler.check_config()
                    handler_result = inst.ok and cfg.ok
                    _print_phase("kube-components", inst.message, cfg.message, inst.ok, cfg.ok, extra=(f"k8s_ver={kver}" if kver else None))
                elif ph == "apiserver-cert":
                    if role != "master":
                        typer.secho("❌ apiserver-cert phase only valid for master role.", fg=typer.colors.RED)
                        overall_ok = False
                        break
                    ts_ip_stdout, _, _ = ssh_session.run("tailscale ip -4", use_sudo=True)
                    ts_ip = ts_ip_stdout.strip().splitlines()[-1] if ts_ip_stdout.strip() else ""
                    cert_handler = KubeAPIServerCertHandler(ssh_session, verbose, required_ip=ts_ip or None)
                    inst = cert_handler.check_installed()
                    cfg = cert_handler.check_config()
                    handler_result = inst.ok and cfg.ok
                    _print_phase("apiserver-cert", inst.message, cfg.message, inst.ok, cfg.ok, extra=f"ip={ts_ip or 'n/a'}")
                else:
                    typer.secho(f"❌ Unknown phase specified: {ph}", fg=typer.colors.RED)
                    overall_ok = False
                    break

                if not handler_result:
                    overall_ok = False
                    if not verbose and ssh_session.last_output:
                        typer.secho("🛈 Remote output (last command):", fg=typer.colors.CYAN)
                        typer.echo(ssh_session.last_output)
                else:
                    typer.secho(f"✅ Phase '{ph}' checks passed.", fg=typer.colors.GREEN)

            if overall_ok:
                typer.secho("🎯 All phase checks passed.", fg=typer.colors.GREEN)
                raise typer.Exit(0)
            else:
                typer.secho("❌ One or more requested phase checks failed.", fg=typer.colors.RED)
                raise typer.Exit(1)
            
            return

        # Full legacy pre-check set when no specific phase
        if role == "master":
            typer.secho(f"📋 Running pre-flight checks on master node {host}...", fg=typer.colors.BLUE)
            pre_checks = MasterNodePreChecks(ssh_session, verbose)
            ok = pre_checks.run_checks()
        else:
            typer.secho(f"📋 Running pre-flight checks on worker node {host}...", fg=typer.colors.BLUE)
            pre_checks = WorkerNodePreChecks(ssh_session, verbose)
            ok = pre_checks.run_checks()
        if ok:
            typer.secho("✅ All checks passed.", fg=typer.colors.GREEN)
        else:
            typer.secho("❌ Some checks failed.", fg=typer.colors.RED)


def _print_phase(name: str, inst_msg: str, cfg_msg: str, inst_ok: bool, cfg_ok: bool, extra: str | None = None) -> None:
    status = "OK" if inst_ok else "FAIL"
    typer.secho(f"🔍 [{name}] installed check: {status} - {inst_msg}", fg=typer.colors.GREEN if inst_ok else typer.colors.RED)
    status_cfg = "OK" if cfg_ok else "FAIL"
    typer.secho(
        f"   [{name}] config check: {status_cfg} - {cfg_msg}" + (f" ({extra})" if extra else ""),
        fg=typer.colors.GREEN if cfg_ok else typer.colors.RED,
    )


def _phase_prepare(handler, name: str, extra: str | None = None) -> None:
    """Install + configure a specific component handler.

    Sequence:
      1. check_installed; if missing -> install()
      2. check_config; if not ok -> configure(); re-check
    """
    inst = handler.check_installed()
    if not inst.ok:
        typer.secho(f"🛠️  Installing {name}...", fg=typer.colors.YELLOW)
        if not handler.install():
            typer.secho(f"❌ Failed to install {name}.", fg=typer.colors.RED)
            return
        inst = handler.check_installed()
    cfg = handler.check_config()
    if not cfg.ok:
        typer.secho(f"🔧 Configuring {name}...", fg=typer.colors.YELLOW)
        if not handler.configure():
            typer.secho(f"❌ Failed to configure {name}.", fg=typer.colors.RED)
            _print_phase(name, inst.message, cfg.message, inst.ok, cfg.ok, extra=extra)
            return
        cfg = handler.check_config()
    _print_phase(name, inst.message, cfg.message, inst.ok, cfg.ok, extra=extra)
    if inst.ok and cfg.ok:
        typer.secho(f"✅ {name} ready.", fg=typer.colors.GREEN)


def _choose_master_endpoint(cfg: MasterNodeConfig) -> str:
    """Pick an endpoint for kubeadm join.

    Prefer a Tailscale-looking IP (100.x), else first IP, else hostname.
    """
    for ip in cfg.ips or []:
        if ip.startswith("100."):
            return f"{ip}:6443"
    if cfg.ips:
        return f"{cfg.ips[0]}:6443"
    return f"{cfg.hostname}:6443"


def _candidate_endpoints(cfg: MasterNodeConfig) -> list[str]:
    """Return a prioritized list of candidate API endpoints with :6443 appended.

    Order: Tailscale (100.x) IPs first, then remaining IPs, then hostname.
    """
    tailscale = [ip for ip in (cfg.ips or []) if ip.startswith("100.")]
    others = [ip for ip in (cfg.ips or []) if not ip.startswith("100.")]
    candidates = [f"{ip}:6443" for ip in tailscale + others]
    if cfg.hostname:
        candidates.append(f"{cfg.hostname}:6443")
    # Deduplicate preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


@node_app.command("prepare", help=(
    "Prepare a node by running installs/config for component phases. "
    "Use --phases (repeatable/comma-separated). Defaults per role if omitted."))
def node_prepare(
    role: str = typer.Option(..., "--role", help="'master' or 'worker'"),
    host: str = typer.Option(..., "--host", help="The user@host for the node"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
    ssh_key_path: str = typer.Option(None, "--ssh-key", help="Path to the SSH private key."),
    user: Optional[str] = typer.Option(None, "--user", help="SSH user (overrides user@host)"),
    phases: List[str] = typer.Option(
        None,
        "--phases",
        help=(
            "Repeatable. Accepts comma-separated values. Defaults per role if omitted. "
            "Valid: tailscale,container-runtime,kube-components,apiserver-cert (master only)."
        ),
    ),
):
    if role not in {"master", "worker"}:
        typer.secho("❌ --role must be 'master' or 'worker'", fg=typer.colors.RED)
        raise typer.Exit(1)

    user, node_host = _parse_host_string(host, user_override=user)
    with SSHSession(user, node_host, ssh_key_path, verbose) as ssh_session:
        requested_phases = _normalize_phases(phases)
        resolved_phases = _resolve_default_phases(role, requested_phases)
        if not requested_phases:
            typer.secho(
                f"ℹ️  No phases specified. Using default phase set for role '{role}': {', '.join(resolved_phases)}",
                fg=typer.colors.CYAN,
            )
        if resolved_phases:
            total = len(resolved_phases)
            for idx, ph in enumerate(resolved_phases, start=1):
                typer.secho(f"▶️  Phase {idx}/{total}: {ph}", fg=typer.colors.BLUE)
                if ph == "tailscale":
                    handler = TailscaleHandler(ssh_session, verbose)
                    _phase_prepare(handler, name="tailscale")
                    ts_ip_out, _, _ = ssh_session.run("tailscale ip -4", use_sudo=True)
                    ip_line = ts_ip_out.strip().splitlines()[-1] if ts_ip_out.strip() else None
                    if ip_line:
                        typer.secho(f"🌐 Tailscale IPv4: {ip_line}", fg=typer.colors.CYAN)
                elif ph == "container-runtime":
                    cfg_loaded, _ = ConfigManager.load_master_config()
                    kver = cfg_loaded.kubernetes_version if cfg_loaded and cfg_loaded.kubernetes_version else None
                    handler = CrioHandler(ssh_session, verbose, kubernetes_version=kver)
                    _phase_prepare(handler, name="container-runtime", extra=(f"k8s_ver={kver}" if kver else None))
                elif ph == "kube-components":
                    cfg_loaded, _ = ConfigManager.load_master_config()
                    kver = cfg_loaded.kubernetes_version if cfg_loaded and cfg_loaded.kubernetes_version else None
                    handler = KubernetesComponentsHandler(ssh_session, verbose, kubernetes_version=kver)
                    _phase_prepare(handler, name="kube-components", extra=(f"k8s_ver={kver}" if kver else None))
                elif ph == "apiserver-cert":
                    if role != "master":
                        typer.secho("❌ apiserver-cert phase only valid for master role.", fg=typer.colors.RED)
                        raise typer.Exit(1)
                    ts_ip_stdout, _, _ = ssh_session.run("tailscale ip -4", use_sudo=True)
                    ts_ip = ts_ip_stdout.strip().splitlines()[-1] if ts_ip_stdout.strip() else ""
                    handler = KubeAPIServerCertHandler(ssh_session, verbose, required_ip=ts_ip or None)
                    _phase_prepare(handler, name="apiserver-cert", extra=f"ip={ts_ip or 'n/a'}")
                else:
                    typer.secho(f"❌ Unknown phase specified: {ph}", fg=typer.colors.RED)
                    raise typer.Exit(1)

                # If a phase failed (non-zero exit code remembered by SSHSession), abort sequence
                if ssh_session.exit_code is not None and ssh_session.exit_code != 0:
                    if ssh_session.last_output:
                        typer.secho("🛈 Remote output (last command):", fg=typer.colors.CYAN)
                        typer.echo(ssh_session.last_output)
                    typer.secho(f"❌ Phase '{ph}' failed. Aborting remaining phases.", fg=typer.colors.RED)
                    raise typer.Exit(1)
            typer.secho("🎯 All phases prepared successfully.", fg=typer.colors.GREEN)
            return

        # Fallback to legacy full flow
        if role == "master":
            _setup_master_node(host, verbose, ssh_key_path)
        else:
            _setup_worker_node(host, verbose, ssh_key_path)


def _setup_master_node(master: str, verbose: bool, ssh_key_path: Optional[str]):
    user, host = master.split("@")  # Ensure consistent indentation

    typer.secho(f"🚀 Starting master node setup for {master}...", fg=typer.colors.BLUE)
    # The new SSHSession handles sudo per-command, so elevate_privileges is removed.
    with SSHSession(user, host, ssh_key_path, verbose) as ssh_session:
        typer.secho("\n📋 Running pre-flight checks on master node...", fg=typer.colors.BLUE)
        pre_checks = MasterNodePreChecks(ssh_session, verbose)
        all_passed_initially = pre_checks.run_checks()

        # If SANs check failed, offer to fix it.
        sans_check_passed, _ = pre_checks.results.get("Verify Tailscale IP in kube-apiserver SANs", (False, ""))
        if not sans_check_passed and pre_checks.tailscale_ip:
            typer.secho(
                "\n⚠️ The Tailscale IP is not present in the kube-apiserver certificate SANs.", fg=typer.colors.YELLOW
            )
            if typer.confirm("Do you want to proceed with this automatic fix?"):
                master_node = MasterNode(ssh_session, verbose)
                fix_successful = master_node.fix_apiserver_sans(pre_checks.tailscale_ip)

                if fix_successful:
                    # Re-run all checks to get a final, clean bill of health
                    typer.secho("\n🔄 Re-running all checks after applying fix...", fg=typer.colors.BLUE)
                    all_passed_finally = pre_checks.run_checks()
                    if all_passed_finally:
                        typer.secho("✅ All pre-flight checks now pass.", fg=typer.colors.GREEN)
                        if pre_checks.tailscale_ip:
                            master_node = MasterNode(ssh_session, verbose)
                            stdout, _, code = master_node.get_join_command(pre_checks.tailscale_ip)
                            if code == 0:
                                typer.secho(
                                    "\n🎉 Setup complete! Use this command to join worker nodes:",
                                    fg=typer.colors.BRIGHT_GREEN,
                                )
                                typer.secho(f"\n    {stdout}\n", fg=typer.colors.WHITE, bold=True)
                            else:
                                typer.secho(
                                    "\n❌ Failed to generate join command.",
                                    fg=typer.colors.RED,
                                )
                                raise typer.Exit(1)
                        else:
                            typer.secho(
                                "\n❌ Could not retrieve Tailscale IP. Cannot generate join command.",
                                fg=typer.colors.RED,
                            )
                            raise typer.Exit(1)
                    else:
                        typer.secho(
                            "\n❌ Some checks still failed after the fix. Please review the output.",
                            fg=typer.colors.RED,
                        )
                        raise typer.Exit(1)
                else:
                    typer.secho("\n❌ Failed to apply the fix. Aborting.", fg=typer.colors.RED)
                    raise typer.Exit(1)

        elif all_passed_initially:
            typer.secho("✅ All pre-flight checks passed. Master node is ready.", fg=typer.colors.GREEN)
            if pre_checks.tailscale_ip:
                master_node = MasterNode(ssh_session, verbose)
                stdout, _, code = master_node.get_join_command(pre_checks.tailscale_ip)
                if code == 0:
                    typer.secho("\n🎉 Setup complete! Use this command to join worker nodes:", fg=typer.colors.BRIGHT_GREEN)
                    typer.secho(f"\n    {stdout}\n", fg=typer.colors.WHITE, bold=True)
                else:
                    typer.secho(
                        "\n❌ Failed to generate join command.",
                        fg=typer.colors.RED,
                    )
                    raise typer.Exit(1)
            else:
                typer.secho(
                    "\n❌ Could not retrieve Tailscale IP. Cannot generate join command.",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
        else:
            typer.secho("\n❌ Some pre-flight checks failed. Please review the output above.", fg=typer.colors.RED)
            raise typer.Exit(1)


def _setup_worker_node(worker: str, verbose: bool, ssh_key_path: Optional[str]):
    """
    Connects to a worker node, runs pre-flight checks, and offers to install missing components.
    """
    user, host = worker.split("@")  # Ensure consistent indentation

    typer.secho(f"🚀 Starting worker node setup for {worker}...", fg=typer.colors.BLUE)

    # Step 1: Initial connection and dry-run checks without elevation
    typer.secho("\n📋 Performing initial dry-run checks...", fg=typer.colors.BLUE)
    with SSHSession(user, host, ssh_key_path, verbose) as ssh_session:
        pre_checks = WorkerNodePreChecks(ssh_session, verbose)
        initial_checks_passed = pre_checks.run_checks(use_sudo=False)

    if initial_checks_passed:
        typer.secho("\n✅ All worker node checks passed. Node is ready to join.", fg=typer.colors.GREEN)
        typer.secho(
            "Use the join command from the 'k8s node prepare --role master --host <user@host>' output.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(0)

    # Step 2: Analyze failures and propose an installation plan
    typer.secho("\n⚠️ Some pre-flight checks failed. Analyzing required installations...", fg=typer.colors.YELLOW)
    install_plan = []
    if not pre_checks.results.get("Check for CRI-O service", (False, ""))[0]:
        install_plan.append("Install CRI-O container runtime")
    if not pre_checks.results.get("Verify kubeadm installation", (False, ""))[0]:
        install_plan.append("Install Kubernetes components (kubelet, kubeadm)")
    if not pre_checks.results.get("Check for Tailscale service", (False, ""))[0]:
        install_plan.append("Install and start Tailscale")
    # The kubelet service might be installed but not running, which is a failure.
    # If it's not running, we should try to install/re-install components.
    if not pre_checks.results.get("Check for kubelet service", (False, ""))[0]:
        # This is a bit of a catch-all. If kubelet isn't running, it's often because
        # of a dependency issue (like CRI-O not being ready). We'll ensure the main
        # components are on the plan.
        if "Install Kubernetes components (kubelet, kubeadm)" not in install_plan:
            install_plan.append("Install Kubernetes components (kubelet, kubeadm)")

    if not install_plan:
        typer.secho("\n❌ Checks failed, but no clear installation path. Please check the node manually.", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho("\nProposed installation plan:", fg=typer.colors.CYAN)
    for item in install_plan:
        typer.secho(f"  - {item}", fg=typer.colors.CYAN)

    # Step 3: Get user confirmation and run installations
    if not typer.confirm("\nDo you want to proceed with these installations?"):
        typer.secho("Aborting.", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho("\n🔧 Proceeding with installation. This will require root privileges.", fg=typer.colors.BLUE)
    with SSHSession(user, host, ssh_key_path, verbose) as elevated_session:
        worker_node = WorkerNode(elevated_session, verbose)
        success = True
        if "Install CRI-O container runtime" in install_plan:
            if not worker_node.install_crio():
                success = False
        if "Install Kubernetes components (kubelet, kubeadm)" in install_plan:
            if not worker_node.install_kubernetes_components():
                success = False
        if "Install and start Tailscale" in install_plan:
            if not worker_node.install_and_start_tailscale():
                success = False

        if not success:
            typer.secho("\n❌ Installation failed. Please review the output above.", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Step 4: Final verification
        typer.secho("\n🔄 Re-running checks to verify installation...", fg=typer.colors.BLUE)
        final_checks = WorkerNodePreChecks(elevated_session, verbose)
        if final_checks.run_checks(use_sudo=True):
            typer.secho("\n✅ Worker node setup complete. It is now ready to join the cluster.", fg=typer.colors.GREEN)
        else:
            typer.secho("\n❌ Some checks still failed after installation. Please review the output.", fg=typer.colors.RED)
            raise typer.Exit(1)


@node_app.command("add", help="Add a new node to the cluster (join flow; WIP).")
def node_add(
    ctx: typer.Context,
    master: str = typer.Option(..., "--master", "-m", help="Master node IP or hostname (user@host)"),
    target: str = typer.Option(
        "localhost",
        "--target",
        "-t",
        help="Target node to add. Can be 'localhost' or a remote 'user@host' string.",
    ),
    user: Optional[str] = typer.Option(None, help="Override user for master or target. Do not use with user@host."),
    ssh_key: Optional[str] = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    """Add a new node to the Kubernetes cluster."""
    typer.echo("🚀 Starting node addition process...")

    # Validate that user is not provided with user@host format
    if user and ("@" in master or "@" in target):
        typer.secho(
            "❌ Do not use the --user flag when specifying user@host in --master or --target.", fg=typer.colors.RED
        )
        raise typer.Exit(1)

    master_user, master_host = _parse_host_string(master, user)
    target_user, target_host = _parse_host_string(target, user)

    if target_host == "localhost":
        typer.echo("📍 Target node: localhost (this machine)")
    else:
        typer.echo(f"📍 Target node: {target_user}@{target_host}")

    try:
        # For add, we don't need to elevate privileges on the master initially
        with SSHSession(master_user, master_host, ssh_key_path=ssh_key, verbose=verbose) as ssh:
            typer.secho(f"📋 Running pre-flight checks on master node ({master_host})...", fg=typer.colors.BLUE)
            pre_checks = MasterNodePreChecks(ssh, verbose)
            if not pre_checks.run_checks():
                typer.secho(
                    "\n❌ Pre-flight checks failed on the master node.",
                    fg=typer.colors.RED,
                )
                typer.secho(
                    "Please run 'kitchen k8s node check --role master --host <user@host>' to diagnose and fix the issues.",
                    fg=typer.colors.YELLOW,
                )
                raise typer.Exit(1)

            typer.secho("✅ Pre-flight checks passed on master node.", fg=typer.colors.GREEN)
            # TODO: Implement the logic to add the new node, now that the master is verified.
            typer.secho("\n🚧 Node joining logic not yet implemented.", fg=typer.colors.YELLOW)

    except typer.Abort:
        typer.echo("Aborted.")
    except Exception as e:
        logger.error(f"An error occurred during the node addition process: {e}")
        typer.secho(f"❌ An error occurred: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)


"""Re-architecture: removed 'k8s nodes list'."""


"""Re-architecture: removed 'k8s status'."""


@node_app.command(
    "join",
    help=(
        "Join a worker node to the cluster using saved cluster config and secrets. "
        "Ensures required phases (tailscale, container-runtime, kube-components) and runs kubeadm join. "
        "Creates a JoinConfiguration on the worker and prefers the Tailscale IP for kubelet node-ip."
    ),
)
def node_join(
    host: str = typer.Option(..., "--host", help="Target worker user@host for join"),
    cluster: str | None = typer.Option(None, "--cluster", help="Cluster name (uses default if omitted)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
    ssh_key_path: str | None = typer.Option(None, "--ssh-key", help="Path to SSH private key."),
    user: Optional[str] = typer.Option(None, "--user", help="SSH user (overrides user@host)"),
    skip_prepare: bool = typer.Option(False, "--skip-prepare", help="Skip pre-join phases (use if already prepared)."),
    endpoint: str | None = typer.Option(
        None,
        "--endpoint",
        help=(
            "Override API endpoint for join (host[:port]). If omitted, you'll be prompted to choose among candidates."
        ),
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help=(
            "Do not prompt for endpoint; auto-select based on config (prefers Tailscale)."
        ),
    ),
    node_ip: str | None = typer.Option(
        None,
        "--node-ip",
        help=(
            "Set node-ip explicitly (overrides autodetected Tailscale IP)."
        ),
    ),
    use_tailscale_node_ip: bool = typer.Option(False, "--use-tailscale-node-ip", help=(
        "Derive node-ip from 'tailscale ip -4' on the worker (default behavior).")),
    taint: List[str] = typer.Option(
        None,
        "--taint",
        help=(
            "Repeatable taint spec key[=value]:Effect (e.g., dedicated=ml:NoSchedule). Added to nodeRegistration.taints."
        ),
    ),
    # node role labeling intentionally omitted per kubeadm guidance; apply labels post-join via kubectl
) -> None:
    # Load config and secrets
    cfg, msg = ConfigManager.load_master_config(cluster=cluster)
    if not cfg:
        typer.secho(f"❌ {msg}", fg=typer.colors.RED)
        raise typer.Exit(1)
    secrets, smsg = ConfigManager.load_cluster_secrets(cluster=cluster)
    if not secrets:
        typer.secho(f"❌ {smsg}", fg=typer.colors.RED)
        raise typer.Exit(1)

    if not secrets.discovery_token_ca_cert_hash:
        typer.secho(
            "❌ Missing discovery token CA cert hash. Set with: kitchen k8s config set-secrets --discovery-hash sha256:...",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if not secrets.kubeadm_token:
        typer.secho(
            "❌ Missing kubeadm token. Set with: kitchen k8s config set-secrets --kubeadm-token <token>",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # Determine endpoint: explicit, interactive choice, or auto
    if endpoint:
        if ":" not in endpoint:
            endpoint = f"{endpoint}:6443"
    else:
        candidates = _candidate_endpoints(cfg)
        if not candidates:
            endpoint = _choose_master_endpoint(cfg)
        elif len(candidates) == 1 or non_interactive:
            endpoint = candidates[0]
            if non_interactive:
                typer.secho(f"ℹ️  Using API endpoint: {endpoint}", fg=typer.colors.CYAN)
        else:
            typer.secho("📡 Select API endpoint to join:", fg=typer.colors.CYAN)
            for i, c in enumerate(candidates, start=1):
                typer.echo(f"  {i}) {c}")
            choice_raw = typer.prompt("Enter choice number", default="1")
            try:
                idx = int(choice_raw)
                if not (1 <= idx <= len(candidates)):
                    raise ValueError
            except Exception:
                typer.secho("⚠️  Invalid choice; defaulting to 1.", fg=typer.colors.YELLOW)
                idx = 1
            endpoint = candidates[idx - 1]
    user, node_host = _parse_host_string(host, user_override=user)

    with SSHSession(user, node_host, ssh_key_path, verbose) as ssh_session:
        # Optionally prepare required phases
        if not skip_prepare:
            # tailscale: try to install/configure using auth key if provided
            ts = TailscaleHandler(ssh_session, verbose)
            inst = ts.check_installed()
            if not inst.ok:
                typer.secho("🛠️  Installing tailscale...", fg=typer.colors.YELLOW)
                if not ts.install():
                    typer.secho("❌ Failed to install tailscale.", fg=typer.colors.RED)
                    raise typer.Exit(1)
            cfg_ok = ts.check_config()
            if not cfg_ok.ok:
                typer.secho("🔧 Configuring tailscale...", fg=typer.colors.YELLOW)
                _ = ts.configure(auth_key=secrets.tailscale_auth_key)
                cfg_ok = ts.check_config()
            if not cfg_ok.ok:
                typer.secho(f"❌ tailscale not ready: {cfg_ok.message}", fg=typer.colors.RED)
                raise typer.Exit(1)

            # container runtime (CRIO)
            kver = cfg.kubernetes_version
            crio = CrioHandler(ssh_session, verbose, kubernetes_version=kver)
            _phase_prepare(crio, name="container-runtime", extra=(f"k8s_ver={kver}" if kver else None))
            if ssh_session.exit_code is not None and ssh_session.exit_code != 0:
                if ssh_session.last_output:
                    typer.secho("🛈 Remote output (last command):", fg=typer.colors.CYAN)
                    typer.echo(ssh_session.last_output)
                typer.secho("❌ container-runtime preparation failed.", fg=typer.colors.RED)
                raise typer.Exit(1)

            # kube components
            kube = KubernetesComponentsHandler(ssh_session, verbose, kubernetes_version=kver)
            _phase_prepare(kube, name="kube-components", extra=(f"k8s_ver={kver}" if kver else None))
            if ssh_session.exit_code is not None and ssh_session.exit_code != 0:
                if ssh_session.last_output:
                    typer.secho("🛈 Remote output (last command):", fg=typer.colors.CYAN)
                    typer.echo(ssh_session.last_output)
                typer.secho("❌ kube-components preparation failed.", fg=typer.colors.RED)
                raise typer.Exit(1)

        # Determine node-ip (prefer Tailscale) and build JoinConfiguration file on worker
        node_ip_effective: str | None = node_ip.strip() if node_ip else None
        if not node_ip_effective:
            # Default: use Tailscale IP unless user explicitly disables via not passing the flag and not wanting TS
            ts_ip_out, _, _ = ssh_session.run("tailscale ip -4", use_sudo=True)
            ts_ip = ts_ip_out.strip().splitlines()[-1] if ts_ip_out.strip() else ""
            if ts_ip:
                node_ip_effective = ts_ip
            elif use_tailscale_node_ip:
                typer.secho("⚠️  Could not determine Tailscale IP on worker; proceeding without node-ip.", fg=typer.colors.YELLOW)

        cri_socket = "unix:///var/run/crio/crio.sock"
        join_yaml_path = "/tmp/kitchen-join.yaml"
        # fmt: skip
        join_yaml = (
            "apiVersion: kubeadm.k8s.io/v1beta4\n"
            "kind: JoinConfiguration\n"
            "discovery:\n"
            "  bootstrapToken:\n"
            f"    token: {secrets.kubeadm_token}\n"
            f"    apiServerEndpoint: {endpoint}\n"
            "    caCertHashes:\n"
            f"      - {secrets.discovery_token_ca_cert_hash}\n"
            "nodeRegistration:\n"
            f"  criSocket: {cri_socket}\n"
        )
        # Build kubeletExtraArgs entries
        extra_args_entries: list[str] = []
        if node_ip_effective:
            extra_args_entries.append("    - name: node-ip\n" + f"      value: {node_ip_effective}\n")
        if extra_args_entries:
            join_yaml += (
                "  kubeletExtraArgs:\n"
                + "".join(extra_args_entries)
            )
        # Parse taints
        taints_yaml: list[str] = []
        if taint:
            for spec in taint:
                s = spec.strip()
                if not s:
                    continue
                # Expect form key[=value]:Effect
                if ":" not in s:
                    typer.secho(f"⚠️  Ignoring invalid taint (missing ':'): {s}", fg=typer.colors.YELLOW)
                    continue
                kv, effect = s.rsplit(":", 1)
                key = kv
                value = None
                if "=" in kv:
                    key, value = kv.split("=", 1)
                key = key.strip()
                effect = effect.strip()
                if not key or not effect:
                    typer.secho(f"⚠️  Ignoring invalid taint: {s}", fg=typer.colors.YELLOW)
                    continue
                item = [f"    - key: {key}\n", f"      effect: {effect}\n"]
                if value is not None and value != "":
                    item.append(f"      value: {value}\n")
                taints_yaml.append("".join(item))
        if taints_yaml:
            join_yaml += "  taints:\n" + "".join(taints_yaml)
        write_join = (
            "set -e; "
            f"cat > {join_yaml_path} <<'EOF'\n{join_yaml}EOF\n"
        )
        _, stderr, code = ssh_session.run(write_join, use_sudo=True)
        if code != 0:
            typer.secho(f"❌ Failed to write JoinConfiguration. STDERR: {stderr}", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Run kubeadm join with config file
        typer.secho(f"🚀 Running kubeadm join to {endpoint} (via --config)...", fg=typer.colors.BLUE)
        join_cmd = f"kubeadm join --config {join_yaml_path}"
        stdout, stderr, code = ssh_session.run(join_cmd, use_sudo=True)
        if code != 0:
            typer.secho("❌ kubeadm join failed.", fg=typer.colors.RED)
            if stdout:
                typer.secho("STDOUT:", fg=typer.colors.YELLOW)
                typer.echo(stdout)
            if stderr:
                typer.secho("STDERR:", fg=typer.colors.YELLOW)
                typer.echo(stderr)
            raise typer.Exit(1)

        # Post-join verification
        kube = KubernetesComponentsHandler(ssh_session, verbose)
        check = kube.check_config()
        if not check.ok:
            typer.secho(f"⚠️  kubelet not active after join: {check.message}", fg=typer.colors.YELLOW)
        else:
            typer.secho("✅ Node joined successfully and kubelet is active.", fg=typer.colors.GREEN)
