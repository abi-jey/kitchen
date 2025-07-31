"""Kubernetes management commands for Kitchen."""

import typer
import subprocess
import sys
import time
from typing import Optional, Dict, Tuple, List, Union
from pathlib import Path

# Constants
SSH_TIMEOUT = 30
SSH_CONNECT_WAIT = 2
COMMAND_PAUSE = 1
SUCCESS_MARKER = "__SUCCESS__"
FAILED_MARKER = "__FAILED__"

# Type aliases for better readability and maintainability
CommandResult = tuple[int, str, str]
CommandList = list[tuple[str, str]]
ResultDict = dict[str, CommandResult]
NodeStatus = dict[str, Union[bool, int, str, None]]

# Create a sub-app for K8s commands
k8s_app = typer.Typer(help="Kubernetes cluster management commands")

# Create a sub-app for node commands
nodes_app = typer.Typer(help="Kubernetes node management")
k8s_app.add_typer(nodes_app, name="nodes")


def run_interactive_command(cmd: List[str], verbose: bool = False) -> CommandResult:
    """Run a command with output capture.
    
    Args:
        cmd: Command and arguments to execute
        verbose: Whether to show the command being run
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    if verbose:
        typer.echo(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=SSH_TIMEOUT
        )
        return result.returncode, result.stdout, result.stderr
        
    except subprocess.TimeoutExpired:
        return 1, "", f"Command '{cmd[0]}' timed out after {SSH_TIMEOUT}s"
    except FileNotFoundError:
        return 1, "", f"Command '{cmd[0]}' not found"
    except Exception as e:
        return 1, "", f"Error running command: {e}"


def run_ssh_command(host: str, user: str, command: str, ssh_key: Optional[str] = None, 
                   verbose: bool = False) -> CommandResult:
    """Run a command on a remote host via SSH.
    
    Args:
        host: Remote host to connect to
        user: SSH username
        command: Command to execute
        ssh_key: Optional path to SSH private key
        verbose: Whether to show SSH command
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no"]
    
    if ssh_key:
        ssh_key_path = Path(ssh_key)
        if not ssh_key_path.exists():
            return 1, "", f"SSH key not found: {ssh_key}"
        ssh_cmd.extend(["-i", str(ssh_key_path)])
        
        # With SSH key, we can capture output
        ssh_cmd.extend([f"{user}@{host}", command])
        
        if verbose:
            typer.echo(f"SSH Command: {' '.join(ssh_cmd)}")
        
        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=SSH_TIMEOUT)
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return 1, "", f"SSH command timed out after {SSH_TIMEOUT}s"
        except Exception as e:
            return 1, "", f"SSH error: {e}"
    else:
        # Without SSH key, use interactive mode for password
        ssh_cmd.extend([f"{user}@{host}", command])
        
        if verbose:
            typer.echo(f"SSH Command: {' '.join(ssh_cmd)}")
        
        try:
            result = subprocess.run(
                ssh_cmd, 
                text=True, 
                stdin=sys.stdin, 
                stdout=sys.stdout, 
                stderr=sys.stderr,
                timeout=SSH_TIMEOUT
            )
            return result.returncode, "", ""
        except subprocess.TimeoutExpired:
            return 1, "", f"SSH command timed out after {SSH_TIMEOUT}s"
        except Exception as e:
            return 1, "", f"SSH error: {e}"


def run_interactive_ssh_session(host: str, user: str, commands: list[tuple[str, str]], 
                               ssh_key: Optional[str] = None, verbose: bool = False) -> dict[str, tuple[int, str, str]]:
    """Run multiple commands in a single interactive SSH session with user confirmation."""
    
    # Show user what we're about to do
    typer.echo(f"🔗 About to connect to {user}@{host} and run these commands:")
    for i, (desc, cmd) in enumerate(commands, 1):
        typer.echo(f"  {i}. {desc}: {cmd}")
    
    typer.echo()
    if not typer.confirm("Continue with SSH connection?"):
        typer.echo("❌ Operation cancelled by user")
        return {desc: (1, "", "Cancelled by user") for desc, cmd in commands}
    
    # Build SSH command
    ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no"]
    if ssh_key:
        if not Path(ssh_key).exists():
            return {desc: (1, "", f"SSH key not found: {ssh_key}") for desc, cmd in commands}
        ssh_cmd.extend(["-i", ssh_key])
    
    ssh_cmd.append(f"{user}@{host}")
    
    typer.echo(f"🔗 Connecting to {host}...")
    if verbose:
        typer.echo(f"SSH Command: {' '.join(ssh_cmd)}")
    
    results = {}
    
    try:
        # Start interactive SSH session
        process = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Combine stderr with stdout
            text=True,
            bufsize=1
        )
        
        # Wait for initial connection (let user enter password if needed)
        time.sleep(2)
        
        # Check if SSH connection failed immediately
        if process.poll() is not None:
            return {desc: (1, "", "SSH connection failed") for desc, cmd in commands}
        
        typer.echo("✅ SSH connection established")
        
        # Run each command interactively
        for i, (desc, cmd) in enumerate(commands, 1):
            typer.echo(f"\n🔧 Step {i}/{len(commands)}: {desc}")
            typer.echo(f"   Running: {cmd}")
            
            if process.stdin:
                # Send command with exit code capture
                full_cmd = f"{cmd} && echo '__SUCCESS__' || echo '__FAILED__'\n"
                process.stdin.write(full_cmd)
                process.stdin.flush()
            
            # Read output until we see our marker
            output_lines = []
            success = False
            timeout = 30
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if process.poll() is not None:
                    break
                
                if process.stdout:
                    line = process.stdout.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    
                    line = line.rstrip('\n')
                    if line == '__SUCCESS__':
                        success = True
                        break
                    elif line == '__FAILED__':
                        success = False
                        break
                    elif line.strip():  # Only show non-empty lines
                        output_lines.append(line)
                        typer.echo(f"   {line}")
            
            # Store result
            exit_code = 0 if success else 1
            output = '\n'.join(output_lines)
            results[desc] = (exit_code, output, "")
            
            # Show result
            status = "✅ Success" if success else "❌ Failed"
            typer.echo(f"   {status}")
            
            # Pause between commands so user can see results
            if i < len(commands):
                time.sleep(1)
        
        # Clean up SSH session
        if process.stdin:
            process.stdin.write("exit\n")
            process.stdin.close()
        
        process.wait(timeout=5)
        
        return results
        
    except Exception as e:
        typer.echo(f"❌ SSH session error: {e}")
        return {desc: (1, "", f"SSH error: {e}") for desc, cmd in commands}


def check_master_node(master_ip: str, user: str = "root", ssh_key: Optional[str] = None, 
                     verbose: bool = False) -> NodeStatus:
    """Check master node status and gather cluster information.
    
    Args:
        master_ip: IP address of the master node
        user: SSH username (default: root)
        ssh_key: Optional path to SSH private key
        verbose: Whether to show detailed output
        
    Returns:
        Dictionary containing master node status and cluster information
    """
    typer.echo(f"🔍 Checking master node {master_ip}...")
    
    # Define commands with descriptions
    command_list: CommandList = [
        ("Test connection", "echo 'Connected'"),
        ("Check kubeadm", "which kubeadm"),
        ("Check kubectl", "which kubectl"), 
        ("Check tailscale", "which tailscale"),
        ("Get Tailscale IP", "tailscale ip -4"),
        ("Check cluster status", "kubectl cluster-info"),
        ("Count nodes", "kubectl get nodes --no-headers | wc -l"),
        ("Generate join token", "kubeadm token create --print-join-command")
    ]
    
    # Run all commands in a single SSH session
    results = run_interactive_ssh_session(master_ip, user, command_list, ssh_key, verbose)
    
    # Check initial connection
    connect_result = results.get("Test connection", (1, "", ""))
    if connect_result[0] != 0:
        typer.echo(f"❌ Failed to connect to master node", err=True)
        return {"error": "Connection failed", "details": "SSH connection failed"}
    
    typer.echo("\n📊 Master Node Summary:")
    typer.echo("=" * 40)
    
    checks: NodeStatus = {
        "connected": True,
        "kubeadm": False,
        "kubectl": False,
        "tailscale": False,
        "cluster_initialized": False,
        "join_command": None,
        "tailscale_ip": None,
        "node_count": 0
    }
    
    # Check kubeadm
    kubeadm_result = results.get("Check kubeadm", (1, "", ""))
    checks["kubeadm"] = kubeadm_result[0] == 0
    typer.echo(f"{'✅' if checks['kubeadm'] else '❌'} kubeadm: "
              f"{'installed' if checks['kubeadm'] else 'not found'}")  # fmt: skip
    
    # Check kubectl
    kubectl_result = results.get("Check kubectl", (1, "", ""))
    checks["kubectl"] = kubectl_result[0] == 0
    typer.echo(f"{'✅' if checks['kubectl'] else '❌'} kubectl: "
              f"{'installed' if checks['kubectl'] else 'not found'}")  # fmt: skip
    
    # Check Tailscale
    tailscale_result = results.get("Check tailscale", (1, "", ""))
    checks["tailscale"] = tailscale_result[0] == 0
    typer.echo(f"{'✅' if checks['tailscale'] else '❌'} tailscale: "
              f"{'installed' if checks['tailscale'] else 'not found'}")  # fmt: skip
    
    if checks["tailscale"]:
        # Get Tailscale IP
        tailscale_ip_result = results.get("Get Tailscale IP", (1, "", ""))
        if tailscale_ip_result[0] == 0 and tailscale_ip_result[1].strip():
            checks["tailscale_ip"] = tailscale_ip_result[1].strip()
            typer.echo(f"🔗 Tailscale IP: {checks['tailscale_ip']}")
    
    # Check if cluster is initialized
    if checks["kubectl"]:
        cluster_info_result = results.get("Check cluster status", (1, "", ""))
        checks["cluster_initialized"] = (cluster_info_result[0] == 0 and 
                                       "Kubernetes control plane is running" in cluster_info_result[1])
        typer.echo(f"{'✅' if checks['cluster_initialized'] else '❌'} Cluster: "
                  f"{'initialized' if checks['cluster_initialized'] else 'not initialized'}")  # fmt: skip
        
        if checks["cluster_initialized"]:
            # Get node count
            node_count_result = results.get("Count nodes", (1, "", ""))
            if node_count_result[0] == 0:
                try:
                    checks["node_count"] = int(node_count_result[1].strip())
                    typer.echo(f"📊 Current nodes: {checks['node_count']}")
                except ValueError:
                    pass
    
    # Generate join command if cluster is ready
    if checks["cluster_initialized"] and checks["kubeadm"]:
        join_cmd_result = results.get("Generate join token", (1, "", ""))
        if join_cmd_result[0] == 0 and join_cmd_result[1].strip():
            checks["join_command"] = join_cmd_result[1].strip()
            typer.echo("✅ Join command ready")
        else:
            typer.echo(f"⚠️  Warning: Could not generate join command")
    
    return checks


@nodes_app.command("add")
def add_node(
    node_ip: Optional[str] = typer.Argument(None, help="IP address or Tailscale hostname of the node to add (use 'localhost' for current machine)"),  # fmt: skip
    master_ip: str = typer.Option(..., "--master", "-m", help="IP address or hostname of the master node"),
    node_name: Optional[str] = typer.Option(None, "--name", "-n", 
                                           help="Name for the node (optional)"),
    ssh_user: str = typer.Option("root", "--user", "-u", 
                                help="SSH user for connecting to nodes"),
    ssh_key: Optional[str] = typer.Option(None, "--key", "-k", 
                                         help="Path to SSH private key"),
    tailscale: bool = typer.Option(True, "--tailscale/--no-tailscale", 
                                  help="Use Tailscale networking (default: enabled)"),
    localhost: bool = typer.Option(False, "--localhost", "-l", 
                                  help="Add the current machine as a node"),
    verbose: bool = typer.Option(False, "--verbose", "-v", 
                                help="Enable verbose output"),
    dry_run: bool = typer.Option(False, "--dry-run", 
                                help="Show what would be done without executing")
) -> None:
    """Add a new node to the Kubernetes cluster.
    
    Steps: 1) Verify master node, 2) Check prerequisites, 3) Generate join token,
    4) Prepare worker node, 5) Join cluster.
    
    Master verification ensures cluster is initialized and tools are available.
    
    Examples:
      kitchen k8s nodes add 192.168.1.100 --master 192.168.1.10
      kitchen k8s nodes add worker-node --master control-plane
      kitchen k8s nodes add --localhost --master 192.168.1.10
    """
    # Handle localhost mode
    if localhost:
        if node_ip and node_ip != "localhost":
            typer.echo("⚠️  Warning: --localhost flag overrides provided IP address", err=True)
        node_ip = "localhost"
        typer.echo("🏠 Adding current machine as a Kubernetes node...")
    elif not node_ip:
        typer.echo("❌ Error: Node IP is required unless using --localhost", err=True)
        sys.exit(1)
    
    # Step 1: Check master node first
    typer.echo("🎯 Phase 1: Master Node Verification")
    typer.echo("=" * 50)
    
    master_status = check_master_node(master_ip, ssh_user, ssh_key, verbose)
    
    if "error" in master_status:
        typer.echo("❌ Master node check failed. Cannot proceed.", err=True)
        sys.exit(1)
    
    if not master_status.get("cluster_initialized"):
        typer.echo("❌ Kubernetes cluster is not initialized on master node", err=True)
        typer.echo("💡 Initialize the cluster first with: kubeadm init", err=True)
        sys.exit(1)
    
    if not master_status.get("join_command"):
        typer.echo("❌ Could not generate join command from master", err=True)
        sys.exit(1)
    
    typer.echo()
    typer.echo("🚀 Phase 2: Worker Node Setup")
    typer.echo("=" * 50)
    typer.echo(f"Adding node {node_ip} to Kubernetes cluster...")
    
    if tailscale:
        typer.echo("🔗 Using Tailscale networking")
    
    if node_name:
        typer.echo(f"📝 Node name: {node_name}")
    
    if dry_run:
        typer.echo("🔍 Dry run mode - showing planned actions:")
        typer.echo()
        typer.echo("MASTER NODE CHECKS:")
        typer.echo(f"✅ Master connectivity: {master_status['connected']}")
        typer.echo(f"✅ Cluster initialized: {master_status['cluster_initialized']}")
        typer.echo(f"✅ Join command ready: {bool(master_status['join_command'])}")
        typer.echo()
        typer.echo("WORKER NODE ACTIONS:")
        if node_ip != "localhost":
            typer.echo(f"1. Test SSH connection to {node_ip}")
        else:
            typer.echo("1. Test local connection")
        
        if tailscale:
            typer.echo("2. Check/Install Tailscale")
        typer.echo("3. Update system packages")
        typer.echo("4. Install Docker/containerd")
        typer.echo("5. Install kubeadm, kubelet, kubectl")
        typer.echo("6. Join cluster using master's join command")
        return
    
    typer.echo("🎉 Master node verification completed successfully!")
    typer.echo("💡 Implementation of worker node setup is coming soon...")


@nodes_app.command("list")
def list_nodes(
    verbose: bool = typer.Option(False, "--verbose", "-v", 
                                help="Show detailed node information")
) -> None:
    """List all nodes in the Kubernetes cluster."""
    typer.echo("📋 Listing Kubernetes nodes...")
    
    cmd = ["kubectl", "get", "nodes"]
    if verbose:
        cmd.append("-o=wide")
    
    exit_code, stdout, stderr = run_interactive_command(cmd, verbose=False)
    if exit_code == 0:
        typer.echo(stdout)
    else:
        typer.echo(f"❌ Failed to list nodes: {stderr}", err=True)
    
    sys.exit(exit_code)


@k8s_app.command("status")
def cluster_status() -> None:
    """Show the status of the Kubernetes cluster."""
    typer.echo("📊 Kubernetes cluster status:")
    
    # Show cluster info
    typer.echo("\n🔍 Cluster info:")
    exit_code, stdout, stderr = run_interactive_command(["kubectl", "cluster-info"])
    if exit_code == 0:
        typer.echo(stdout)
    else:
        typer.echo(f"❌ Failed to get cluster info: {stderr}", err=True)
    
    # Show nodes
    typer.echo("\n📋 Nodes:")
    exit_code, stdout, stderr = run_interactive_command(["kubectl", "get", "nodes"])
    if exit_code == 0:
        typer.echo(stdout)
    else:
        typer.echo(f"❌ Failed to get nodes: {stderr}", err=True)
    
    # Show system pods
    typer.echo("\n🏗️  System pods:")
    exit_code, stdout, stderr = run_interactive_command(["kubectl", "get", "pods", "-n", "kube-system"])
    if exit_code == 0:
        typer.echo(stdout)
    else:
        typer.echo(f"❌ Failed to get system pods: {stderr}", err=True)
