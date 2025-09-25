"""Main entry point for the node manager service."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Optional

import uvicorn
from kitchen.node_manager.api import app


def setup_logging() -> None:
    """Configure logging for the application."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific log levels for noisy libraries
    logging.getLogger("kubernetes").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


async def run_server() -> None:
    """Run the FastAPI server with proper lifecycle management."""
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info").lower(),
        access_log=True,
        use_colors=True,
        loop="asyncio",
    )
    
    server = uvicorn.Server(config)
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, initiating shutdown...")
        server.should_exit = True
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logging.info(f"Starting Kitchen Node Manager on {host}:{port}")
    
    try:
        await server.serve()
    except KeyboardInterrupt:
        logging.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logging.error(f"Server error: {e}")
        raise
    finally:
        logging.info("Server shutdown complete")


def main() -> None:
    """Main entry point."""
    setup_logging()
    
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logging.info("Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Application failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()