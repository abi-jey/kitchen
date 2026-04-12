"""Worker service for periodic node monitoring."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from kitchen.node_manager.database import AsyncSessionLocal
from kitchen.node_manager.k8s_client import K8sClient
from kitchen.node_manager.models import NodeSnapshot, NodeConnectivity

logger = logging.getLogger(__name__)


class NodeMonitorWorker:
    """Background worker for monitoring Kubernetes nodes.

    Note: Connectivity checks are handled by DaemonSet agents running on each node.
    This worker only monitors K8s node status.
    """

    def __init__(
        self,
        monitoring_interval: int = 60,  # seconds
        retention_hours: int = 24,  # hours to keep historical data and unavailable nodes
    ) -> None:
        """Initialize the node monitor worker.

        Args:
            monitoring_interval: How often to check node status (seconds)
            retention_hours: How long to keep connectivity history and removed nodes (hours)
        """
        self.monitoring_interval = monitoring_interval
        self.retention_hours = retention_hours

        self.k8s_client = K8sClient()

        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False

        logger.info(
            f"NodeMonitorWorker initialized: monitoring_interval={monitoring_interval}s, retention_hours={retention_hours}h"
        )

    async def start(self) -> None:
        """Start the background monitoring tasks."""
        if self._running:
            logger.warning("Worker is already running")
            return

        self._running = True
        logger.info("Starting node monitor worker")

        # Start monitoring task
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())

        logger.info("Node monitor worker started (connectivity via agents)")

    async def stop(self) -> None:
        """Stop the background monitoring tasks."""
        if not self._running:
            return

        logger.info("Stopping node monitor worker")
        self._running = False

        # Cancel monitoring task
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        logger.info("Node monitor worker stopped")

    async def _monitoring_loop(self) -> None:
        """Main loop for node status monitoring."""
        logger.info("Starting node monitoring loop")

        while self._running:
            try:
                await self._update_node_snapshots()
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)

            try:
                await self._cleanup_old_data()
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}", exc_info=True)

            # Wait for next interval
            if self._running:
                await asyncio.sleep(self.monitoring_interval)

        logger.info("Node monitoring loop stopped")

    async def _update_node_snapshots(self) -> None:
        """Update node snapshots from Kubernetes API."""
        try:
            # Fetch current nodes from Kubernetes
            nodes = await self.k8s_client.get_all_nodes()

            if not nodes:
                logger.warning("No nodes found in Kubernetes cluster")
                return

            async with AsyncSessionLocal() as session:
                current_time = datetime.now(timezone.utc)
                processed_nodes = set()

                for node_data in nodes:
                    node_name = node_data["name"]
                    processed_nodes.add(node_name)

                    # Check if we already have this node
                    stmt = select(NodeSnapshot).where(NodeSnapshot.name == node_name)
                    result = await session.execute(stmt)
                    existing_node = result.scalar_one_or_none()

                    if existing_node:
                        # Update existing node
                        await self._update_existing_node(
                            session, existing_node, node_data, current_time
                        )
                    else:
                        # Create new node snapshot
                        await self._create_new_node_snapshot(
                            session, node_data, current_time
                        )

                # Mark nodes as unavailable if they're no longer in Kubernetes
                await self._mark_missing_nodes_unavailable(
                    session, processed_nodes, current_time
                )

                await session.commit()
                logger.info(f"Updated snapshots for {len(nodes)} nodes")

        except Exception as e:
            logger.error(f"Failed to update node snapshots: {e}", exc_info=True)
            raise

    async def _update_existing_node(
        self,
        session: AsyncSession,
        existing_node: NodeSnapshot,
        node_data: Dict[str, Any],
        current_time: datetime,
    ) -> None:
        """Update an existing node snapshot."""
        # Update all fields
        for key, value in node_data.items():
            if hasattr(existing_node, key):
                setattr(existing_node, key, value)

        # Update timestamps
        existing_node.last_seen_at = current_time

        # Clear unavailable_since if node is back online
        if node_data.get("ready") and existing_node.unavailable_since:
            existing_node.unavailable_since = None
            logger.info(f"Node {existing_node.name} is back online")

    async def _create_new_node_snapshot(
        self, session: AsyncSession, node_data: Dict[str, Any], current_time: datetime
    ) -> None:
        """Create a new node snapshot."""
        node_snapshot = NodeSnapshot(
            first_seen_at=current_time, last_seen_at=current_time, **node_data
        )
        session.add(node_snapshot)
        logger.info(f"Created new node snapshot for {node_data['name']}")

    async def _mark_missing_nodes_unavailable(
        self, session: AsyncSession, processed_nodes: set, current_time: datetime
    ) -> None:
        """Mark nodes as unavailable if they're missing from current scan."""
        # Find nodes that exist in DB but weren't seen in current scan
        stmt = select(NodeSnapshot).where(
            ~NodeSnapshot.name.in_(processed_nodes),
            NodeSnapshot.unavailable_since.is_(None),
        )
        result = await session.execute(stmt)
        missing_nodes = result.scalars().all()

        for node in missing_nodes:
            node.unavailable_since = current_time
            node.ready = False
            node.status = "Unknown"
            logger.warning(
                f"Marked node {node.name} as unavailable (removed from cluster)"
            )

    async def _cleanup_old_data(self) -> None:
        """Remove old nodes and connectivity data based on retention policy."""
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(
                hours=self.retention_hours
            )
            async with AsyncSessionLocal() as session:
                # Clean up old connectivity records
                conn_stmt = delete(NodeConnectivity).where(
                    NodeConnectivity.measured_at < cutoff_time
                )
                conn_result = await session.execute(conn_stmt)

                # Clean up old unavailable nodes
                node_stmt = delete(NodeSnapshot).where(
                    NodeSnapshot.unavailable_since.is_not(None),
                    NodeSnapshot.unavailable_since < cutoff_time,
                )
                node_result = await session.execute(node_stmt)

                await session.commit()

                if conn_result.rowcount > 0 or node_result.rowcount > 0:
                    logger.info(
                        f"Cleanup: Removed {node_result.rowcount} old nodes and {conn_result.rowcount} old connectivity records"
                    )
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}", exc_info=True)

    async def get_health_status(self) -> Dict[str, Any]:
        """Get worker health and status information."""
        return {
            "worker_running": self._running,
            "monitoring_task_running": self._monitoring_task
            and not self._monitoring_task.done()
            if self._monitoring_task
            else False,
            "kubernetes_healthy": await self.k8s_client.is_healthy(),
            "monitoring_interval": self.monitoring_interval,
        }
