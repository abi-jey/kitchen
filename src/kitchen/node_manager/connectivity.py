"""Direct ping connectivity monitoring."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class DirectConnectivityChecker:
    """Handles direct ping connectivity measurements."""
    
    # Regex pattern to parse ping output - looks for time measurements in ping reply lines
    PING_PATTERN = re.compile(
        r"(?:time[=<]|time=)(\d+(?:\.\d+)?)(?:\s*ms)?",
        re.IGNORECASE
    )
    
    def __init__(self, ping_count: int = 4, timeout_seconds: int = 5) -> None:
        """Initialize the connectivity checker.
        
        Args:
            ping_count: Number of ping packets to send
            timeout_seconds: Timeout for ping operation
        """
        self.ping_count = ping_count
        self.timeout_seconds = timeout_seconds
    
    async def ping_node(self, target_ip: str, node_name: str = "") -> Dict[str, Any]:
        """Ping a node directly and measure connectivity.
        
        Args:
            target_ip: IP address to ping
            node_name: Name of the node (for logging)
            
        Returns:
            Dictionary with connectivity measurement results
        """
        logger.debug(f"Pinging {target_ip} ({node_name}) with {self.ping_count} packets")
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Build direct ping command
            cmd = [
                "ping",
                "-c", str(self.ping_count),
                "-W", str(self.timeout_seconds),
                target_ip
            ]
            
            # Execute ping with timeout
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds + 5  # Extra buffer for command timeout
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                    await process.wait()
                except:
                    pass
                
                return {
                    "success": False,
                    "latency_ms": None,
                    "packet_loss": 100.0,
                    "error_message": f"Ping timeout after {self.timeout_seconds + 5} seconds",
                    "error_code": -1,
                    "measured_at": start_time,
                }
            
            # Parse results
            return self._parse_ping_output(
                stdout.decode("utf-8"),
                stderr.decode("utf-8"),
                process.returncode,
                start_time
            )
            
        except FileNotFoundError:
            return {
                "success": False,
                "latency_ms": None,
                "packet_loss": 100.0,
                "error_message": "ping command not found",
                "error_code": 127,
                "measured_at": start_time,
            }
        except Exception as e:
            logger.error(f"Unexpected error pinging {target_ip}: {e}")
            return {
                "success": False,
                "latency_ms": None,
                "packet_loss": 100.0,
                "error_message": str(e),
                "error_code": -1,
                "measured_at": start_time,
            }
    
    def _parse_ping_output(
        self, 
        stdout: str, 
        stderr: str, 
        return_code: int,
        start_time: datetime
    ) -> Dict[str, Any]:
        """Parse direct ping command output.
        
        Args:
            stdout: Standard output from ping command
            stderr: Standard error from ping command
            return_code: Process return code
            start_time: When the ping was started
            
        Returns:
            Dictionary with parsed ping results
        """
        if return_code != 0:
            # Command failed
            error_msg = stderr.strip() or stdout.strip() or f"Command failed with code {return_code}"
            return {
                "success": False,
                "latency_ms": None,
                "packet_loss": 100.0,
                "error_message": error_msg,
                "error_code": return_code,
                "measured_at": start_time,
            }
        
        # Parse successful ping output
        lines = stdout.strip().split('\n')
        latencies = []
        successful_pings = 0
        
        # Look for round trip times in ping reply lines (not summary lines)
        for line in lines:
            # Skip summary lines that don't contain individual ping responses
            if "packets transmitted" in line or "packet loss" in line or "round-trip" in line:
                continue
                
            match = self.PING_PATTERN.search(line)
            if match:
                latency_str = match.group(1)
                if latency_str:
                    try:
                        latency = float(latency_str)
                        latencies.append(latency)
                        successful_pings += 1
                    except ValueError:
                        logger.warning(f"Failed to parse latency: {latency_str}")
        
        # Also look for packet loss information in ping summary
        packet_loss_percentage = 0.0
        for line in lines:
            # Look for packet loss summary (e.g., "2 received, 0% packet loss")
            if "packet loss" in line.lower():
                loss_match = re.search(r"(\d+(?:\.\d+)?)%", line)
                if loss_match:
                    try:
                        packet_loss_percentage = float(loss_match.group(1))
                    except ValueError:
                        pass
                break
        
        # Calculate statistics
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            # Use packet loss from summary if available, otherwise calculate from responses
            if packet_loss_percentage == 0.0 and successful_pings < self.ping_count:
                packet_loss_percentage = ((self.ping_count - successful_pings) / self.ping_count) * 100
            success = packet_loss_percentage < 100  # Success if at least one packet got through
        else:
            # No successful pings found
            avg_latency = None
            packet_loss_percentage = 100.0
            success = False
        
        return {
            "success": success,
            "latency_ms": avg_latency,
            "packet_loss": packet_loss_percentage,
            "error_message": None if success else "No successful pings",
            "error_code": None,
            "measured_at": start_time,
        }
    
    async def batch_ping_nodes(self, node_targets: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
        """Ping multiple nodes concurrently.
        
        Args:
            node_targets: Dictionary mapping node names to IP addresses
            
        Returns:
            Dictionary mapping node names to ping results
        """
        if not node_targets:
            return {}
        
        logger.info(f"Starting batch ping for {len(node_targets)} nodes")
        
        # Create ping tasks
        tasks = []
        node_names = []
        
        for node_name, target_ip in node_targets.items():
            task = self.ping_node(target_ip, node_name)
            tasks.append(task)
            node_names.append(node_name)
        
        # Execute all pings concurrently
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            ping_results = {}
            for i, result in enumerate(results):
                node_name = node_names[i]
                
                if isinstance(result, Exception):
                    logger.error(f"Exception pinging {node_name}: {result}")
                    ping_results[node_name] = {
                        "success": False,
                        "latency_ms": None,
                        "packet_loss": 100.0,
                        "error_message": str(result),
                        "error_code": -1,
                        "measured_at": datetime.now(timezone.utc),
                    }
                else:
                    ping_results[node_name] = result
            
            logger.info(f"Completed batch ping for {len(ping_results)} nodes")
            return ping_results
            
        except Exception as e:
            logger.error(f"Error in batch ping operation: {e}")
            # Return error results for all nodes
            error_result = {
                "success": False,
                "latency_ms": None,
                "packet_loss": 100.0,
                "error_message": str(e),
                "error_code": -1,
                "measured_at": datetime.now(timezone.utc),
            }
            return {name: error_result for name in node_names}
    
    def is_ping_available(self) -> bool:
        """Check if ping command is available.
        
        Returns:
            True if ping is available, False otherwise.
        """
        try:
            import shutil
            return shutil.which("ping") is not None
        except Exception:
            return False