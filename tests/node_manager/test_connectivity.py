"""Tests for connectivity checking functionality."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, Mock

import pytest

from kitchen.node_manager.worker import NodeMonitorWorker


@pytest.fixture
def connectivity_checker():
    """Create a NodeMonitorWorker instance for testing connectivity."""
    return NodeMonitorWorker(
        monitoring_interval=60,
        connectivity_interval=300,
        ping_count=2,
        ping_timeout=3
    )


def test_connectivity_checker_init():
    """Test NodeMonitorWorker initialization with ping parameters."""
    checker = NodeMonitorWorker(ping_count=4, ping_timeout=5)
    assert checker.ping_count == 4
    assert checker.ping_timeout == 5


def test_connectivity_checker_defaults():
    """Test NodeMonitorWorker default values."""
    checker = NodeMonitorWorker()
    assert checker.ping_count == 4
    assert checker.ping_timeout == 5


def test_parse_ping_output_success(connectivity_checker):
    """Test parsing successful ping output."""
    stdout = """PING 192.168.1.10 (192.168.1.10): 56 data bytes
64 bytes from 192.168.1.10: icmp_seq=0 ttl=64 time=12.5 ms
64 bytes from 192.168.1.10: icmp_seq=1 ttl=64 time=13.2 ms

--- 192.168.1.10 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss
round-trip min/avg/max/stddev = 12.5/12.85/13.2/0.35 ms"""
    
    result = connectivity_checker._parse_ping_output(
        stdout, "", 0, datetime.now(timezone.utc)
    )
    
    assert result["success"] is True
    assert result["latency_ms"] == pytest.approx(12.85, rel=1e-2)  # (12.5 + 13.2) / 2
    assert result["packet_loss"] == 0.0
    assert result["error_message"] is None


def test_parse_ping_output_partial_success(connectivity_checker):
    """Test parsing ping output with packet loss."""
    stdout = """PING 192.168.1.10 (192.168.1.10): 56 data bytes
64 bytes from 192.168.1.10: icmp_seq=0 ttl=64 time=12.5 ms

--- 192.168.1.10 ping statistics ---
2 packets transmitted, 1 received, 50% packet loss"""
    
    result = connectivity_checker._parse_ping_output(
        stdout, "", 0, datetime.now(timezone.utc)
    )
    
    assert result["success"] is True
    assert result["latency_ms"] == 12.5
    assert result["packet_loss"] == 50.0  # From summary line
    assert result["error_message"] is None


def test_parse_ping_output_failure(connectivity_checker):
    """Test parsing failed ping output."""
    result = connectivity_checker._parse_ping_output(
        "", "timeout", 1, datetime.now(timezone.utc)
    )
    
    assert result["success"] is False
    assert result["latency_ms"] is None
    assert result["packet_loss"] == 100.0
    assert result["error_message"] == "timeout"
    assert result["error_code"] == 1


def test_parse_ping_output_no_responses(connectivity_checker):
    """Test parsing ping output with no successful responses."""
    stdout = """PING 192.168.1.10 (192.168.1.10): 56 data bytes

--- 192.168.1.10 ping statistics ---
2 packets transmitted, 0 received, 100% packet loss"""
    
    result = connectivity_checker._parse_ping_output(
        stdout, "", 0, datetime.now(timezone.utc)
    )
    
    assert result["success"] is False
    assert result["latency_ms"] is None
    assert result["packet_loss"] == 100.0
    assert result["error_message"] == "No successful pings"


@pytest.mark.asyncio
async def test_ping_node_command_not_found(connectivity_checker):
    """Test _ping_node when ping command is not found."""
    with patch('asyncio.create_subprocess_exec', side_effect=FileNotFoundError):
        result = await connectivity_checker._ping_node("192.168.1.10", "test-node")
    
    assert result["success"] is False
    assert result["error_message"] == "ping command not found"
    assert result["error_code"] == 127


@pytest.mark.asyncio 
async def test_ping_node_timeout(connectivity_checker):
    """Test _ping_node with timeout."""
    mock_process = Mock()
    mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_process.kill = AsyncMock()
    mock_process.wait = AsyncMock()
    
    with patch('asyncio.create_subprocess_exec', return_value=mock_process), \
         patch('asyncio.wait_for', side_effect=asyncio.TimeoutError):
        
        result = await connectivity_checker._ping_node("192.168.1.10", "test-node")
    
    assert result["success"] is False
    assert "timeout" in result["error_message"].lower()
    assert result["error_code"] == -1


@pytest.mark.asyncio
async def test_batch_ping_nodes_empty(connectivity_checker):
    """Test _batch_ping_nodes with empty input."""
    result = await connectivity_checker._batch_ping_nodes({})
    assert result == {}


@pytest.mark.asyncio
async def test_batch_ping_nodes_success(connectivity_checker):
    """Test _batch_ping_nodes with successful pings."""
    mock_result = {
        "success": True,
        "latency_ms": 12.5,
        "packet_loss": 0.0,
        "error_message": None,
        "error_code": None,
        "measured_at": datetime.now(timezone.utc),
    }
    
    with patch.object(connectivity_checker, '_ping_node', return_value=mock_result):
        targets = {"node1": "192.168.1.10", "node2": "192.168.1.11"}
        results = await connectivity_checker._batch_ping_nodes(targets)
    
    assert len(results) == 2
    assert "node1" in results
    assert "node2" in results
    assert results["node1"]["success"] is True
    assert results["node2"]["success"] is True


def test_is_ping_available_true():
    """Test _is_ping_available when ping is available."""
    with patch('shutil.which', return_value='/bin/ping'):
        checker = NodeMonitorWorker()
        assert checker._is_ping_available() is True


def test_is_ping_available_false():
    """Test _is_ping_available when ping is not available."""
    with patch('shutil.which', return_value=None):
        checker = NodeMonitorWorker()
        assert checker._is_ping_available() is False
def test_is_ping_available_exception():
    """Test _is_ping_available when shutil.which raises exception."""
    with patch('shutil.which', side_effect=Exception("test error")):
        checker = NodeMonitorWorker()
        assert checker._is_ping_available() is False