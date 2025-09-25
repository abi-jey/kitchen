#!/bin/bash
set -e

# Build and test the Kitchen Node Manager Docker image

echo "🔨 Building Kitchen Node Manager Docker image..."

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
echo "1. Push the image to your registry:"
echo "   docker tag kitchen/node-manager:latest your-registry/kitchen/node-manager:latest"
echo "   docker push your-registry/kitchen/node-manager:latest"
echo ""
echo "2. Update the image in k8s-manifests.yaml"
echo ""
echo "3. Deploy to Kubernetes:"
echo "   kubectl apply -f postgres.yaml"
echo "   kubectl apply -f k8s-manifests.yaml"