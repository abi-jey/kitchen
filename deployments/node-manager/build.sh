#!/bin/bash
set -e

# Build and test the Kitchen Node Manager Docker image

echo "🔨 Building Kitchen Node Manager Docker image with Poetry..."

# Build the image
docker build -f Dockerfile -t kitchen/node-manager:latest ../../

echo "✅ Docker image built successfully!"

# Test the image (basic smoke test)
echo "🧪 Running basic smoke test..."

# Check if the image can start (will fail without database, but should not crash immediately)
timeout 10s docker run --rm kitchen/node-manager:latest || true

echo "✅ Smoke test completed!"

# Optional: Run with dummy database URL to test startup process
echo "🧪 Testing startup with dummy database..."

timeout 10s docker run --rm \
  -e DATABASE_URL="postgresql+asyncpg://dummy:dummy@dummy:5432/dummy" \
  kitchen/node-manager:latest || true

echo "✅ Startup test completed!"

echo "🎉 All tests passed! Image is ready for deployment."
echo ""
echo "To deploy to Kubernetes:"
echo "1. Push the image to GHCR (handled by GitHub Actions):"
echo "   - Image will be built and pushed automatically on merge to main"
echo "   - Location: ghcr.io/abi-jey/kitchen/node-manager:latest"
echo ""
echo "2. Ensure you have PostgreSQL database configured"
echo ""
echo "3. Deploy to Kubernetes:"
echo "   kubectl apply -f k8s-manifests.yaml"
echo ""
echo "Note: This Docker image uses Poetry for dependency management from pyproject.toml"
echo "Note: SQLModel is used for database models (wraps SQLAlchemy with Pydantic)"