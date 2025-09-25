"""Database models for node manager using SQLModel."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Column, Text, DateTime
from sqlalchemy.sql import func


class NodeSnapshot(SQLModel, table=True):
    """Represents a snapshot of a Kubernetes node at a specific time.
    
    Tracks when nodes start and when they become unavailable.
    """
    __tablename__ = "node_snapshots"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255, index=True)
    
    # Node details
    internal_ip: Optional[str] = Field(default=None, max_length=45)  # IPv4/IPv6
    external_ip: Optional[str] = Field(default=None, max_length=45)
    tailscale_ip: Optional[str] = Field(default=None, max_length=45)
    hostname: Optional[str] = Field(default=None, max_length=255)
    
    # Node status
    status: str = Field(max_length=50)  # Ready, NotReady, Unknown
    ready: bool = Field(default=False)
    schedulable: bool = Field(default=True)
    
    # Kubernetes version and runtime info
    kubelet_version: Optional[str] = Field(default=None, max_length=50)
    container_runtime: Optional[str] = Field(default=None, max_length=100)
    os_image: Optional[str] = Field(default=None, max_length=255)
    kernel_version: Optional[str] = Field(default=None, max_length=100)
    
    # Resource capacity and usage
    cpu_capacity: Optional[str] = Field(default=None, max_length=20)
    memory_capacity: Optional[str] = Field(default=None, max_length=20)
    pods_capacity: Optional[int] = Field(default=None)
    
    # Conditions and metadata (JSON strings)
    conditions: Optional[str] = Field(default=None, sa_column=Column(Text))
    labels: Optional[str] = Field(default=None, sa_column=Column(Text))
    annotations: Optional[str] = Field(default=None, sa_column=Column(Text))
    
    # Timestamps
    node_created_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    first_seen_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now()))
    last_seen_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now()))
    unavailable_since: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    
    def __repr__(self) -> str:
        return f"<NodeSnapshot(name='{self.name}', status='{self.status}', last_seen='{self.last_seen_at}')>"


class NodeConnectivity(SQLModel, table=True):
    """Records connectivity measurements to nodes via direct ping.
    
    Tracks round-trip latency and connection success/failure over time.
    """
    __tablename__ = "node_connectivity"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    node_name: str = Field(max_length=255, index=True)
    target_ip: str = Field(max_length=45)  # IP used for ping
    
    # Connectivity measurement
    success: bool = Field()
    latency_ms: Optional[float] = Field(default=None)  # Round-trip time in milliseconds
    packet_loss: Optional[float] = Field(default=None)  # Percentage packet loss
    
    # Error information
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))
    error_code: Optional[int] = Field(default=None)
    
    # Measurement metadata
    ping_count: int = Field(default=4)  # Number of ping packets sent
    timeout_seconds: int = Field(default=5)
    
    # Timestamp
    measured_at: datetime = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now(), index=True))
    
    def __repr__(self) -> str:
        status = f"{self.latency_ms}ms" if self.success else "failed"
        return f"<NodeConnectivity(node='{self.node_name}', target='{self.target_ip}', status='{status}')>"