"""Kubernetes client for cluster operations."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, cast

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client.rest import ApiException
from kubernetes_asyncio.client.models import (
    V1Node,
    V1NodeList,
    V1ObjectMeta,
    V1NodeSpec,
    V1NodeStatus,
    V1NodeAddress,
    V1NodeCondition,
    V1NodeSystemInfo,
)

logger = logging.getLogger(__name__)


class K8sClient:
    """Client for interacting with Kubernetes cluster resources."""
    
    def __init__(self) -> None:
        """Initialize the Kubernetes client."""
        self.v1: Optional[client.CoreV1Api] = None
        self._config_loaded = False
    
    async def _initialize_client(self) -> None:
        """Initialize the Kubernetes API client."""
        if self._config_loaded:
            return
            
        try:
            # Try to load in-cluster config first (for running in pod)
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes configuration")
        except config.ConfigException:
            try:
                # Fall back to local kubeconfig
                await config.load_kube_config()
                logger.info("Loaded kubeconfig from local environment")
            except config.ConfigException as e:
                logger.error(f"Failed to load Kubernetes configuration: {e}")
                raise
        
        self.v1 = client.CoreV1Api()
        self._config_loaded = True
    
    async def get_all_nodes(self) -> List[Dict[str, Any]]:
        """Fetch all nodes from the Kubernetes cluster.
        
        Returns:
            List of node dictionaries with processed information.
        """
        await self._initialize_client()
        assert self.v1 is not None, "Kubernetes client not initialized"
        
        try:
            nodes_response: V1NodeList = await self.v1.list_node()
            assert nodes_response is not None, "Node list response is None"
            assert nodes_response.items is not None, "Node list items is None"
            nodes = []
            
            for node in nodes_response.items:
                node_data = self._process_node(node)
                nodes.append(node_data)
            
            logger.info(f"Retrieved {len(nodes)} nodes from Kubernetes")
            return nodes
            
        except ApiException as e:
            logger.error(f"Failed to fetch nodes from Kubernetes: {e}")
            raise
    
    def _process_node(self, node: V1Node) -> Dict[str, Any]:
        """Process a Kubernetes node object into a dictionary.
        
        Args:
            node: Kubernetes V1Node object
            
        Returns:
            Dictionary with processed node information
        """
        assert node is not None, "Node object is None"
        
        # Extract basic metadata
        metadata = cast(V1ObjectMeta, node.metadata)
        assert metadata is not None, "Node metadata is None"
        
        spec = cast(V1NodeSpec, node.spec)
        assert spec is not None, "Node spec is None"
        
        status = cast(V1NodeStatus, node.status)
        assert status is not None, "Node status is None"
        
        # Extract IP addresses
        internal_ip = None
        external_ip = None
        
        if status.addresses:
            for addr in status.addresses:
                assert addr is not None, "Address object is None"
                addr_typed = cast(V1NodeAddress, addr)
                if addr_typed.type == "InternalIP":
                    internal_ip = addr_typed.address
                elif addr_typed.type == "ExternalIP":
                    external_ip = addr_typed.address
        
        # Determine node readiness
        ready = False
        node_conditions: List[Dict[str, Any]] = []
        
        if status.conditions:
            for condition in status.conditions:
                assert condition is not None, "Condition object is None"
                condition_typed = cast(V1NodeCondition, condition)
                condition_dict = {
                    "type": condition_typed.type,
                    "status": condition_typed.status,
                    "last_heartbeat_time": condition_typed.last_heartbeat_time.isoformat() if condition_typed.last_heartbeat_time else None,  # fmt: skip
                    "last_transition_time": condition_typed.last_transition_time.isoformat() if condition_typed.last_transition_time else None,  # fmt: skip
                    "reason": condition_typed.reason,
                    "message": condition_typed.message,
                }
                node_conditions.append(condition_dict)
                
                if condition_typed.type == "Ready" and condition_typed.status == "True":
                    ready = True
        
        # Extract node info
        assert status.node_info is not None, "Node is not parsed correctly, missing system info"
        node_info: V1NodeSystemInfo = status.node_info
        
        # Extract resource capacity
        capacity: Dict[str, Any] = status.capacity or {}

        # Check if node is schedulable
        schedulable = not (spec.unschedulable or False)
        
        # Extract Tailscale IP from labels or annotations if available
        tailscale_ip = None
        labels = metadata.labels or {}
        annotations = metadata.annotations or {}
        
        # Common Tailscale label/annotation patterns
        tailscale_keys = [
            "tailscale.com/ip",
            "tailscale/ip", 
            "tailscale.io/ip",
            "node.tailscale.com/ip"
        ]
        
        for key in tailscale_keys:
            if key in labels:
                tailscale_ip = labels[key]
                break
            if key in annotations:
                tailscale_ip = annotations[key]
                break
        
        return {
            "name": metadata.name,
            "uid": metadata.uid,
            "internal_ip": internal_ip,
            "external_ip": external_ip,
            "tailscale_ip": tailscale_ip,
            "hostname": labels.get("kubernetes.io/hostname"),
            "ready": ready,
            "schedulable": schedulable,
            "status": "Ready" if ready else "NotReady",
            "kubelet_version": node_info.kubelet_version,
            "container_runtime_version": node_info.container_runtime_version,
            "os_image": node_info.os_image,
            "kernel_version": node_info.kernel_version,
            "cpu_capacity": capacity.get("cpu"),
            "memory_capacity": capacity.get("memory"),
            "pods_capacity": int(capacity.get("pods", 0)) if capacity.get("pods") else None,
            "conditions": json.dumps(node_conditions),
            "labels": json.dumps(labels),
            "annotations": json.dumps(annotations),
            "node_created_at": metadata.creation_timestamp.replace(tzinfo=None) if metadata.creation_timestamp else None,
        }
    
    async def is_healthy(self) -> bool:
        """Check if the Kubernetes client connection is healthy.
        
        Returns:
            True if connection is healthy, False otherwise.
        """
        if not self._config_loaded:
            try:
                await self._initialize_client()
            except Exception:
                return False
        
        if self.v1 is None:
            return False
        
        try:
            # Simple API call to test connectivity
            assert self.v1 is not None, "Kubernetes client became None during health check"
            # Use a simple API call to test connectivity - list nodes with limit 1
            await self.v1.list_node(limit=1)
            return True
        except Exception as e:
            logger.warning(f"Kubernetes client health check failed: {e}")
            return False
    
    async def close(self) -> None:
        """Close the Kubernetes client and cleanup resources."""
        if self.v1 is not None:
            await self.v1.api_client.close()
            logger.info("Kubernetes client closed")
    
    async def __aenter__(self) -> "K8sClient":
        """Async context manager entry."""
        await self._initialize_client()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()