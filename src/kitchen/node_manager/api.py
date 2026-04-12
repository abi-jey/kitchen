"""FastAPI application for node manager."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Any, Optional, cast

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from contextlib import asynccontextmanager
from pydantic import BaseModel
import sentry_sdk
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from kitchen.node_manager.database import init_db, get_db_session, close_db
from kitchen.node_manager.models import NodeSnapshot, NodeConnectivity
from kitchen.node_manager.worker import NodeMonitorWorker
from kitchen.node_manager.websocket import manager as ws_manager, broadcast_update


# Configure logging based on environment
def _get_log_level() -> int:
    """Get log level from environment variables."""
    debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    if debug:
        return logging.DEBUG
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


logging.basicConfig(
    level=_get_log_level(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Pydantic models for API responses
class NodeSummary(BaseModel):
    """Summary information about a node."""

    name: str
    status: str
    ready: bool
    schedulable: bool
    internal_ip: Optional[str] = None
    tailscale_ip: Optional[str] = None
    kubelet_version: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime
    unavailable_since: Optional[datetime] = None


class NodeDetail(NodeSummary):
    """Detailed information about a node."""

    external_ip: Optional[str] = None
    hostname: Optional[str] = None
    container_runtime: Optional[str] = None
    os_image: Optional[str] = None
    kernel_version: Optional[str] = None
    cpu_capacity: Optional[str] = None
    memory_capacity: Optional[str] = None
    pods_capacity: Optional[int] = None
    node_created_at: Optional[datetime] = None


class ConnectivityRecord(BaseModel):
    """Connectivity measurement record with all database fields."""

    id: int
    source_node: str = "node-manager"
    node_name: str
    target_ip: str
    success: bool
    latency_ms: Optional[float] = None
    packet_loss: Optional[float] = None
    error_message: Optional[str] = None
    error_code: Optional[int] = None
    ping_count: int
    timeout_seconds: int = 5
    measured_at: datetime


class HealthStatus(BaseModel):
    """Health status of the node manager."""

    healthy: bool
    kubernetes_healthy: bool
    worker_running: bool
    monitoring_task_running: bool
    database_healthy: bool
    node_count: int
    last_monitoring_cycle: Optional[datetime] = None


class NodeStats(BaseModel):
    """Statistics about nodes."""

    total_nodes: int
    ready_nodes: int
    not_ready_nodes: int
    unavailable_nodes: int
    nodes_with_tailscale: int
    average_latency_ms: Optional[float] = None


class ConnectivitySummary(BaseModel):
    """Latest connectivity status for a node."""

    source_node: str = "node-manager"
    node_name: str
    target_ip: str
    success: bool
    latency_ms: Optional[float] = None
    packet_loss: Optional[float] = None
    measured_at: datetime


class NodeWithConnectivity(BaseModel):
    """Node with its latest connectivity status."""

    name: str
    status: str
    ready: bool
    schedulable: bool
    internal_ip: Optional[str] = None
    tailscale_ip: Optional[str] = None
    kubelet_version: Optional[str] = None
    os_image: Optional[str] = None
    cpu_capacity: Optional[str] = None
    memory_capacity: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime
    unavailable_since: Optional[datetime] = None
    connectivity: Optional[ConnectivitySummary] = None


class GraphNode(BaseModel):
    """Node representation for graph visualization."""

    id: str
    label: str
    type: str  # 'hub' or 'node'
    status: str  # 'healthy', 'degraded', 'unreachable', 'unknown'
    ready: bool
    ip: Optional[str] = None
    kubelet_version: Optional[str] = None
    cpu_capacity: Optional[str] = None
    memory_capacity: Optional[str] = None
    location: Optional[str] = None


class GraphEdge(BaseModel):
    """Edge representing connectivity between nodes."""

    source: str
    target: str
    latency_ms: Optional[float] = None
    success: bool
    packet_loss: Optional[float] = None
    measured_at: datetime


class ConnectivityGraph(BaseModel):
    """Full graph data for visualization."""

    nodes: List[GraphNode]
    edges: List[GraphEdge]


worker: Optional[NodeMonitorWorker] = None  # Global reference for handlers

if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        send_default_pii=True,
        enable_logs=True,
        traces_sample_rate=1.0,
        enable_tracing=True,
        enable_db_query_source=True,
        server_name="node-manager",
    )
    logger.info("Sentry SDK initialized")
else:
    logger.info("SENTRY_DSN not set, Sentry SDK not initialized")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[override]
    """FastAPI lifespan context managing startup and shutdown.

    Replaces deprecated @app.on_event usage.
    """
    global worker
    broadcast_task: Optional[asyncio.Task[None]] = None
    logger.info("Starting Kitchen Node Manager")
    try:
        await init_db()
        logger.info("Database initialized")
        worker = NodeMonitorWorker(
            monitoring_interval=60,  # seconds
            retention_hours=int(os.environ.get("NODE_RETENTION_HOURS", "24")),
        )
        await worker.start()
        logger.info("Worker started")

        # Start WebSocket broadcast task
        broadcast_task = asyncio.create_task(_broadcast_loop())
        logger.info("WebSocket broadcast task started")

        yield
    except Exception as e:
        logger.error(f"Failed during startup: {e}")
        # Ensure we propagate error so server fails fast
        raise
    finally:
        logger.info("Shutting down Kitchen Node Manager")
        if broadcast_task:
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass
        if worker:
            try:
                await worker.stop()
                logger.info("Worker stopped")
            except Exception as e:  # pragma: no cover - defensive
                logger.error(f"Error stopping worker: {e}")
        try:
            await close_db()
            logger.info("Database connections closed")
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"Error closing database: {e}")


async def _broadcast_loop() -> None:
    """Background task to broadcast dashboard updates to WebSocket clients."""
    while True:
        try:
            await asyncio.sleep(10)  # Broadcast every 10 seconds

            if not ws_manager.active_connections:
                continue

            # Fetch current dashboard data
            async for db in get_db_session():
                try:
                    # Get stats
                    total_result = await db.execute(
                        select(func.count(cast(Any, NodeSnapshot.id)))
                    )
                    total_nodes = total_result.scalar() or 0

                    ready_result = await db.execute(
                        select(func.count(cast(Any, NodeSnapshot.id))).where(
                            cast(Any, NodeSnapshot.ready) == True
                        )
                    )
                    ready_nodes = ready_result.scalar() or 0

                    unavailable_result = await db.execute(
                        select(func.count(cast(Any, NodeSnapshot.id))).where(
                            cast(Any, NodeSnapshot.unavailable_since).is_not(None)
                        )
                    )
                    unavailable_nodes = unavailable_result.scalar() or 0

                    # Get nodes with connectivity
                    nodes_stmt = select(NodeSnapshot).order_by(NodeSnapshot.name)
                    nodes_result = await db.execute(nodes_stmt)
                    nodes = nodes_result.scalars().all()

                    nodes_data = []
                    for node in nodes:
                        conn_stmt = (
                            select(NodeConnectivity)
                            .where(cast(Any, NodeConnectivity.node_name) == node.name)
                            .order_by(desc(cast(Any, NodeConnectivity.measured_at)))
                            .limit(1)
                        )
                        conn_result = await db.execute(conn_stmt)
                        conn = conn_result.scalar_one_or_none()

                        connectivity = None
                        if conn:
                            connectivity = {
                                "node_name": conn.node_name,
                                "target_ip": conn.target_ip,
                                "success": conn.success,
                                "latency_ms": conn.latency_ms,
                                "packet_loss": conn.packet_loss,
                                "measured_at": conn.measured_at,
                            }

                        nodes_data.append(
                            {
                                "name": node.name,
                                "status": node.status,
                                "ready": node.ready,
                                "schedulable": node.schedulable,
                                "internal_ip": node.internal_ip,
                                "tailscale_ip": node.tailscale_ip,
                                "kubelet_version": node.kubelet_version,
                                "os_image": node.os_image,
                                "cpu_capacity": node.cpu_capacity,
                                "memory_capacity": node.memory_capacity,
                                "first_seen_at": node.first_seen_at,
                                "last_seen_at": node.last_seen_at,
                                "unavailable_since": node.unavailable_since,
                                "connectivity": connectivity,
                            }
                        )

                    await broadcast_update(
                        "dashboard",
                        {
                            "stats": {
                                "total_nodes": total_nodes,
                                "ready_nodes": ready_nodes,
                                "not_ready_nodes": total_nodes
                                - ready_nodes
                                - unavailable_nodes,
                                "unavailable_nodes": unavailable_nodes,
                            },
                            "nodes": nodes_data,
                        },
                    )
                finally:
                    break

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in broadcast loop: {e}")
            await asyncio.sleep(5)


app = FastAPI(
    title="Kitchen Node Manager",
    description="Kubernetes node monitoring and connectivity tracking service",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static UI assets from `dist/kitchen-ui` within the repo/cwd
UI_PATH = os.path.join(os.getcwd(), "dist", "kitchen-ui")
if os.path.isdir(UI_PATH):
    try:
        # html=True ensures index.html will be used for SPA routing when
        # requesting the mount root (e.g. GET /ui)
        app.mount("/ui", StaticFiles(directory=UI_PATH, html=True), name="ui")
        logger.info(f"Mounted UI static files at /ui from {UI_PATH}")
    except Exception as e:  # pragma: no cover - optional behavior
        logger.warning(f"Failed to mount UI static files: {e}")
else:
    logger.info(
        "No UI static assets found at runtime. Build the UI and copy "
        "dist/kitchen-ui into /app/dist/kitchen-ui if you want to deploy the "
        "UI with the image"
    )


@app.get("/ui", include_in_schema=False)
async def serve_ui_index() -> FileResponse:  # pragma: no cover - optional
    """Serve the UI entrypoint if available at runtime.

    This makes it convenient to navigate to /ui in a browser.
    """
    index_path = os.path.join(UI_PATH, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="UI not available")


@app.get("/health", response_model=HealthStatus)
async def get_health(db: AsyncSession = Depends(get_db_session)) -> HealthStatus:
    """Get health status of the node manager."""
    try:
        # Check database health
        db_healthy = True
        node_count = 0
        last_monitoring = None

        try:
            # Simple query to test database
            result = await db.execute(select(func.count(cast(Any, NodeSnapshot.id))))  # type: ignore[arg-type]
            node_count = result.scalar() or 0

            # Get last monitoring time
            result = await db.execute(
                select(cast(Any, NodeSnapshot.last_seen_at))  # type: ignore[arg-type]
                .order_by(desc(cast(Any, NodeSnapshot.last_seen_at)))  # type: ignore[arg-type]
                .limit(1)
            )
            last_monitoring = result.scalar()

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            db_healthy = False

        # Get worker status
        worker_status = {}
        if worker:
            worker_status = await worker.get_health_status()

        overall_healthy = (
            db_healthy
            and worker_status.get("worker_running", False)
            and worker_status.get("kubernetes_healthy", False)
        )

        return HealthStatus(
            healthy=overall_healthy,
            database_healthy=db_healthy,
            node_count=node_count,
            last_monitoring_cycle=last_monitoring,
            kubernetes_healthy=worker_status.get("kubernetes_healthy", False),
            worker_running=worker_status.get("worker_running", False),
            monitoring_task_running=worker_status.get("monitoring_task_running", False),
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nodes", response_model=List[NodeSummary])
async def list_nodes(
    ready: Optional[bool] = Query(None, description="Filter by ready status"),
    available: Optional[bool] = Query(
        None, description="Filter by availability (not unavailable_since)"
    ),
    db: AsyncSession = Depends(get_db_session),
) -> List[NodeSummary]:
    """List all nodes with optional filtering."""
    try:
        stmt = select(NodeSnapshot)

        # Apply filters
        if ready is not None:
            stmt = stmt.where(cast(Any, NodeSnapshot.ready) == ready)  # type: ignore[arg-type]

        if available is not None:
            if available:
                stmt = stmt.where(cast(Any, NodeSnapshot.unavailable_since).is_(None))  # type: ignore[arg-type]
            else:
                stmt = stmt.where(
                    cast(Any, NodeSnapshot.unavailable_since).is_not(None)
                )  # type: ignore[arg-type]

        stmt = stmt.order_by(NodeSnapshot.name)

        result = await db.execute(stmt)
        nodes = result.scalars().all()

        return [
            NodeSummary(
                name=node.name,
                status=node.status,
                ready=node.ready,
                schedulable=node.schedulable,
                internal_ip=node.internal_ip,
                tailscale_ip=node.tailscale_ip,
                kubelet_version=node.kubelet_version,
                first_seen_at=node.first_seen_at,
                last_seen_at=node.last_seen_at,
                unavailable_since=node.unavailable_since,
            )
            for node in nodes
        ]

    except Exception as e:
        logger.error(f"Failed to list nodes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nodes/dashboard", response_model=List[NodeWithConnectivity])
async def get_nodes_dashboard(
    db: AsyncSession = Depends(get_db_session),
) -> List[NodeWithConnectivity]:
    """Get all nodes with their latest connectivity status for dashboard display."""
    try:
        # Get all nodes
        nodes_stmt = select(NodeSnapshot).order_by(NodeSnapshot.name)
        nodes_result = await db.execute(nodes_stmt)
        nodes = nodes_result.scalars().all()

        result = []
        for node in nodes:
            # Get latest connectivity for this node
            conn_stmt = (
                select(NodeConnectivity)
                .where(cast(Any, NodeConnectivity.node_name) == node.name)
                .order_by(desc(cast(Any, NodeConnectivity.measured_at)))
                .limit(1)
            )
            conn_result = await db.execute(conn_stmt)
            conn = conn_result.scalar_one_or_none()

            connectivity = None
            if conn:
                connectivity = ConnectivitySummary(
                    node_name=conn.node_name,
                    target_ip=conn.target_ip,
                    success=conn.success,
                    latency_ms=conn.latency_ms,
                    packet_loss=conn.packet_loss,
                    measured_at=conn.measured_at,
                )

            result.append(
                NodeWithConnectivity(
                    name=node.name,
                    status=node.status,
                    ready=node.ready,
                    schedulable=node.schedulable,
                    internal_ip=node.internal_ip,
                    tailscale_ip=node.tailscale_ip,
                    kubelet_version=node.kubelet_version,
                    os_image=node.os_image,
                    cpu_capacity=node.cpu_capacity,
                    memory_capacity=node.memory_capacity,
                    first_seen_at=node.first_seen_at,
                    last_seen_at=node.last_seen_at,
                    unavailable_since=node.unavailable_since,
                    connectivity=connectivity,
                )
            )

        return result

    except Exception as e:
        logger.error(f"Failed to get nodes dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nodes/{node_name}", response_model=NodeDetail)
async def get_node(
    node_name: str, db: AsyncSession = Depends(get_db_session)
) -> NodeDetail:
    """Get detailed information about a specific node."""
    try:
        stmt = select(NodeSnapshot).where(cast(Any, NodeSnapshot.name) == node_name)  # type: ignore[arg-type]
        result = await db.execute(stmt)
        node = result.scalar_one_or_none()

        if not node:
            raise HTTPException(status_code=404, detail=f"Node {node_name} not found")

        return NodeDetail(
            name=node.name,
            status=node.status,
            ready=node.ready,
            schedulable=node.schedulable,
            internal_ip=node.internal_ip,
            external_ip=node.external_ip,
            tailscale_ip=node.tailscale_ip,
            hostname=node.hostname,
            kubelet_version=node.kubelet_version,
            container_runtime=node.container_runtime,
            os_image=node.os_image,
            kernel_version=node.kernel_version,
            cpu_capacity=node.cpu_capacity,
            memory_capacity=node.memory_capacity,
            pods_capacity=node.pods_capacity,
            node_created_at=node.node_created_at,
            first_seen_at=node.first_seen_at,
            last_seen_at=node.last_seen_at,
            unavailable_since=node.unavailable_since,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get node {node_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nodes/{node_name}/connectivity", response_model=List[ConnectivityRecord])
async def get_node_connectivity(
    node_name: str,
    hours: int = Query(24, description="Hours of history to return", ge=1, le=168),
    db: AsyncSession = Depends(get_db_session),
) -> List[ConnectivityRecord]:
    """Get connectivity history for a specific node."""
    try:
        # Check if node exists
        node_stmt = select(NodeSnapshot).where(
            cast(Any, NodeSnapshot.name) == node_name
        )  # type: ignore[arg-type]
        node_result = await db.execute(node_stmt)
        if not node_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"Node {node_name} not found")

        # Get connectivity records
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = (
            select(NodeConnectivity)
            .where(
                cast(Any, NodeConnectivity.node_name) == node_name,  # type: ignore[arg-type]
                cast(Any, NodeConnectivity.measured_at) >= since,  # type: ignore[arg-type]
            )
            .order_by(desc(cast(Any, NodeConnectivity.measured_at)))  # type: ignore[arg-type]
        )

        result = await db.execute(stmt)
        records = result.scalars().all()

        return [
            ConnectivityRecord(
                id=record.id,
                source_node=record.source_node,
                node_name=record.node_name,
                target_ip=record.target_ip,
                success=record.success,
                latency_ms=record.latency_ms,
                packet_loss=record.packet_loss,
                error_message=record.error_message,
                error_code=record.error_code,
                ping_count=record.ping_count,
                timeout_seconds=record.timeout_seconds,
                measured_at=record.measured_at,
            )
            for record in records
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get connectivity for node {node_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/nodes/{node_name}/connectivity/history", response_model=List[ConnectivityRecord]
)
async def get_node_connectivity_history(
    node_name: str,
    limit: int = Query(
        100, description="Maximum number of records to return", ge=1, le=1000
    ),
    source_node: Optional[str] = Query(None, description="Filter by source node"),
    success: Optional[bool] = Query(None, description="Filter by success status"),
    db: AsyncSession = Depends(get_db_session),
) -> List[ConnectivityRecord]:
    """Get connectivity history for a specific node with filtering options.

    Returns the latest connectivity records ordered by measured_at descending.
    Default limit is 100 records.
    """
    try:
        # Check if node exists
        node_stmt = select(NodeSnapshot).where(
            cast(Any, NodeSnapshot.name) == node_name
        )  # type: ignore[arg-type]
        node_result = await db.execute(node_stmt)
        if not node_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"Node {node_name} not found")

        # Build query with filters
        stmt = select(NodeConnectivity).where(
            cast(Any, NodeConnectivity.node_name) == node_name  # type: ignore[arg-type]
        )

        if source_node is not None:
            stmt = stmt.where(cast(Any, NodeConnectivity.source_node) == source_node)  # type: ignore[arg-type]

        if success is not None:
            stmt = stmt.where(cast(Any, NodeConnectivity.success) == success)  # type: ignore[arg-type]

        stmt = stmt.order_by(desc(cast(Any, NodeConnectivity.measured_at))).limit(limit)  # type: ignore[arg-type]

        result = await db.execute(stmt)
        records = result.scalars().all()

        return [
            ConnectivityRecord(
                id=record.id,
                source_node=record.source_node,
                node_name=record.node_name,
                target_ip=record.target_ip,
                success=record.success,
                latency_ms=record.latency_ms,
                packet_loss=record.packet_loss,
                error_message=record.error_message,
                error_code=record.error_code,
                ping_count=record.ping_count,
                timeout_seconds=record.timeout_seconds,
                measured_at=record.measured_at,
            )
            for record in records
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get connectivity history for node {node_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/connectivity/history", response_model=List[ConnectivityRecord])
async def get_all_connectivity_history(
    limit: int = Query(
        100, description="Maximum number of records to return", ge=1, le=1000
    ),
    source_node: Optional[str] = Query(None, description="Filter by source node"),
    target_node: Optional[str] = Query(None, description="Filter by target node"),
    success: Optional[bool] = Query(None, description="Filter by success status"),
    db: AsyncSession = Depends(get_db_session),
) -> List[ConnectivityRecord]:
    """Get all connectivity history with optional filtering.

    Returns the latest connectivity records ordered by measured_at descending.
    By default returns all records (all sources, all targets).
    """
    try:
        stmt = select(NodeConnectivity)

        if source_node is not None:
            stmt = stmt.where(cast(Any, NodeConnectivity.source_node) == source_node)  # type: ignore[arg-type]

        if target_node is not None:
            stmt = stmt.where(cast(Any, NodeConnectivity.node_name) == target_node)  # type: ignore[arg-type]

        if success is not None:
            stmt = stmt.where(cast(Any, NodeConnectivity.success) == success)  # type: ignore[arg-type]

        stmt = stmt.order_by(desc(cast(Any, NodeConnectivity.measured_at))).limit(limit)  # type: ignore[arg-type]

        result = await db.execute(stmt)
        records = result.scalars().all()

        return [
            ConnectivityRecord(
                id=record.id,
                source_node=record.source_node,
                node_name=record.node_name,
                target_ip=record.target_ip,
                success=record.success,
                latency_ms=record.latency_ms,
                packet_loss=record.packet_loss,
                error_message=record.error_message,
                error_code=record.error_code,
                ping_count=record.ping_count,
                timeout_seconds=record.timeout_seconds,
                measured_at=record.measured_at,
            )
            for record in records
        ]

    except Exception as e:
        logger.error(f"Failed to get connectivity history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=NodeStats)
async def get_stats(db: AsyncSession = Depends(get_db_session)) -> NodeStats:
    """Get statistics about all nodes."""
    try:
        # Get node counts
        total_result = await db.execute(select(func.count(cast(Any, NodeSnapshot.id))))  # type: ignore[arg-type]
        total_nodes = total_result.scalar() or 0

        ready_result = await db.execute(
            select(func.count(cast(Any, NodeSnapshot.id))).where(
                cast(Any, NodeSnapshot.ready) == True
            )  # type: ignore[arg-type]
        )
        ready_nodes = ready_result.scalar() or 0

        unavailable_result = await db.execute(
            select(func.count(cast(Any, NodeSnapshot.id))).where(
                cast(Any, NodeSnapshot.unavailable_since).is_not(None)
            )  # type: ignore[arg-type]
        )
        unavailable_nodes = unavailable_result.scalar() or 0

        tailscale_result = await db.execute(
            select(func.count(cast(Any, NodeSnapshot.id))).where(
                cast(Any, NodeSnapshot.tailscale_ip).is_not(None)
            )  # type: ignore[arg-type]
        )
        nodes_with_tailscale = tailscale_result.scalar() or 0

        # Get average latency from recent connectivity checks (last 24 hours)
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        latency_result = await db.execute(
            select(func.avg(cast(Any, NodeConnectivity.latency_ms))).where(  # type: ignore[arg-type]
                cast(Any, NodeConnectivity.measured_at) >= since,  # type: ignore[arg-type]
                cast(Any, NodeConnectivity.success) == True,  # type: ignore[arg-type]
                cast(Any, NodeConnectivity.latency_ms).is_not(None),  # type: ignore[arg-type]
            )
        )
        avg_latency = latency_result.scalar()

        return NodeStats(
            total_nodes=total_nodes,
            ready_nodes=ready_nodes,
            not_ready_nodes=total_nodes - ready_nodes - unavailable_nodes,
            unavailable_nodes=unavailable_nodes,
            nodes_with_tailscale=nodes_with_tailscale,
            average_latency_ms=avg_latency,
        )

    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Pydantic models for agent connectivity reports
class ConnectivityMeasurement(BaseModel):
    """Single connectivity measurement from an agent."""

    target_node: str
    target_ip: str
    success: bool
    latency_ms: Optional[float] = None
    packet_loss: Optional[float] = None
    error_message: Optional[str] = None
    measured_at: str  # ISO format string


class ConnectivityReport(BaseModel):
    """Connectivity report from a node agent."""

    source_node: str
    location: Optional[str] = None
    measurements: List[ConnectivityMeasurement]


class ConnectivityReportResponse(BaseModel):
    """Response to a connectivity report."""

    accepted: int
    rejected: int
    message: str


@app.post("/connectivity/report", response_model=ConnectivityReportResponse)
async def report_connectivity(
    report: ConnectivityReport, db: AsyncSession = Depends(get_db_session)
) -> ConnectivityReportResponse:
    """Receive connectivity measurements from node agents.

    This endpoint is called by the node-agent DaemonSet running on each node
    to report node-to-node ping measurements.
    """
    try:
        accepted = 0
        rejected = 0

        for measurement in report.measurements:
            try:
                # Parse the timestamp
                try:
                    measured_at = datetime.fromisoformat(
                        measurement.measured_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    measured_at = datetime.now(timezone.utc)

                # Create connectivity record
                record = NodeConnectivity(
                    node_name=measurement.target_node,
                    target_ip=measurement.target_ip,
                    source_node=report.source_node,
                    success=measurement.success,
                    latency_ms=measurement.latency_ms,
                    packet_loss=measurement.packet_loss,
                    error_message=measurement.error_message,
                    ping_count=4,  # Default, agent doesn't report this
                    measured_at=measured_at,
                )
                db.add(record)
                accepted += 1

            except Exception as e:
                logger.warning(
                    f"Failed to process measurement for {measurement.target_node}: {e}"
                )
                rejected += 1

        # Try to update the node's location if reported by agent
        if getattr(report, "location", None):
            node_stmt = select(NodeSnapshot).where(
                NodeSnapshot.name == report.source_node
            )
            node_result = await db.execute(node_stmt)
            node = node_result.scalars().first()
            if node and getattr(node, "location", None) != report.location:
                node.location = report.location
                db.add(node)

        await db.commit()

        logger.info(
            f"Received connectivity report from {report.source_node}: {accepted} accepted, {rejected} rejected"
        )

        return ConnectivityReportResponse(
            accepted=accepted,
            rejected=rejected,
            message=f"Processed {accepted + rejected} measurements from {report.source_node}",
        )

    except Exception as e:
        logger.error(f"Failed to process connectivity report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Root endpoint with basic information."""
    return {
        "service": "Kitchen Node Manager",
        "version": "1.0.0",
        "description": "Kubernetes node monitoring and connectivity tracking service",
        "endpoints": {
            "health": "/health",
            "nodes": "/nodes",
            "nodes_dashboard": "/nodes/dashboard",
            "node_detail": "/nodes/{node_name}",
            "connectivity": "/nodes/{node_name}/connectivity",
            "connectivity_report": "/connectivity/report",
            "connectivity_latest": "/connectivity/latest",
            "connectivity_graph": "/connectivity/graph",
            "stats": "/stats",
            "websocket": "/ws",
        },
    }


@app.get("/connectivity/latest", response_model=List[ConnectivitySummary])
async def get_latest_connectivity(
    db: AsyncSession = Depends(get_db_session),
) -> List[ConnectivitySummary]:
    """Get the latest connectivity measurement for all nodes."""
    try:
        # Subquery to get max measured_at per node
        from sqlalchemy import and_

        subq = (
            select(
                NodeConnectivity.node_name,
                func.max(cast(Any, NodeConnectivity.measured_at)).label("max_at"),
            )
            .group_by(NodeConnectivity.node_name)
            .subquery()
        )

        stmt = (
            select(NodeConnectivity)
            .join(
                subq,
                and_(
                    NodeConnectivity.node_name == subq.c.node_name,
                    cast(Any, NodeConnectivity.measured_at) == subq.c.max_at,
                ),
            )
            .order_by(NodeConnectivity.node_name)
        )

        result = await db.execute(stmt)
        records = result.scalars().all()

        return [
            ConnectivitySummary(
                source_node=getattr(r, "source_node", "node-manager"),
                node_name=r.node_name,
                target_ip=r.target_ip,
                success=r.success,
                latency_ms=r.latency_ms,
                packet_loss=r.packet_loss,
                measured_at=r.measured_at,
            )
            for r in records
        ]

    except Exception as e:
        logger.error(f"Failed to get latest connectivity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/connectivity/graph", response_model=ConnectivityGraph)
async def get_connectivity_graph(
    db: AsyncSession = Depends(get_db_session),
) -> ConnectivityGraph:
    """Get connectivity data in graph format for visualization."""
    try:
        from sqlalchemy import and_

        # Get all nodes
        nodes_stmt = select(NodeSnapshot).order_by(NodeSnapshot.name)
        nodes_result = await db.execute(nodes_stmt)
        nodes = nodes_result.scalars().all()

        # Build graph nodes
        graph_nodes: List[GraphNode] = []

        # Add the node-manager as the central hub
        graph_nodes.append(
            GraphNode(
                id="node-manager",
                label="Node Manager",
                type="hub",
                status="healthy",
                ready=True,
                ip=None,
                kubelet_version=None,
                cpu_capacity=None,
                memory_capacity=None,
            )
        )

        # Add cluster nodes
        for node in nodes:
            # Determine status
            if node.unavailable_since:
                status = "unreachable"
            elif not node.ready:
                status = "degraded"
            else:
                status = "healthy"

            # Determine location based on node name pattern or DB field if present
            location = getattr(node, "location", None)
            if not location:
                import re

                if node.name in ["abja", "desktop"] or "lab" in node.name.lower():
                    location = "lab"
                elif (
                    "azure" in node.name.lower()
                    or "stan" in node.name.lower()
                    or re.search(r"-[a-z0-9]{6}$", node.name)
                ):
                    location = "azure (North Europe)"
                else:
                    location = "lab"

            graph_nodes.append(
                GraphNode(
                    id=node.name,
                    label=node.name,
                    type="node",
                    status=status,
                    ready=node.ready,
                    ip=node.tailscale_ip or node.internal_ip,
                    kubelet_version=node.kubelet_version,
                    cpu_capacity=node.cpu_capacity,
                    memory_capacity=node.memory_capacity,
                    location=location,
                )
            )

        # Get latest connectivity for edges between each source-target pair
        subq = (
            select(
                NodeConnectivity.source_node,
                NodeConnectivity.node_name,
                func.max(cast(Any, NodeConnectivity.measured_at)).label("max_at"),
            )
            .group_by(NodeConnectivity.source_node, NodeConnectivity.node_name)
            .subquery()
        )

        conn_stmt = select(NodeConnectivity).join(
            subq,
            and_(
                NodeConnectivity.source_node == subq.c.source_node,
                NodeConnectivity.node_name == subq.c.node_name,
                cast(Any, NodeConnectivity.measured_at) == subq.c.max_at,
            ),
        )

        conn_result = await db.execute(conn_stmt)
        connectivity_records = conn_result.scalars().all()

        # Build edges from node-manager to each node
        valid_node_ids = {n.id for n in graph_nodes}
        graph_edges: List[GraphEdge] = []
        for conn in connectivity_records:
            source = getattr(conn, "source_node", "node-manager")

            # Only include edges if BOTH the source and target are currently valid nodes
            if source in valid_node_ids and conn.node_name in valid_node_ids:
                graph_edges.append(
                    GraphEdge(
                        source=source,
                        target=conn.node_name,
                        latency_ms=conn.latency_ms,
                        success=conn.success,
                        packet_loss=conn.packet_loss,
                        measured_at=conn.measured_at,
                    )
                )

        return ConnectivityGraph(nodes=graph_nodes, edges=graph_edges)

    except Exception as e:
        logger.error(f"Failed to get connectivity graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for live dashboard updates."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle any incoming messages
            try:
                data = await websocket.receive_text()
                # Client can send ping messages to keep connection alive
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await ws_manager.disconnect(websocket)
