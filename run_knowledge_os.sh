#!/bin/bash
# Knowledge OS Startup Script

cd "$(dirname "$0")"

echo "📚 Knowledge OS"
echo "================"
echo ""
echo "Installing dependencies..."
pip install -q fastapi uvicorn sqlalchemy pydantic

echo ""
echo "Starting API server..."
echo "🚀 A URL da UI será impressa abaixo"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run API server
python -m src.main ui --port 9876
