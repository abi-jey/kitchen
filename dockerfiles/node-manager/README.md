# Kitchen Node Manager

A FastAPI service for monitoring Kubernetes nodes and their network connectivity.

## Features

- **Node Monitoring**: Periodically fetches all Kubernetes nodes and tracks their status
- **Connectivity Checking**: Node-to-node connectivity via agents running on each node
- **REST API**: Provides endpoints for querying node status and connectivity metrics
- **Web UI**: Interactive dashboard with connectivity graph visualization
- **Database Storage**: Stores node snapshots and connectivity records in PostgreSQL
- **High Availability**: Designed for deployment with HPA and pod disruption budgets

## Architecture

The node manager has a split architecture with two container images:

### 1. Server (`node-manager-server`)
- **FastAPI Application**: REST API endpoints for querying data
- **Web UI**: React-based dashboard for visualizing node connectivity
- **Background Worker**: Async tasks for monitoring nodes from Kubernetes API
- **WebSocket**: Live updates to connected UI clients
- **Runs as**: Kubernetes Deployment (1-5 replicas)
- **Image**: `ghcr.io/abi-jey/kitchen/node-manager-server`

### 2. Agent (`node-agent`)
- **Lightweight Python Agent**: Minimal footprint (~20MB image)
- **Node-to-Node Pinging**: Pings all other nodes from its host
- **Reports to Server**: Sends connectivity measurements to the server API
- **Runs as**: Kubernetes DaemonSet (one per node)
- **Image**: `ghcr.io/abi-jey/kitchen/node-agent`

```
┌─────────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐    ┌──────────────────┐                  │
│  │  Server Pod #1   │    │  Server Pod #2   │  (Deployment)    │
│  │  - API + UI      │    │  - API + UI      │                  │
│  │  - K8s watcher   │    │  - K8s watcher   │                  │
│  └────────┬─────────┘    └────────┬─────────┘                  │
│           │                       │                             │
│           └───────────┬───────────┘                             │
│                       │                                         │
│              ┌────────▼────────┐                               │
│              │   PostgreSQL    │                               │
│              └─────────────────┘                               │
│                       ▲                                         │
│                       │ POST /connectivity/report               │
│  ┌────────────────────┼────────────────────────┐               │
│  │                    │                        │   (DaemonSet) │
│  ▼                    ▼                        ▼               │
│ ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│ │ Agent    │    │ Agent    │    │ Agent    │                   │
│ │ (node-1) │◄──►│ (node-2) │◄──►│ (node-3) │  ← ping each other│
│ └──────────┘    └──────────┘    └──────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Deployment

### Prerequisites

- Kubernetes cluster with RBAC enabled
- PostgreSQL database (external - not included in deployment)

### Quick Start

1. **Configure your PostgreSQL database** and update the connection string in `node-manager-secrets`:
   ```bash
   kubectl edit secret node-manager-secrets -n kitchen-system
   ```

2. **Deploy the node manager**:
   ```bash
   kubectl apply -f k8s-manifests.yaml
   ```

3. **Docker images are automatically built and pushed via GitHub Actions**:
   - Server: `ghcr.io/abi-jey/kitchen/node-manager-server:latest`
   - Agent: `ghcr.io/abi-jey/kitchen/node-agent:latest`
   
   ```bash
   # Update images in deployment
   kubectl set image deployment/node-manager-server \
     node-manager-server=ghcr.io/abi-jey/kitchen/node-manager-server:latest \
     -n kitchen-system
   
   kubectl set image daemonset/node-agent \
     node-agent=ghcr.io/abi-jey/kitchen/node-agent:latest \
     -n kitchen-system
   ```

### Configuration

#### Server Configuration (via ConfigMap/Secret)

| Variable | Description | Default |
|----------|-------------|---------|
| `MONITORING_INTERVAL` | Node monitoring frequency (seconds) | 60 |
| `CONNECTIVITY_INTERVAL` | Server-side ping frequency (seconds) | 300 |
| `PING_COUNT` | Ping packets per check | 4 |
| `PING_TIMEOUT` | Ping timeout (seconds) | 5 |
| `DATABASE_URL` | PostgreSQL connection string | Required |
| `LOG_LEVEL` | Application log level | INFO |

#### Agent Configuration (via ConfigMap)

| Variable | Description | Default |
|----------|-------------|---------|
| `NODE_MANAGER_API_URL` | URL of the server API | `http://node-manager.kitchen-system.svc:8000` |
| `REPORT_INTERVAL` | How often to report connectivity (seconds) | 60 |
| `PING_COUNT` | Ping packets per check | 4 |
| `PING_TIMEOUT` | Ping timeout (seconds) | 5 |
| `LOG_LEVEL` | Agent log level | INFO |

### Database Schema

**node_snapshots**: Tracks node state over time
- Node metadata (name, IPs, versions)
- Status and readiness information
- Resource capacity
- First/last seen timestamps

**node_connectivity**: Records ping measurements
- Per-node latency and packet loss
- Success/failure status
- Error details
- Measurement timestamps

## API Endpoints

### Health and Status

- `GET /health` - Service health check
- `GET /stats` - Cluster-wide node statistics

### Node Information

- `GET /nodes` - List all nodes with optional filtering
  - `?ready=true/false` - Filter by readiness
  - `?available=true/false` - Filter by availability
- `GET /nodes/{node_name}` - Detailed node information

### Connectivity

- `GET /nodes/{node_name}/connectivity` - Connectivity history
  - `?hours=24` - Hours of history (default: 24, max: 168)

### Example Responses

**Node List**:
```json
[
  {
    "name": "worker-1",
    "status": "Ready", 
    "ready": true,
    "schedulable": true,
    "internal_ip": "10.0.1.10",
    "tailscale_ip": "100.64.1.10",
    "kubelet_version": "v1.29.0",
    "first_seen_at": "2024-01-01T10:00:00Z",
    "last_seen_at": "2024-01-01T10:30:00Z",
    "unavailable_since": null
  }
]
```

**Connectivity Record**:
```json
[
  {
    "node_name": "worker-1",
    "target_ip": "100.64.1.10",
    "success": true,
    "latency_ms": 12.5,
    "packet_loss": 0.0,
    "error_message": null,
    "ping_count": 4,
    "measured_at": "2024-01-01T10:25:00Z"
  }
]
```

## Monitoring and Alerts

The service provides several monitoring points:

1. **Health Endpoint**: `/health` for liveness/readiness probes
2. **Metrics**: Consider adding Prometheus metrics for:
   - Node count and status distribution
   - Connectivity success rates
   - API response times
   - Database query performance

3. **Alerts**: Set up alerts for:
   - Service unavailability
   - High connectivity failure rates
   - Database connection issues
   - Node state changes

## Security

- Runs as non-root user (UID 1000)
- Service account with minimal RBAC permissions (read-only nodes)
- Network policies to restrict traffic
- Secrets for sensitive configuration

## Scaling

- **Horizontal**: HPA scales 1-5 replicas based on CPU/memory
- **Vertical**: Adjust resource requests/limits as needed
- **Database**: Use external managed PostgreSQL for production

## Troubleshooting

**Common Issues**:

1. **Connectivity checks failing**:
   - Ensure Tailscale is installed and running on nodes
   - Check RBAC permissions for reading nodes
   - Verify network connectivity between pods and nodes

2. **Database connection errors**:
   - Check DATABASE_URL configuration
   - Verify PostgreSQL is running and accessible
   - Check network policies and security groups

3. **Node monitoring not working**:
   - Verify service account has correct RBAC permissions
   - Check Kubernetes API server connectivity
   - Review application logs for errors

**Debug Commands**:
```bash
# Check pod status
kubectl get pods -n kitchen-system -l app=node-manager

# View logs
kubectl logs -n kitchen-system deployment/node-manager -f

# Test API endpoints
kubectl port-forward -n kitchen-system service/node-manager 8000:8000
curl http://localhost:8000/health

# Check database connectivity
kubectl exec -it -n kitchen-system deployment/postgres -- psql -U kitchen_user -d kitchen_node_manager -c "SELECT count(*) FROM node_snapshots;"
```