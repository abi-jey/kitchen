"""Main CLI application for Kitchen."""

import typer
from typing import List, Optional
import subprocess
import sys
from kitchen.k8s.main import k8s_app
from kitchen.k8s.worker import WorkerNode
from kitchen.ssh import SSHSession

app = typer.Typer(help="Kitchen - Your Kubernetes cookbook for cluster management")

# Add the K8s sub-commands
app.add_typer(k8s_app, name="k8s")


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
    
    required_tools = ["kubectl", "kubeadm", "docker"]
    recommended_tools = ["tailscale", "ssh", "sshpass"]
    missing_tools = []
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
        typer.echo("- docker: https://docs.docker.com/engine/install/")
    
    if missing_recommended:
        typer.echo(f"\n⚠️  Missing recommended tools: {', '.join(missing_recommended)}")
        typer.echo("Installation guides:")
        typer.echo("- tailscale: https://tailscale.com/download (for secure networking)")
        typer.echo("- ssh: Usually pre-installed, check your package manager")
        typer.echo("- sshpass: For password automation (apt install sshpass / brew install sshpass)")
    
    if not missing_tools and not missing_recommended:
        typer.echo("\n🎉 All tools are installed!")
        typer.echo("Kitchen is ready for Kubernetes management.")
    elif not missing_tools:
        typer.echo("\n✅ All required tools are installed!")
        typer.echo("Kitchen is ready for basic Kubernetes management.")
        typer.echo("Install recommended tools for full functionality.")
    
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


@app.command()
def cookbook() -> None:
    """Show the Kitchen cookbook - common Kubernetes recipes."""
    typer.echo("📚 Kitchen Cookbook - Kubernetes Recipes")
    typer.echo("=" * 50)
    typer.echo()
    typer.echo("🏗️  CLUSTER MANAGEMENT:")
    typer.echo("  kitchen k8s status                 - Show cluster status")
    typer.echo("  kitchen k8s nodes list             - List all nodes")
    typer.echo("  kitchen k8s nodes add <ip>         - Add a new node")
    typer.echo()
    typer.echo("� TAILSCALE NETWORKING:")
    typer.echo("  kitchen k8s nodes add worker-node --tailscale")
    typer.echo("  kitchen k8s nodes add 100.64.1.2  --tailscale")
    typer.echo("  (Tailscale provides secure, mesh networking)")
    typer.echo()
    typer.echo("🔑 AUTHENTICATION OPTIONS:")
    typer.echo("  kitchen k8s nodes add <ip> --key ~/.ssh/id_rsa")
    typer.echo("  kitchen k8s nodes add <ip> --password --user ubuntu")
    typer.echo("  kitchen k8s nodes add --localhost  # Current machine")
    typer.echo()
    typer.echo("�🔧 SETUP:")
    typer.echo("  kitchen setup                      - Check required tools")
    typer.echo()
    typer.echo("📋 PLANNED FEATURES:")
    typer.echo("  kitchen k8s create                 - Create new cluster")
    typer.echo("  kitchen k8s nodes remove <name>    - Remove a node")
    typer.echo("  kitchen k8s backup                 - Backup cluster state")
    typer.echo("  kitchen k8s restore                - Restore cluster state")
    typer.echo()
    typer.echo("💡 EXAMPLES:")
    typer.echo("  # Add current machine as a node")
    typer.echo("  kitchen k8s nodes add --localhost")
    typer.echo()
    typer.echo("  # Add remote node with password auth")
    typer.echo("  kitchen k8s nodes add 192.168.1.100 --password --user ubuntu")
    typer.echo()
    typer.echo("  # Add Tailscale node with custom name")
    typer.echo("  kitchen k8s nodes add worker-01 --name k8s-worker-1 --tailscale")
    typer.echo()
    typer.echo("  # Dry run to see what would happen")
    typer.echo("  kitchen k8s nodes add 192.168.1.100 --dry-run")
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
