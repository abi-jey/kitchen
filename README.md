# Kitchen

Your Kubernetes cookbook for cluster management and operations.

Kitchen is a command-line tool designed to simplify Kubernetes cluster management. It provides easy-to-use commands for adding nodes, managing clusters, and performing common K8s operations.

## Installation

Install using Poetry:

```bash
poetry install
```

## Quick Start

Check if you have the required tools:
```bash
kitchen setup
```

View available recipes:
```bash
kitchen cookbook
```

## Core Features

### Cluster Management
```bash
# Check cluster status
kitchen k8s status

# List all nodes
kitchen k8s nodes list
```

### Node Management with Tailscale
```bash
# Add a new node with Tailscale (recommended)
kitchen k8s nodes add worker-node --tailscale

# Add a node using Tailscale IP
kitchen k8s nodes add 100.64.1.100 --tailscale --name worker-1

# Add current machine as a node
kitchen k8s nodes add --localhost

# Add a node with password authentication
kitchen k8s nodes add 192.168.1.100 --password --user ubuntu

# Add a node with SSH key
kitchen k8s nodes add 192.168.1.100 \
  --key ~/.ssh/id_rsa \
  --user root \
  --name worker-2

# Dry run to see what would happen
kitchen k8s nodes add 192.168.1.100 --dry-run --tailscale
```

### Tailscale Integration

Kitchen integrates with [Tailscale](https://tailscale.com) for secure, mesh networking between Kubernetes nodes:

**Benefits:**
- 🔒 **Secure**: End-to-end encrypted mesh network
- 🌐 **Easy**: No complex firewall rules or VPN setup
- 📱 **Accessible**: Access your cluster from anywhere
- 🏷️ **Named**: Use friendly hostnames instead of IPs

**Setup:**
1. Install Tailscale on all machines: `curl -fsSL https://tailscale.com/install.sh | sh`
2. Connect to your Tailnet: `tailscale up`
3. Use Kitchen with Tailscale hostnames: `kitchen k8s nodes add worker-node --tailscale`

**Authentication Options:**
- `--key ~/.ssh/id_rsa` - SSH key authentication (default)
- `--password` - Password authentication (interactive)
- `--localhost` - Add current machine (no SSH needed)

### Node Manager
```bash
# Deploy node manager to Kubernetes
kitchen node-manager deploy

# Check node manager status
kitchen node-manager status

# View node manager logs
kitchen node-manager logs --follow

# Access node manager API
kitchen node-manager api --port 8000
```

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

**Required:**
- `kubectl` - Kubernetes command-line tool
- `kubeadm` - Kubernetes cluster management
- `docker` - Container runtime

**Recommended:**
- `tailscale` - Secure mesh networking (highly recommended)
- `ssh` - Remote access to nodes

Run `kitchen setup` to check your installation and see Tailscale status.

## Development

Install dependencies:
```bash
poetry install
```

Run the CLI in development:
```bash
poetry run kitchen --help
```

## Roadmap

- ✅ Node addition with automated setup
- ✅ Cluster status monitoring  
- ✅ Node manager with FastAPI and connectivity tracking
- 🚧 Cluster creation from scratch
- 🚧 Node removal and cleanup
- 🚧 Cluster backup and restore
- 🚧 Multi-cluster management

## Contributing

Kitchen is designed to be your personal Kubernetes cookbook. Feel free to extend it with your own recipes and automation!


