"""Main entry point for the node manager service."""
from __future__ import annotations

import asyncio
from asyncio.log import logger
import logging
import os
import signal
import sys
from traceback import print_exc
try:
    import uvicorn
    from kitchen.node_manager.api import app
except ImportError as e:
    print(f"❌ Missing dependencies for node manager: {e}, {print_exc()}")
    print("💡 To install node manager dependencies, run:")
    print("   poetry install --with=node-manager")
    print("   # OR")
    print("   pip install fastapi uvicorn sqlmodel asyncpg alembic kubernetes")
    print()
    print("📚 For more information, see the node manager documentation.")
    sys.exit(1)


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
    logger.info(f"Configuring server to run on {host}:{port}")
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
    
    # Check if we have a database URL configured
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logging.warning("⚠️  DATABASE_URL environment variable not set")
        logging.info("💡 To run the node manager, you need to provide a PostgreSQL database URL:")
        logging.info("   export DATABASE_URL='postgresql+asyncpg://user:pass@host:5432/db'")
        logging.info("   python -m kitchen.node_manager.main")
        logging.info("")
        logging.info("📚 Or use the CLI: kitchen node-manager deploy --database-url 'postgresql+asyncpg://...'")
        logging.info("")
        logging.info("🔧 Starting server anyway (will fail without valid database)...")
    
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logging.info("Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Application failed: {e}")
        if "Connect call failed" in str(e) and "5432" in str(e):
            logging.error("💡 This error indicates PostgreSQL is not available or misconfigured.")
            logging.error("   Please ensure your DATABASE_URL is correct and PostgreSQL is running.")
        sys.exit(1)


if __name__ == "__main__":
    main()