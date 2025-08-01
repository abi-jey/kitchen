"""
Kubernetes cluster management utilities.
This module provides functionality for managing Kubernetes clusters,
particularly focused on node addition and cluster status verification.
"""

import subprocess
from logging import getLogger
from typing import Dict, Optional, Tuple, Union

import typer

from kitchen.k8s.master import MasterNode
from kitchen.k8s.nodes.pre_check import MasterNodePreChecks
from kitchen.k8s.nodes.worker_pre_check import WorkerNodePreChecks
from kitchen.k8s.worker import WorkerNode
from kitchen.ssh import SSHSession

logger = getLogger(__name__)


# Type aliases for better code clarity
NodeStatus = Dict[str, Union[bool, int, str, None]]  # Master node status

# Typer app definitions
k8s_app = typer.Typer(help="Kubernetes cluster management commands")
nodes_app = typer.Typer(help="Manage Kubernetes nodes.")
k8s_app.add_typer(nodes_app, name="nodes")


@nodes_app.command("setup", help="Prepare a master or worker node.")
def setup_node(
    ctx: typer.Context,
    master: str = typer.Option(None, "--master", help="The user@host for the master node."),
    worker: str = typer.Option(None, "--worker", help="The user@host for the worker node."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
    ssh_key_path: str = typer.Option(None, "--ssh-key", help="Path to the SSH private key."),
):
    """
    Connects to a node, runs pre-flight checks, and offers to install missing components.
    """
    # Update context with local options if provided
    ctx.ensure_object(dict)
    if verbose:
        ctx.obj["verbose"] = verbose
    if ssh_key_path:
        ctx.obj["ssh_key_path"] = ssh_key_path

    if not (master or worker) or (master and worker):
        typer.secho("Please specify either --master or --worker, but not both.", fg=typer.colors.RED)
        raise typer.Exit(1)

    if master:
        _setup_master_node(ctx, master)
    elif worker:
        _setup_worker_node(ctx, worker)


def _setup_master_node(ctx: typer.Context, master: str):
    verbose = ctx.obj.get("verbose", False)
    user, host = master.split("@")
    ssh_key_path = ctx.obj.get("ssh_key_path")

    typer.secho(f"🚀 Starting master node setup for {master}...", fg=typer.colors.BLUE)
    # Always elevate privileges for setup
    with SSHSession(user, host, ssh_key_path, verbose, elevate_privileges=True) as ssh_session:
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
                            join_command = master_node.get_join_command(pre_checks.tailscale_ip)
                            typer.secho(
                                "\n🎉 Setup complete! Use this command to join worker nodes:",
                                fg=typer.colors.BRIGHT_GREEN,
                            )
                            typer.secho(f"\n    {join_command}\n", fg=typer.colors.WHITE, bold=True)
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
                join_command = master_node.get_join_command(pre_checks.tailscale_ip)
                typer.secho("\n🎉 Setup complete! Use this command to join worker nodes:", fg=typer.colors.BRIGHT_GREEN)
                typer.secho(f"\n    {join_command}\n", fg=typer.colors.WHITE, bold=True)
            else:
                typer.secho(
                    "\n❌ Could not retrieve Tailscale IP. Cannot generate join command.",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
        else:
            typer.secho("\n❌ Some pre-flight checks failed. Please review the output above.", fg=typer.colors.RED)
            raise typer.Exit(1)


def _setup_worker_node(ctx: typer.Context, worker: str):
    """
    Connects to a worker node, runs pre-flight checks, and offers to install missing components.
    """
    verbose = ctx.obj.get("verbose", False)
    user, host = worker.split("@")
    ssh_key_path = ctx.obj.get("ssh_key_path")

    typer.secho(f"🚀 Starting worker node setup for {worker}...", fg=typer.colors.BLUE)

    # Step 1: Initial connection and dry-run checks without elevation
    typer.secho("\n📋 Performing initial dry-run checks...", fg=typer.colors.BLUE)
    with SSHSession(user, host, ssh_key_path, verbose) as ssh_session:
        pre_checks = WorkerNodePreChecks(ssh_session, verbose)
        initial_checks_passed = pre_checks.run_checks()

    if initial_checks_passed:
        typer.secho("\n✅ All worker node checks passed. Node is ready to join.", fg=typer.colors.GREEN)
        typer.secho("Use the join command from the 'k8s nodes setup --master' output.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    # Step 2: Analyze failures and propose an installation plan
    typer.secho("\n⚠️ Some pre-flight checks failed. Analyzing required installations...", fg=typer.colors.YELLOW)
    install_plan = []
    if not pre_checks.results.get("Check for CRI-O service", (False, ""))[0]:
        install_plan.append("Install CRI-O container runtime")
    if not pre_checks.results.get("Verify kubeadm installation", (False, ""))[0]:
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
    with SSHSession(user, host, ssh_key_path, verbose, elevate_privileges=True) as elevated_session:
        worker_node = WorkerNode(elevated_session, verbose)
        success = True
        if "Install CRI-O container runtime" in install_plan:
            if not worker_node.install_crio():
                success = False
        if "Install Kubernetes components (kubelet, kubeadm)" in install_plan:
            if not worker_node.install_kubernetes_components():
                success = False

        if not success:
            typer.secho("\n❌ Installation failed. Please review the output above.", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Step 4: Final verification
        typer.secho("\n🔄 Re-running checks to verify installation...", fg=typer.colors.BLUE)
        final_checks = WorkerNodePreChecks(elevated_session, verbose)
        if final_checks.run_checks():
            typer.secho("\n✅ Worker node setup complete. It is now ready to join the cluster.", fg=typer.colors.GREEN)
        else:
            typer.secho("\n❌ Some checks still failed after installation. Please review the output.", fg=typer.colors.RED)
            raise typer.Exit(1)


@nodes_app.command("add", help="Add a new node to the cluster.")
def add_node(
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
        with SSHSession(master_user, master_host, ssh_key_path=ssh_key, verbose=verbose, elevate_privileges=False) as ssh:
            typer.secho(f"📋 Running pre-flight checks on master node ({master_host})...", fg=typer.colors.BLUE)
            pre_checks = MasterNodePreChecks(ssh, verbose)
            if not pre_checks.run_checks():
                typer.secho(
                    "\n❌ Pre-flight checks failed on the master node.",
                    fg=typer.colors.RED,
                )
                typer.secho(
                    "Please run 'kitchen k8s nodes setup' to diagnose and fix the issues.",
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


@nodes_app.command("list")
def list_nodes(
    master: Optional[str] = None, user: str = "root", ssh_key: Optional[str] = None, verbose: bool = False
) -> None:
    """List all nodes in the Kubernetes cluster."""
    if master:
        master_user = user
        master_host = master
        if "@" in master:
            provided_user, provided_host = master.split("@", 1)
            master_host = provided_host
            if user == "root":
                master_user = provided_user

        typer.echo(f"📋 Listing nodes from master: {master_host}")
        try:
            with SSHSession(master_user, master_host) as ssh:
                typer.secho("Getting all nodes...", fg=typer.colors.YELLOW)
                nodes_wide = ssh.run("kubectl get nodes -o wide")
                typer.secho("📊 Nodes:", fg=typer.colors.GREEN)
                for line in nodes_wide.split("\n"):
                    if line.strip():
                        typer.echo(f"   {line}")

                typer.secho("\nGetting node descriptions...", fg=typer.colors.YELLOW)
                node_details = ssh.run("kubectl describe nodes | grep -E '(Name:|Roles:|Status:)'")
                typer.secho("📊 Node Details:", fg=typer.colors.GREEN)
                for line in node_details.split("\n"):
                    if line.strip():
                        typer.echo(f"   {line}")

        except Exception as e:
            logger.error(f"Failed to list nodes from master: {e}")
            typer.secho(f"❌ Failed to list nodes from master: {e}", fg=typer.colors.RED)
    else:
        typer.echo("📋 Checking local kubectl configuration...")
        exit_code, stdout, stderr = run_local_command("kubectl get nodes", verbose)

        if exit_code == 0:
            typer.echo("📊 Cluster nodes:")
            for line in stdout.split("\n"):
                if line.strip():
                    typer.echo(f"   {line}")
        else:
            typer.secho("❌ Failed to get nodes - check kubectl configuration", fg=typer.colors.RED)
            typer.echo(f"Error: {stderr}")


@k8s_app.command("status")
def cluster_status() -> None:
    """Show the status of the Kubernetes cluster."""
    typer.echo("🔍 Checking Kubernetes cluster status...")

    # Check if kubectl is available locally
    exit_code, _, stderr = run_local_command("kubectl version --client", False)

    if exit_code != 0:
        typer.secho("❌ kubectl not found or not configured", fg=typer.colors.RED)
        typer.echo("Please ensure kubectl is installed and configured to connect to your cluster")
        return

    typer.secho("✅ kubectl is available", fg=typer.colors.GREEN)

    # Get cluster info
    commands = [
        ("kubectl cluster-info", "Cluster Info"),
        ("kubectl get nodes", "Nodes"),
        ("kubectl get pods --all-namespaces", "All Pods"),
        ("kubectl get services --all-namespaces", "All Services"),
    ]

    for cmd, desc in commands:
        typer.echo(f"\n📊 {desc}:")
        exit_code, stdout, stderr = run_local_command(cmd, False)

        if exit_code == 0:
            for line in stdout.split("\n")[:10]:  # Limit output
                if line.strip():
                    typer.echo(f"   {line}")
            if len(stdout.split("\n")) > 10:
                typer.echo(f"   ... ({len(stdout.splitlines()) - 10} more lines)")
        else:
            typer.secho(f"   ❌ Failed: {stderr}", fg=typer.colors.RED)
