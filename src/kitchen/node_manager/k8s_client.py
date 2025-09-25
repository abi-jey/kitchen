"""Kubernetes client for node monitoring."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


class KubernetesNodeClient:
    """Client for interacting with Kubernetes nodes."""
    
    def __init__(self) -> None:
        """Initialize the Kubernetes client."""
        self.v1 = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize the Kubernetes API client."""
        try:
            # Try to load in-cluster config first (for running in pod)
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes configuration")
        except config.ConfigException:
            try:
                # Fall back to local kubeconfig
                config.load_kube_config()
                logger.info("Loaded kubeconfig from local environment")
            except config.ConfigException as e:
                logger.error(f"Failed to load Kubernetes configuration: {e}")
                raise
        
        self.v1 = client.CoreV1Api()
    
    async def get_all_nodes(self) -> List[Dict[str, Any]]:
        """Fetch all nodes from the Kubernetes cluster.
        
        Returns:
            List of node dictionaries with processed information.
        """
        if not self.v1:
            raise RuntimeError("Kubernetes client not initialized")
        
        try:
            nodes_response = self.v1.list_node()
            nodes = []
            
            for node in nodes_response.items:
                node_data = self._process_node(node)
                nodes.append(node_data)
            
            logger.info(f"Retrieved {len(nodes)} nodes from Kubernetes")
            return nodes
            
        except ApiException as e:
            logger.error(f"Failed to fetch nodes from Kubernetes: {e}")
            raise
    
    def _process_node(self, node: client.V1Node) -> Dict[str, Any]:
        """Process a Kubernetes node object into a dictionary.
        
        Args:
            node: Kubernetes V1Node object
            
        Returns:
            Dictionary with processed node information
        """
        # Extract basic metadata
        metadata = node.metadata
        spec = node.spec
        status = node.status
        
        # Extract IP addresses
        internal_ip = None
        external_ip = None
        
        if status.addresses:
            for addr in status.addresses:
                if addr.type == "InternalIP":
                    internal_ip = addr.address
                elif addr.type == "ExternalIP":
                    external_ip = addr.address
        
        # Determine node readiness
        ready = False
        node_conditions = []
        
        if status.conditions:
            for condition in status.conditions:
                condition_dict = {
                    "type": condition.type,
                    "status": condition.status,
                    "last_heartbeat_time": condition.last_heartbeat_time.isoformat() if condition.last_heartbeat_time else None,
                    "last_transition_time": condition.last_transition_time.isoformat() if condition.last_transition_time else None,
                    "reason": condition.reason,
                    "message": condition.message,
                }
                node_conditions.append(condition_dict)
                
                if condition.type == "Ready" and condition.status == "True":
                    ready = True
        
        # Extract node info
        node_info = status.node_info or {}
        
        # Extract resource capacity
        capacity = status.capacity or {}
        
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
            "kubelet_version": node_info.get("kubeletVersion"),
            "container_runtime": node_info.get("containerRuntimeVersion"),
            "os_image": node_info.get("osImage"),
            "kernel_version": node_info.get("kernelVersion"),
            "cpu_capacity": capacity.get("cpu"),
            "memory_capacity": capacity.get("memory"),
            "pods_capacity": int(capacity.get("pods", 0)) if capacity.get("pods") else None,
            "conditions": json.dumps(node_conditions),
            "labels": json.dumps(labels),
            "annotations": json.dumps(annotations),
            "node_created_at": metadata.creation_timestamp.replace(tzinfo=None) if metadata.creation_timestamp else None,
        }
    
    def is_healthy(self) -> bool:
        """Check if the Kubernetes client connection is healthy.
        
        Returns:
            True if connection is healthy, False otherwise.
        """
        if not self.v1:
            return False
        
        try:
            # Simple API call to test connectivity
            self.v1.get_api_resources()
            return True
        except Exception as e:
            logger.warning(f"Kubernetes client health check failed: {e}")
            return False