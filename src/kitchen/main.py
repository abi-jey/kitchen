"""Main CLI application for Kitchen."""

import typer
from typing import List, Optional
import subprocess
import sys
from kitchen.k8s.main import k8s_app
from kitchen.k8s.worker import WorkerNode
from kitchen.ssh import SSHSession
from kitchen.node_manager.cli import node_manager_app

app = typer.Typer(help="Kitchen - Your Kubernetes cookbook for cluster management")

# Add the K8s sub-commands
app.add_typer(k8s_app, name="k8s")

# Add the Node Manager sub-commands
app.add_typer(node_manager_app, name="node-manager")


@app.callback()
def main_callback(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
    ssh_key_path: str = typer.Option(None, "--ssh-key", help="Path to the SSH private key."),
):
    """
    Kitchen is a CLI tool for managing Kubernetes clusters with Tailscale integration.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["ssh_key_path"] = ssh_key_path


@app.command()
def run(
    command: str = typer.Argument(..., help="Command to run"),
    args: Optional[List[str]] = typer.Argument(None, help="Arguments for the command"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output"),
) -> None:
    """Run a command with optional arguments."""
    cmd_parts = [command]
    if args:
        cmd_parts.extend(args)
    
    if verbose:
        typer.echo(f"Running: {' '.join(cmd_parts)}")
    
    try:
        result = subprocess.run(cmd_parts, capture_output=False, text=True)
        sys.exit(result.returncode)
    except FileNotFoundError:
        typer.echo(f"Error: Command '{command}' not found", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"Error running command: {e}", err=True)
        sys.exit(1)


@app.command()
def setup() -> None:
    """Check and install required tools for Kubernetes management."""
    typer.echo("🔧 Checking Kitchen setup...")
    typer.echo("(Checks for tools needed on your local machine)")
    typer.echo()
    
    required_tools = ["kubectl", "kubeadm"]
    optional_tools = ["docker"]  # For local dev/building images
    recommended_tools = ["tailscale", "ssh", "sshpass"]
    missing_tools = []
    missing_optional = []
    missing_recommended = []
    
    # Check required tools
    for tool in required_tools:
        try:
            result = subprocess.run(
                ["which", tool], 
                capture_output=True, 
                text=True
            )
            if result.returncode == 0:
                typer.echo(f"✅ {tool} is installed")
            else:
                missing_tools.append(tool)
                typer.echo(f"❌ {tool} is not installed")
        except Exception:
            missing_tools.append(tool)
            typer.echo(f"❌ {tool} is not installed")
    
    # Check optional tools
    for tool in optional_tools:
        try:
            result = subprocess.run(
                ["which", tool], 
                capture_output=True, 
                text=True
            )
            if result.returncode == 0:
                typer.echo(f"✅ {tool} is installed (optional, for local dev)")
            else:
                missing_optional.append(tool)
                typer.echo(f"ℹ️  {tool} is not installed (optional, for local dev)")
        except Exception:
            missing_optional.append(tool)
            typer.echo(f"ℹ️  {tool} is not installed (optional, for local dev)")
    
    # Check recommended tools
    for tool in recommended_tools:
        try:
            result = subprocess.run(
                ["which", tool], 
                capture_output=True, 
                text=True
            )
            if result.returncode == 0:
                typer.echo(f"✅ {tool} is installed")
            else:
                missing_recommended.append(tool)
                typer.echo(f"⚠️  {tool} is not installed (recommended)")
        except Exception:
            missing_recommended.append(tool)
            typer.echo(f"⚠️  {tool} is not installed (recommended)")
    
    # Show results and recommendations
    if missing_tools:
        typer.echo(f"\n❌ Missing required tools: {', '.join(missing_tools)}")
        typer.echo("Please install the missing tools before using Kitchen for K8s management.")
        typer.echo("\nInstallation guides:")
        typer.echo("- kubectl: https://kubernetes.io/docs/tasks/tools/install-kubectl/")
        typer.echo("- kubeadm: https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/")  # fmt: skip
    
    if missing_optional:
        typer.echo(f"\nℹ️  Optional tools not found: {', '.join(missing_optional)}")
        typer.echo("(These are only needed for local development)")
        typer.echo("- docker: https://docs.docker.com/engine/install/ (for building node-manager images)")
    
    if missing_recommended:
        typer.echo(f"\n⚠️  Missing recommended tools: {', '.join(missing_recommended)}")
        typer.echo("Installation guides:")
        typer.echo("- tailscale: https://tailscale.com/download (for secure networking)")
        typer.echo("- ssh: Usually pre-installed, check your package manager")
        typer.echo("- sshpass: For password automation (apt install sshpass / brew install sshpass)")
    
    if not missing_tools and not missing_recommended and not missing_optional:
        typer.echo("\n🎉 All tools are installed!")
        typer.echo("Kitchen is ready for Kubernetes management.")
    elif not missing_tools:
        typer.echo("\n✅ All required tools are installed!")
        typer.echo("Kitchen is ready for Kubernetes management.")
        if missing_recommended:
            typer.echo("Install recommended tools for enhanced functionality.")
        if missing_optional:
            typer.echo("Optional tools are only needed for development work.")
    
    # Show Tailscale status if available
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"], 
            capture_output=True, 
            text=True
        )
        if result.returncode == 0:
            typer.echo("\n🔗 Tailscale Status:")
            typer.echo("✅ Tailscale is running")
            # Could parse JSON for more details if needed
        else:
            typer.echo("\n🔗 Tailscale Status:")
            typer.echo("⚠️  Tailscale is installed but not authenticated")
            typer.echo("Run 'tailscale up' to connect to your Tailnet")
    except Exception:
        pass  # Tailscale not available, already reported above
    
    # Important note about remote node setup
    typer.echo("\n💡 Note: Kitchen automatically installs CRI-O and Kubernetes components")
    typer.echo("   on remote nodes during 'kitchen k8s node prepare'. You don't need to")
    typer.echo("   pre-install these on worker nodes.")


@app.command()
def cookbook() -> None:
    """Show the Kitchen cookbook - common Kubernetes recipes."""
    typer.echo("📚 Kitchen Cookbook - Kubernetes Recipes")
    typer.echo("=" * 50)
    typer.echo()
    typer.echo("⚙️  CLUSTER CONFIGURATION:")
    typer.echo("  kitchen k8s config init --hostname master-01 --ip 192.168.1.10")
    typer.echo("  kitchen k8s config set-secrets --cluster my-cluster")
    typer.echo("  kitchen k8s config show")
    typer.echo("  kitchen k8s config list")
    typer.echo()
    typer.echo("🔍 NODE PREPARATION:")
    typer.echo("  kitchen k8s node check --role worker --host user@192.168.1.100")
    typer.echo("  kitchen k8s node prepare --role worker --host user@node-01")
    typer.echo("  (Installs CRI-O, Kubernetes components, and Tailscale)")
    typer.echo()
    typer.echo("🔗 NODE JOINING:")
    typer.echo("  kitchen k8s node join --host user@worker-node --cluster my-cluster")
    typer.echo("  kitchen k8s node join --host user@node-01 --verbose")
    typer.echo("  (Joins worker node to cluster using saved config)")
    typer.echo()
    typer.echo("🛠️  SETUP:")
    typer.echo("  kitchen setup                      - Check required tools")
    typer.echo()
    typer.echo("📦 NODE MANAGER:")
    typer.echo("  kitchen node-manager deploy        - Deploy node manager")
    typer.echo("  kitchen node-manager status        - Check status")
    typer.echo("  kitchen node-manager logs --follow - View logs")
    typer.echo()
    typer.echo("📋 PLANNED FEATURES:")
    typer.echo("  kitchen k8s node add               - Complete interactive workflow")
    typer.echo("  kitchen k8s node remove <name>     - Remove a node")
    typer.echo("  kitchen k8s cluster init           - Initialize new cluster")
    typer.echo("  kitchen k8s backup/restore         - Backup and restore")
    typer.echo()
    typer.echo("💡 EXAMPLES:")
    typer.echo("  # Prepare a worker node with all components")
    typer.echo("  kitchen k8s node prepare --role worker --host ubuntu@192.168.1.100 \\")
    typer.echo("    --phases tailscale,container-runtime,kube-components")
    typer.echo()
    typer.echo("  # Join worker with Tailscale")
    typer.echo("  kitchen k8s node join --host user@worker-01 \\")
    typer.echo("    --cluster production --use-tailscale-node-ip")
    typer.echo()
    typer.echo("  # Check node before making changes")
    typer.echo("  kitchen k8s node check --role worker --host user@node-01 --verbose")
    typer.echo()
    typer.echo("💡 TIP: Use --help with any command for detailed options")


@app.command()
def version() -> None:
    """Show the version of Kitchen."""
    from kitchen import __version__
    typer.echo(f"Kitchen version {__version__}")


def main() -> None:
    """Entry point for the CLI application."""
    app()


if __name__ == "__main__":
    main()
