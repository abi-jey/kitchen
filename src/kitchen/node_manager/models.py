"""Database models for node manager."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, Boolean, Integer, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

Base = declarative_base()


class NodeSnapshot(Base):
    """Represents a snapshot of a Kubernetes node at a specific time.
    
    Tracks when nodes start and when they become unavailable.
    """
    __tablename__ = "node_snapshots"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Node details
    internal_ip: Mapped[Optional[str]] = mapped_column(String(45))  # IPv4/IPv6
    external_ip: Mapped[Optional[str]] = mapped_column(String(45))
    tailscale_ip: Mapped[Optional[str]] = mapped_column(String(45))
    hostname: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Node status
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # Ready, NotReady, Unknown
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    schedulable: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Kubernetes version and runtime info
    kubelet_version: Mapped[Optional[str]] = mapped_column(String(50))
    container_runtime: Mapped[Optional[str]] = mapped_column(String(100))
    os_image: Mapped[Optional[str]] = mapped_column(String(255))
    kernel_version: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Resource capacity and usage
    cpu_capacity: Mapped[Optional[str]] = mapped_column(String(20))
    memory_capacity: Mapped[Optional[str]] = mapped_column(String(20))
    pods_capacity: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Conditions and metadata
    conditions: Mapped[Optional[str]] = mapped_column(Text)  # JSON string of node conditions
    labels: Mapped[Optional[str]] = mapped_column(Text)  # JSON string of labels
    annotations: Mapped[Optional[str]] = mapped_column(Text)  # JSON string of annotations
    
    # Timestamps
    node_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    unavailable_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    def __repr__(self) -> str:
        return f"<NodeSnapshot(name='{self.name}', status='{self.status}', last_seen='{self.last_seen_at}')>"


class NodeConnectivity(Base):
    """Records connectivity measurements to nodes via Tailscale ping.
    
    Tracks round-trip latency and connection success/failure over time.
    """
    __tablename__ = "node_connectivity"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_ip: Mapped[str] = mapped_column(String(45), nullable=False)  # IP used for ping
    
    # Connectivity measurement
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)  # Round-trip time in milliseconds
    packet_loss: Mapped[Optional[float]] = mapped_column(Float)  # Percentage packet loss
    
    # Error information
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_code: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Measurement metadata
    ping_count: Mapped[int] = mapped_column(Integer, default=4)  # Number of ping packets sent
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5)
    
    # Timestamp
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    def __repr__(self) -> str:
        status = f"{self.latency_ms}ms" if self.success else "failed"
        return f"<NodeConnectivity(node='{self.node_name}', target='{self.target_ip}', status='{status}')>"