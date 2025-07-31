"""
Kubernetes cluster management utilities.
This module provides functionality for managing Kubernetes clusters,
particularly focused on node addition and cluster status verification.
"""

import subprocess
from logging import getLogger
from typing import Dict, Optional, Tuple, Union

import typer

from kitchen.k8s.nodes.pre_check import MasterNodePreChecks
from kitchen.ssh import SSHSession

logger = getLogger(__name__)


# Type aliases for better code clarity
NodeStatus = Dict[str, Union[bool, int, str, None]]  # Master node status

# Typer app definitions
k8s_app = typer.Typer(help="Kubernetes cluster management commands")
nodes_app = typer.Typer(help="Kubernetes node management")

# Add nodes subcommand to k8s app
k8s_app.add_typer(nodes_app, name="nodes")


def run_local_command(cmd: str, verbose: bool = False) -> Tuple[int, str, str]:
    """Run a command locally, showing output in real-time."""
    if verbose:
        typer.secho(f"Running local command: {cmd}", fg=typer.colors.YELLOW)

    try:
        # Using shell=True to handle pipes and other shell features
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)  # Increased timeout
        if verbose:
            if result.stdout:
                typer.secho("Output:", fg=typer.colors.GREEN)
                typer.echo(result.stdout)
            if result.stderr:
                typer.secho("Error:", fg=typer.colors.RED)
                typer.echo(result.stderr)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"
    except Exception as e:
        return 1, "", str(e)


@nodes_app.command("add")
def add_node(
    master: Optional[str] = typer.Option(None, "--master", "-m", help="Master node IP or hostname"),
    user: str = "root",
    ssh_key: Optional[str] = None,
    localhost: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    """Add a new node to the Kubernetes cluster."""
    typer.echo("🚀 Starting node addition process...")

    if not master:
        typer.secho("❌ Master node IP or hostname is required. Use --master option.", fg=typer.colors.RED)
        raise typer.Exit(1)

    if localhost:
        typer.echo("📍 Target node: localhost (this machine)")

    try:
        with SSHSession(user, master) as ssh:
            # Step 1: Run pre-flight checks
            typer.echo("\n📋 Step 1: Pre-flight checks on master node")
            pre_checks = MasterNodePreChecks(ssh, verbose=verbose)

            typer.secho("The following checks will be performed on the master node:", bold=True)
            for item in pre_checks.get_check_plan():
                typer.echo(f"  - {item}")

            if not dry_run and not typer.confirm("\nDo you want to proceed with these checks?"):
                raise typer.Abort()

            if not pre_checks.run_checks():
                typer.secho("\n❌ Pre-flight checks failed. Cannot proceed.", fg=typer.colors.RED)
                raise typer.Exit(1)

            typer.secho("\n✅ Pre-flight checks passed successfully.", fg=typer.colors.GREEN)

            # Step 2: Generate join command
            typer.echo("\n🔑 Step 2: Generate join command from master")
            join_command_gen_cmd = "kubeadm token create --print-join-command"

            if dry_run:
                typer.echo("🔍 DRY RUN: Would run this command on master:")
                typer.echo(f"  - {join_command_gen_cmd}")
                typer.echo("\n🔍 DRY RUN: Would then run join command on localhost")
                typer.echo("  - Install prerequisites (docker, kubeadm, kubectl)")
                typer.echo("  - Configure system settings")
                typer.echo("  - Execute kubeadm join command")
                typer.echo("  - Verify node joined successfully")
                typer.echo("\n✅ DRY RUN completed - no actual changes made")
                return

            join_command = ""
            typer.secho(f"Running on master '{master}': {join_command_gen_cmd}", fg=typer.colors.YELLOW)
            join_command_output = ssh.run(join_command_gen_cmd)

            typer.secho("[REMOTE OUTPUT]", fg=typer.colors.CYAN)
            typer.echo(join_command_output)
            typer.secho("[END REMOTE OUTPUT]", fg=typer.colors.CYAN)

            for line in join_command_output.splitlines():
                if "kubeadm join" in line:
                    join_command = line.strip()
                    break

            if not join_command:
                typer.secho("❌ Failed to get join command from master.", fg=typer.colors.RED)
                raise typer.Exit(1)

            typer.secho("✅ Got join command:", fg=typer.colors.GREEN)
            typer.echo(join_command)

            # Step 3: Prepare localhost for joining
            if localhost:
                typer.echo("\n🔧 Step 3: Prepare localhost for joining cluster")

                local_prep_commands = [
                    "sudo apt-get update",
                    "sudo apt-get install -y docker.io",
                    "sudo systemctl enable docker --now",
                    "curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -",
                    'echo "deb https://apt.kubernetes.io/ kubernetes-xenial main" | sudo tee /etc/apt/sources.list.d/kubernetes.list',  # fmt: skip
                    "sudo apt-get update",
                    "sudo apt-get install -y kubelet kubeadm kubectl",
                    "sudo apt-mark hold kubelet kubeadm kubectl",
                    "sudo systemctl enable kubelet --now",
                ]

                for cmd_str in local_prep_commands:
                    typer.secho(f"🔧 Running local command: {cmd_str}", fg=typer.colors.YELLOW)
                    returncode, stdout, stderr = run_local_command(cmd_str, verbose)
                    if returncode != 0:
                        typer.secho(f"❌ Command failed: {cmd_str}", fg=typer.colors.RED)
                        if stdout:
                            typer.echo(stdout)
                        if stderr:
                            typer.echo(stderr)
                        raise typer.Exit(1)
                    typer.secho("✅ Success", fg=typer.colors.GREEN)

                # Step 4: Join the cluster
                typer.echo("\n🔗 Step 4: Join the cluster")
                join_cmd_with_sudo = f"sudo {join_command}"
                typer.secho(f"🔧 Running local command: {join_cmd_with_sudo}", fg=typer.colors.YELLOW)

                returncode, stdout, stderr = run_local_command(join_cmd_with_sudo, verbose)
                if returncode != 0:
                    typer.secho("❌ Join failed:", fg=typer.colors.RED)
                    if stdout:
                        typer.echo(stdout)
                    if stderr:
                        typer.echo(stderr)
                    raise typer.Exit(1)

                typer.secho("✅ Successfully joined cluster!", fg=typer.colors.GREEN)
                typer.echo(stdout)

                # Step 5: Verify node joined
                typer.echo("\n✅ Step 5: Verify node joined successfully")
                typer.secho("Checking nodes on master...", fg=typer.colors.YELLOW)
                nodes = ssh.run("kubectl get nodes -o wide")
                typer.secho("🎉 Node addition completed successfully!", fg=typer.colors.GREEN)
                typer.echo("📊 Current cluster nodes:")
                for line in nodes.split("\n"):
                    if line.strip():
                        typer.echo(f"   {line}")

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
        typer.echo(f"📋 Listing nodes from master: {master}")
        try:
            with SSHSession(user, master) as ssh:
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
