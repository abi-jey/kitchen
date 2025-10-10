"""Worker service for periodic node monitoring."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kitchen.node_manager.database import AsyncSessionLocal
from kitchen.node_manager.k8s_client import K8sClient
from kitchen.node_manager.connectivity import DirectConnectivityChecker
from kitchen.node_manager.models import NodeSnapshot, NodeConnectivity

logger = logging.getLogger(__name__)


class NodeMonitorWorker:
    """Background worker for monitoring Kubernetes nodes and connectivity."""
    
    def __init__(
        self,
        monitoring_interval: int = 60,  # seconds
        connectivity_interval: int = 300,  # seconds
        ping_count: int = 4,
        ping_timeout: int = 5,
    ) -> None:
        """Initialize the node monitor worker.
        
        Args:
            monitoring_interval: How often to check node status (seconds)
            connectivity_interval: How often to ping nodes (seconds) 
            ping_count: Number of ping packets per connectivity check
            ping_timeout: Timeout for ping operations (seconds)
        """
        self.monitoring_interval = monitoring_interval
        self.connectivity_interval = connectivity_interval
        
        self.k8s_client = K8sClient()
        self.connectivity_checker = DirectConnectivityChecker(
            ping_count=ping_count,
            timeout_seconds=ping_timeout
        )
        
        self._monitoring_task: Optional[asyncio.Task] = None
        self._connectivity_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info(f"NodeMonitorWorker initialized with {monitoring_interval}s monitoring, {connectivity_interval}s connectivity intervals")
    
    async def start(self) -> None:
        """Start the background monitoring tasks."""
        if self._running:
            logger.warning("Worker is already running")
            return
        
        self._running = True
        logger.info("Starting node monitor worker")
        
        # Start monitoring tasks
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        self._connectivity_task = asyncio.create_task(self._connectivity_loop(self.connectivity_interval))
        
        logger.info("Node monitor worker started successfully")
    
    async def stop(self) -> None:
        """Stop the background monitoring tasks."""
        if not self._running:
            return
        
        logger.info("Stopping node monitor worker")
        self._running = False
        
        # Cancel tasks
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        if self._connectivity_task:
            self._connectivity_task.cancel()
            try:
                await self._connectivity_task
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
            
            # Wait for next interval
            if self._running:
                await asyncio.sleep(self.monitoring_interval)
        
        logger.info("Node monitoring loop stopped")

    async def _connectivity_loop(self, delay: float) -> None:
        """Main loop for connectivity monitoring."""
        logger.info("Starting connectivity monitoring loop")
        
        # Wait a bit before starting connectivity checks to let node monitoring initialize

        while self._running:
            try:
                await self._check_node_connectivity()
            except Exception as e:
                logger.error(f"Error in connectivity loop: {e}", exc_info=True)
            await asyncio.sleep(delay)
        
        logger.info("Connectivity monitoring loop stopped")
    
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
                        await self._update_existing_node(session, existing_node, node_data, current_time)
                    else:
                        # Create new node snapshot
                        await self._create_new_node_snapshot(session, node_data, current_time)
                
                # Mark nodes as unavailable if they're no longer in Kubernetes
                await self._mark_missing_nodes_unavailable(session, processed_nodes, current_time)
                
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
        current_time: datetime
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
        self, 
        session: AsyncSession, 
        node_data: Dict[str, Any],
        current_time: datetime
    ) -> None:
        """Create a new node snapshot."""
        node_snapshot = NodeSnapshot(
            first_seen_at=current_time,
            last_seen_at=current_time,
            **node_data
        )
        session.add(node_snapshot)
        logger.info(f"Created new node snapshot for {node_data['name']}")
    
    async def _mark_missing_nodes_unavailable(
        self, 
        session: AsyncSession, 
        processed_nodes: set, 
        current_time: datetime
    ) -> None:
        """Mark nodes as unavailable if they're missing from current scan."""
        # Find nodes that exist in DB but weren't seen in current scan
        stmt = select(NodeSnapshot).where(
            ~NodeSnapshot.name.in_(processed_nodes),
            NodeSnapshot.unavailable_since.is_(None)
        )
        result = await session.execute(stmt)
        missing_nodes = result.scalars().all()
        
        for node in missing_nodes:
            node.unavailable_since = current_time
            logger.warning(f"Marked node {node.name} as unavailable")
    
    async def _check_node_connectivity(self) -> None:
        """Check connectivity to all nodes via direct ping."""
        try:
            # Get nodes with IP addresses for pinging
            async with AsyncSessionLocal() as session:
                stmt = select(NodeSnapshot).where(
                    NodeSnapshot.unavailable_since.is_(None)  # Only ping available nodes
                )
                result = await session.execute(stmt)
                nodes = result.scalars().all()
                
                if not nodes:
                    logger.info("No nodes available for connectivity check")
                    return
                
                # Build target list (prefer Tailscale IPs if available, otherwise use internal IPs)
                ping_targets = {}
                for node in nodes:
                    target_ip = node.tailscale_ip or node.internal_ip
                    if target_ip:
                        ping_targets[node.name] = target_ip
                    else:
                        logger.warning(f"No IP address found for node {node.name}")
                
                if not ping_targets:
                    logger.warning("No pingable IP addresses found for any nodes")
                    return
                
            # Perform batch ping
            ping_results = await self.connectivity_checker.batch_ping_nodes(ping_targets)
            
            # Store results in database
            async with AsyncSessionLocal() as session:
                connectivity_records = []
                
                for node_name, result in ping_results.items():
                    target_ip = ping_targets[node_name]
                    
                    record = NodeConnectivity(
                        node_name=node_name,
                        target_ip=target_ip,
                        success=result["success"],
                        latency_ms=result["latency_ms"],
                        packet_loss=result["packet_loss"],
                        error_message=result["error_message"],
                        error_code=result["error_code"],
                        ping_count=self.connectivity_checker.ping_count,
                        timeout_seconds=self.connectivity_checker.timeout_seconds,
                        measured_at=result["measured_at"]
                    )
                    connectivity_records.append(record)
                
                session.add_all(connectivity_records)
                await session.commit()
                
                successful_pings = sum(1 for r in ping_results.values() if r["success"])
                logger.info(f"Connectivity check completed: {successful_pings}/{len(ping_results)} nodes reachable")
                
        except Exception as e:
            logger.error(f"Failed to check node connectivity: {e}", exc_info=True)
            raise
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get worker health and status information."""
        return {
            "worker_running": self._running,
            "monitoring_task_running": self._monitoring_task and not self._monitoring_task.done() if self._monitoring_task else False,
            "connectivity_task_running": self._connectivity_task and not self._connectivity_task.done() if self._connectivity_task else False,
            "kubernetes_healthy": await self.k8s_client.is_healthy(),
            "ping_available": self.connectivity_checker.is_ping_available(),
            "monitoring_interval": self.monitoring_interval,
            "connectivity_interval": self.connectivity_interval,
        }