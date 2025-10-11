"""Tests for node manager database models."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from kitchen.node_manager.models import NodeSnapshot, NodeConnectivity


def test_node_snapshot_creation():
    """Test NodeSnapshot model creation."""
    node = NodeSnapshot(
        name="test-node",
        status="Ready",
        ready=True,
        schedulable=True,
        internal_ip="10.0.1.10",
        tailscale_ip="100.64.1.10",
        kubelet_version="v1.29.0",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    
    assert node.name == "test-node"
    assert node.status == "Ready"
    assert node.ready is True
    assert node.schedulable is True
    assert node.internal_ip == "10.0.1.10"
    assert node.tailscale_ip == "100.64.1.10"
    assert node.kubelet_version == "v1.29.0"
    assert isinstance(node.first_seen_at, datetime)
    assert isinstance(node.last_seen_at, datetime)


def test_node_snapshot_repr():
    """Test NodeSnapshot string representation."""
    node = NodeSnapshot(
        name="test-node",
        status="Ready",
        ready=True,
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    
    repr_str = repr(node)
    assert "NodeSnapshot" in repr_str
    assert "test-node" in repr_str
    assert "Ready" in repr_str


def test_node_connectivity_creation():
    """Test NodeConnectivity model creation."""
    connectivity = NodeConnectivity(
        node_name="test-node",
        target_ip="10.0.0.1",
        success=True,
        latency_ms=10.5,
        packet_loss=0.0,
        ping_count=4,
        timeout_seconds=5,
        measured_at=datetime.now(timezone.utc),
    )
    
    assert connectivity.node_name == "test-node"
    assert connectivity.target_ip == "100.64.1.10"
    assert connectivity.success is True
    assert connectivity.latency_ms == 12.5
    assert connectivity.packet_loss == 0.0
    assert connectivity.ping_count == 4
    assert connectivity.timeout_seconds == 5
    assert isinstance(connectivity.measured_at, datetime)


def test_node_connectivity_repr():
    """Test NodeConnectivity string representation."""
    connectivity = NodeConnectivity(
        node_name="test-node",
        target_ip="100.64.1.10",
        success=True,
        latency_ms=12.5,
        measured_at=datetime.now(timezone.utc),
    )
    
    repr_str = repr(connectivity)
    assert "NodeConnectivity" in repr_str
    assert "test-node" in repr_str
    assert "100.64.1.10" in repr_str
    assert "12.5ms" in repr_str


def test_node_connectivity_failed_repr():
    """Test NodeConnectivity string representation for failed ping."""
    connectivity = NodeConnectivity(
        node_name="test-node",
        target_ip="100.64.1.10",
        success=False,
        error_message="Timeout",
        measured_at=datetime.now(timezone.utc),
    )
    
    repr_str = repr(connectivity)
    assert "NodeConnectivity" in repr_str
    assert "test-node" in repr_str
    assert "100.64.1.10" in repr_str
    assert "failed" in repr_str