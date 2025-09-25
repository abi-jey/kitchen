# Build stage
FROM python:3.12-slim as builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Tailscale
RUN curl -fsSL https://tailscale.com/install.sh | sh

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Production stage  
FROM python:3.12-slim

# Install system dependencies and Tailscale
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && curl -fsSL https://tailscale.com/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create app user
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# Set working directory
WORKDIR /app

# Copy application code
COPY src/kitchen/node_manager ./kitchen/node_manager
COPY src/kitchen/__init__.py ./kitchen/

# Set Python path
ENV PYTHONPATH=/app

# Create logs directory
RUN mkdir -p /app/logs && chown -R appuser:appgroup /app

# Switch to app user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "-m", "kitchen.node_manager.main"]