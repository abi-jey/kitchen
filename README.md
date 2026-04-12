# Kitchen

Your Kubernetes cookbook for cluster management and operations.

Kitchen is a command-line tool designed to simplify Kubernetes cluster management. It provides easy-to-use commands for adding nodes, managing clusters, and performing common K8s operations.

## Installation

Install using Poetry:

```bash
poetry install
```

## Quick Start

### 1. Check Your Setup
```bash
kitchen setup
```

This checks for required tools and shows your Tailscale status.

### 2. Configure Your Cluster

First, set up your master node configuration:
```bash
# Initialize master node config
kitchen k8s config init --hostname master-01 \
  --ip 192.168.1.10 \
  --ip 100.64.1.5 \
  --version 1.29 \
  --cluster production

# Save cluster secrets (you'll be prompted for values)
kitchen k8s config set-secrets --cluster production

# Verify configuration
kitchen k8s config show
```

### 3. Add Worker Nodes

**Step 1: Check the node**
```bash
kitchen k8s node check --role worker --host user@192.168.1.100 --verbose
```

**Step 2: Prepare the node**
```bash
kitchen k8s node prepare --role worker --host user@192.168.1.100
```

This installs:
- Tailscale (if configured in secrets)
- CRI-O container runtime
- Kubernetes components (kubelet, kubeadm, kubectl)

**Step 3: Join the node to your cluster**
```bash
kitchen k8s node join --host user@192.168.1.100 --cluster production --verbose
```

### 4. View Available Commands
```bash
kitchen cookbook
```

This shows common recipes and usage examples.

## Core Features

### Cluster Configuration Management
```bash
# Initialize master node configuration
kitchen k8s config init --hostname master-01 --ip 192.168.1.10 --ip 100.64.1.5

# Save cluster secrets (join token, discovery hash, Tailscale auth key)
kitchen k8s config set-secrets --cluster my-cluster

# Show current master configuration
kitchen k8s config show

# List all configured clusters
kitchen k8s config list

# Set default cluster
kitchen k8s config set-default my-cluster
```

### Node Management
```bash
# Run pre-flight checks on a node
kitchen k8s node check --role worker --host user@192.168.1.100 --verbose

# Prepare a node (install components)
kitchen k8s node prepare --role worker --host user@192.168.1.100 --phases tailscale,container-runtime,kube-components

# Join a worker node to the cluster
kitchen k8s node join --host user@worker-node --cluster my-cluster --verbose

# Add a node (interactive workflow - WIP)
kitchen k8s node add --master user@master-node --target user@worker-node
```

**Available Component Phases:**
- `tailscale` - Install and configure Tailscale for secure networking
- `container-runtime` - Install CRI-O container runtime
- `kube-components` - Install kubectl, kubelet, and kubeadm
- `apiserver-cert` - Configure API server certificates (master only)

The `check` and `prepare` commands accept `--phases` to target specific components. If omitted, sensible defaults are used based on the node role.

#### Proposal: Improving Node Adds with Labels and Taints
Currently, when nodes are provisioned (either manually via `node join` or automated via `node-pools scale`), the node setup SSH script writes a bare-minimum `JoinConfiguration` (`/tmp/kitchen-join.yaml`) dynamically, attaching `node-ip` for Tailscale logic if found.

*The Problem:* There is no native support for assigning Kubernetes Labels or Taints. This forces admins to manually execute `kubectl label nodes <name>` post-join, which leads to race conditions where unintended workloads might schedule before labels/taints are applied.

**Proposed Implementation:**
1. **NodePool Schema Updates:** Extend `NodePool` in `src/kitchen/config/models.py` to include `labels: dict[str, str]` and `taints: list[str]`.
2. **Kubeadm JoinConfiguration modifications:**
   - **Labels:** Update the `JoinConfiguration` to append `node-labels` to the `kubeletExtraArgs` map. Since Kubeadm requires this as a comma-separated list, we will generate:
     ```yaml
     nodeRegistration:
       kubeletExtraArgs:
         - name: node-labels
           value: "pool=my-azure-workers,env=production"
     ```
   - **Taints:** Add `taints` natively to `nodeRegistration` inside the dynamic YAML.
     ```yaml
     nodeRegistration:
       taints:
         - key: "gpu"
           value: "true"
           effect: "NoSchedule"
     ```
3. **CLI Arguments:** Extend `kitchen k8s node join` to accept `--label` and `--taint` flags. This enables users to attach workload isolation topologies from the get-go reliably before the kubelet registers to the API server.

### Tailscale Integration

Kitchen integrates with [Tailscale](https://tailscale.com) for secure, mesh networking between Kubernetes nodes:

**Benefits:**
- 🔒 **Secure**: End-to-end encrypted mesh network
- 🌐 **Easy**: No complex firewall rules or VPN setup
- 📱 **Accessible**: Access your cluster from anywhere
- 🏷️ **Named**: Use friendly hostnames instead of IPs

**How Kitchen Uses Tailscale:**
- Kitchen can install and configure Tailscale on nodes during the prepare phase
- Automatically detects Tailscale IPs for kubelet node-ip configuration
- Uses Tailscale for secure API server communication
- Prefers Tailscale endpoints when joining nodes to the cluster

**Configuration:**
Save your Tailscale auth key in cluster secrets:
```bash
kitchen k8s config set-secrets --cluster my-cluster
# You'll be prompted for the Tailscale auth key
```

### Node Manager
```bash
# Deploy node manager to Kubernetes
kitchen node-manager deploy

# Check node manager status
kitchen node-manager status

# View node manager logs
kitchen node-manager logs --follow

# Access node manager API locally
kitchen node-manager api --port 8000
```

#### Accessing the UI
The Node Manager includes a web-based dashboard UI. To access it locally:
1. Build the UI first (from the repository root):
   ```bash
   npm install
   npm run build
   ```
2. Start the API server:
   ```bash
   kitchen node-manager api --port 8000
   ```
3. Open your browser and navigate to **`http://localhost:8000/ui`**.

### Node Pools & Azure Integration
Kitchen allows you to define node pools using various cloud providers. Here's an example of how to provision an Azure VMSS node pool and automatically add the instances to your cluster:

```bash
# 1. Add an Azure Node Pool definition
kitchen k8s node-pools add \
  --name my-azure-workers \
  --provider azure \
  --azure-vmss-name my-scale-set \
  --azure-resource-group my-resource-group \
  --size 0

# 2. Scale the pool and auto-join the new nodes to the Kubernetes cluster
kitchen k8s node-pools scale my-azure-workers \
  --size 3 \
  --auto-join
```
*Note: The scale command requires you to have the Azure CLI (`az`) installed and authenticated.*

### Utility Commands
```bash
# Run any command
kitchen run kubectl get pods

# Show Kitchen version
kitchen version

# View the cookbook
kitchen cookbook
```

## Prerequisites

Kitchen requires these tools to be installed:

**Required (for local machine):**
- `kubectl` - Kubernetes command-line tool (for cluster interaction)
- `kubeadm` - Kubernetes cluster management (if setting up locally)
- `docker` - Container runtime (for local development, not required for remote node setup)

**Recommended:**
- `tailscale` - Secure mesh networking (highly recommended)
- `ssh` - Remote access to nodes
- `sshpass` - For password-based SSH automation

**Note:** Kitchen automatically installs CRI-O (container runtime) and Kubernetes components on remote nodes during the prepare phase. You don't need to pre-install these on worker nodes.

Run `kitchen setup` to check your installation and see Tailscale status.

## Development

### Setup Development Environment

```bash
# Install dependencies
poetry install

# Run CLI in development
poetry run kitchen --help

# Run with verbose output
poetry run kitchen --verbose k8s config show
```
UI
--
Build the Vite UI from the repository root with:

  npm install
  npm run build

Then build the node-manager image; the Docker build expects `dist/kitchen-ui` to
exist and will copy it into the image so the UI can be served from /ui.

### Project Structure

```
src/kitchen/
├── main.py              # Main CLI entry point
├── ssh.py               # SSH session management
├── config/              # Configuration management
├── k8s/                 # Kubernetes operations
│   ├── main.py         # K8s CLI commands
│   ├── handlers/       # Component handlers (Tailscale, CRI-O, etc.)
│   ├── nodes/          # Pre-flight checks
│   ├── master.py       # Master node operations
│   └── worker.py       # Worker node operations
└── node_manager/       # Node monitoring service
    ├── api/            # FastAPI endpoints
    ├── cli.py          # Node manager CLI
    └── manifests/      # Kubernetes manifests
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=kitchen
```

## Roadmap

- ✅ Node pre-flight checks (validate requirements before setup)
- ✅ Node preparation (automated CRI-O and Kubernetes component installation)
- ✅ Worker node joining with Tailscale support
- ✅ Cluster configuration management (multi-cluster support)
- ✅ Node manager with FastAPI and connectivity tracking
- ✅ Tailscale integration (automated installation and configuration)
- ✅ CRI-O container runtime support
- 🚧 Complete node addition workflow (interactive end-to-end)
- 🚧 Master node initialization
- 🚧 Node removal and cleanup
- 🚧 Cluster backup and restore

## Troubleshooting

### Common Issues

**SSH Connection Issues**
- Ensure SSH key permissions are correct: `chmod 600 ~/.ssh/id_rsa`
- Test SSH connection manually: `ssh user@host`
- Use `--verbose` flag for detailed connection logs

**Node Join Failures**
- Verify master config is set: `kitchen k8s config show`
- Check cluster secrets are saved: `kitchen k8s config show-secrets`
- Ensure all phases are prepared: `kitchen k8s node check --role worker --host user@node`
- Review join logs with `--verbose` flag

**Tailscale Issues**
- Verify Tailscale is running: `tailscale status`
- Check auth key is set in secrets: `kitchen k8s config show-secrets`
- Manually test Tailscale connectivity: `ping 100.64.x.x`

**Container Runtime Issues**
- Check CRI-O status: `systemctl status crio`
- View CRI-O logs: `journalctl -u crio -f`
- Verify container runtime socket: `crictl info`

### Getting Help

- Run any command with `--help` for detailed usage
- Use `--verbose` flag for debugging
- Check the cookbook: `kitchen cookbook`
- Review command history in `.github/history/` for development context

## Contributing

Kitchen is designed to be your personal Kubernetes cookbook. Feel free to extend it with your own recipes and automation!

**Development Guidelines:**
- Follow existing code structure and patterns
- Add type hints to all functions
- Keep line length to 120 characters (use `# fmt: skip` for long strings)
- Use named constants instead of magic numbers
- Write comprehensive error messages with actionable suggestions


