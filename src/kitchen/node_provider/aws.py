"""AWS node provider implementation."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass

from .base import NodeProvider

logger = logging.getLogger(__name__)

@dataclass
class ASGInstance:
    """Represents an AWS Auto Scaling Group instance."""
    instance_id: str
    name: str
    public_ip: str | None
    private_ip: str | None
    provisioning_state: str
    power_state: str

class AwsNodeProvider(NodeProvider):
    """AWS implementation of the NodeProvider interface.
    Uses AWS CLI (aws) under the hood.
    """
    def __init__(self, *, asg_name: str, region: str = "us-east-1") -> None:
        aws_path = shutil.which("aws")
        if not aws_path:
            raise RuntimeError("AWS CLI ('aws') not found in PATH.")

        self._aws_path = aws_path
        self._asg_name = (asg_name or "").strip()
        self._region = (region or "us-east-1").strip()

        if not self._asg_name:
            raise ValueError("asg_name is required")

        logger.info("Using AWS CLI at: %s (asg=%s region=%s)", self._aws_path, self._asg_name, self._region)

    def scale_pool(self, name: str, size: int) -> str | None:
        if size < 0:
            raise ValueError("size must be >= 0")

        cmd = [
            self._aws_path, "autoscaling", "update-auto-scaling-group",
            "--auto-scaling-group-name", self._asg_name,
            "--min-size", "0",
            "--desired-capacity", str(size),
            "--region", self._region
        ]

        logger.info("AWS scale_pool pool=%s asg=%s size=%s", name, self._asg_name, size)

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"aws autoscaling update failed (exit {result.returncode}): {details}")

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if stdout and stderr:
            return stdout + "\n" + stderr
        return stdout or stderr or None

    def get_capacity(self) -> int:
        cmd = [
            self._aws_path, "autoscaling", "describe-auto-scaling-groups",
            "--auto-scaling-group-names", self._asg_name,
            "--region", self._region,
            "--query", "AutoScalingGroups[0].DesiredCapacity",
            "--output", "json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"aws autoscaling describe failed (exit {result.returncode}): {details}")

        try:
            return int(json.loads(result.stdout.strip()))
        except (ValueError, json.JSONDecodeError, TypeError) as e:
            raise RuntimeError(f"Failed to parse ASG capacity: {e}")

    def list_instances(self) -> list[ASGInstance]:
        # 1. Get instances in ASG
        cmd = [
            self._aws_path, "autoscaling", "describe-auto-scaling-groups",
            "--auto-scaling-group-names", self._asg_name,
            "--region", self._region,
            "--query", "AutoScalingGroups[0].Instances[*].InstanceId",
            "--output", "json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to list ASG instances: {result.stderr or result.stdout}")

        try:
            instance_ids = json.loads(result.stdout.strip())
            if not instance_ids:
                return []
        except (json.JSONDecodeError, TypeError):
            return []

        # 2. Get instance details
        cmd = [
            self._aws_path, "ec2", "describe-instances",
            "--instance-ids", *instance_ids,
            "--region", self._region,
            "--output", "json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to describe EC2 instances: {result.stderr or result.stdout}")
            
        try:
            data = json.loads(result.stdout.strip())
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse EC2 instances JSON: {e}")

        instances = []
        for reservation in data.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                instance_id = inst.get("InstanceId", "")
                
                # Try to find a Name tag, otherwise use InstanceId
                name = instance_id
                for tag in inst.get("Tags", []):
                    if tag.get("Key") == "Name":
                        name = tag.get("Value")
                        break

                public_ip = inst.get("PublicIpAddress")
                private_ip = inst.get("PrivateIpAddress")
                state = inst.get("State", {}).get("Name", "unknown")

                instances.append(ASGInstance(
                    instance_id=instance_id,
                    name=name,
                    public_ip=public_ip,
                    private_ip=private_ip,
                    provisioning_state="Succeeded" if state == "running" else state,
                    power_state=state,
                ))

        return instances
