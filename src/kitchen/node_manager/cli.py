"""CLI commands for node manager integration."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from typing import Optional

import typer

node_manager_app = typer.Typer(help="Node manager commands")


@node_manager_app.command("deploy")
def deploy_node_manager(
    namespace: str = typer.Option("kitchen-system", "--namespace", "-n", help="Kubernetes namespace"),
    image: str = typer.Option("ghcr.io/abi-jey/kitchen/node-manager:latest", "--image", help="Docker image to deploy"),
    database_url: Optional[str] = typer.Option(None, "--database-url", help="PostgreSQL connection string"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deployed without applying"),
) -> None:
    """Deploy node manager to Kubernetes cluster."""
    typer.secho("🚀 Deploying Kitchen Node Manager...", fg=typer.colors.BLUE)
    
    # Check prerequisites
    if not database_url:
        typer.secho("⚠️  PostgreSQL Configuration Required", fg=typer.colors.YELLOW)
        typer.echo("The node manager requires an external PostgreSQL database.")
        typer.echo("Please provide a database URL or configure the secret manually:")
        typer.echo("")
        typer.echo("Option 1: Use --database-url parameter:")
        typer.echo("  kitchen node-manager deploy --database-url 'postgresql+asyncpg://user:pass@host:5432/db'")
        typer.echo("")
        typer.echo("Option 2: Configure Kubernetes secret after deployment:")
        typer.echo(f"  kubectl edit secret node-manager-secrets -n {namespace}")
        typer.echo("")
        typer.echo("Continuing with default secret configuration...")
    
    # Get the manifest file from the package
    import kitchen.node_manager
    
    node_manager_dir = os.path.dirname(kitchen.node_manager.__file__)
    manifests_file = os.path.join(node_manager_dir, "manifests", "k8s-manifests.yaml")
    
    if not os.path.exists(manifests_file):
        typer.secho(f"❌ Manifest file not found: {manifests_file}", fg=typer.colors.RED)
        typer.echo("This indicates a package installation issue.")
        raise typer.Exit(1)
    
    # Read and potentially modify manifests
    with open(manifests_file, 'r') as f:
        manifest_content = f.read()
    
    # Update image reference if different from default
    if image != "ghcr.io/abi-jey/kitchen/node-manager:latest":
        typer.echo(f"📝 Using custom image: {image}")
        # Replace the image in the deployment
        manifest_content = manifest_content.replace(
            "image: ghcr.io/abi-jey/kitchen/node-manager:latest",
            f"image: {image}"
        )
    
    # Update database configuration if provided
    if database_url:
        typer.echo("📝 Updating database configuration...")
        manifest_content = manifest_content.replace(
            'DATABASE_URL: "postgresql+asyncpg://kitchen_user:kitchen_password@postgres:5432/kitchen_node_manager"',
            f'DATABASE_URL: "{database_url}"'
        )
    
    # Write to temporary file for deployment
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp_file:
        tmp_file.write(manifest_content)
        tmp_manifest_path = tmp_file.name
    
    try:
        # Deploy node manager
        typer.echo("🔧 Deploying Node Manager...")
        cmd = ["kubectl", "apply", "-f", tmp_manifest_path]
        if dry_run:
            cmd.append("--dry-run=client")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            if not dry_run:
                typer.secho("✅ Node Manager deployed", fg=typer.colors.GREEN)
                typer.echo(f"Monitor deployment: kubectl get pods -n {namespace} -l app=node-manager")
                typer.echo(f"Check logs: kubectl logs -n {namespace} deployment/node-manager -f")
                
                if not database_url:
                    typer.echo("")
                    typer.secho("📋 Next Steps:", fg=typer.colors.BLUE) 
                    typer.echo("1. Configure your PostgreSQL database connection:")
                    typer.echo(f"   kubectl edit secret node-manager-secrets -n {namespace}")
                    typer.echo("2. Update the DATABASE_URL with your PostgreSQL connection string")
                    typer.echo("3. Restart the deployment to pick up the new configuration:")
                    typer.echo(f"   kubectl rollout restart deployment/node-manager -n {namespace}")
            else:
                typer.echo("Node Manager would be deployed:")
                typer.echo(result.stdout)
        except subprocess.CalledProcessError as e:
            typer.secho(f"❌ Failed to deploy Node Manager: {e.stderr}", fg=typer.colors.RED)
            raise typer.Exit(1)
        
        if not dry_run:
            typer.secho("🎉 Deployment complete!", fg=typer.colors.GREEN)
    
    finally:
        # Clean up temporary file
        try:
            os.unlink(tmp_manifest_path)
        except OSError:
            pass


@node_manager_app.command("status")
def node_manager_status(
    namespace: str = typer.Option("kitchen-system", "--namespace", "-n", help="Kubernetes namespace"),
    api_port: int = typer.Option(8000, "--port", help="Port for API access"),
) -> None:
    """Check node manager status."""
    typer.secho("📊 Checking Node Manager status...", fg=typer.colors.BLUE)
    
    # Check pods
    try:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-l", "app=node-manager"],
            capture_output=True, text=True, check=True
        )
        typer.echo("Node Manager Pods:")
        typer.echo(result.stdout)
    except subprocess.CalledProcessError as e:
        typer.secho(f"❌ Failed to get pod status: {e.stderr}", fg=typer.colors.RED)
        raise typer.Exit(1)
    
    # Check service
    try:
        result = subprocess.run(
            ["kubectl", "get", "service", "-n", namespace, "node-manager"],
            capture_output=True, text=True, check=True
        )
        typer.echo("Node Manager Service:")
        typer.echo(result.stdout)
    except subprocess.CalledProcessError as e:
        typer.secho(f"❌ Failed to get service status: {e.stderr}", fg=typer.colors.RED)
    
    typer.echo(f"\n🔗 To access the API locally:")
    typer.echo(f"   kubectl port-forward -n {namespace} service/node-manager {api_port}:8000")
    typer.echo(f"   curl http://localhost:{api_port}/health")


@node_manager_app.command("logs")
def node_manager_logs(
    namespace: str = typer.Option("kitchen-system", "--namespace", "-n", help="Kubernetes namespace"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    tail: int = typer.Option(100, "--tail", help="Number of recent lines to show"),
) -> None:
    """View node manager logs."""
    typer.secho("📋 Viewing Node Manager logs...", fg=typer.colors.BLUE)
    
    cmd = ["kubectl", "logs", "-n", namespace, "deployment/node-manager", f"--tail={tail}"]
    if follow:
        cmd.append("-f")
    
    try:
        # Use subprocess.run with no capture_output so logs stream to terminal
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        typer.secho(f"❌ Failed to get logs: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.secho("\n👋 Log streaming stopped", fg=typer.colors.YELLOW)


@node_manager_app.command("api")  
def api_access(
    namespace: str = typer.Option("kitchen-system", "--namespace", "-n", help="Kubernetes namespace"),
    port: int = typer.Option(8000, "--port", help="Local port for API access"),
) -> None:
    """Set up port forwarding to access the Node Manager API."""
    typer.secho(f"🔗 Setting up API access on port {port}...", fg=typer.colors.BLUE)
    typer.echo(f"API will be available at: http://localhost:{port}")
    typer.echo("Press Ctrl+C to stop port forwarding")
    typer.echo("")
    typer.echo("Available endpoints:")
    typer.echo("  GET  /health                        - Service health")
    typer.echo("  GET  /nodes                         - List nodes")  
    typer.echo("  GET  /nodes/{name}                  - Node details")
    typer.echo("  GET  /nodes/{name}/connectivity     - Connectivity history")
    typer.echo("  GET  /stats                         - Cluster statistics")
    typer.echo("")
    
    cmd = ["kubectl", "port-forward", "-n", namespace, "service/node-manager", f"{port}:8000"]
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        typer.secho(f"❌ Port forwarding failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.secho("\n👋 Port forwarding stopped", fg=typer.colors.YELLOW)