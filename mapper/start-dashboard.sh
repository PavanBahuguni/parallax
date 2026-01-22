#!/bin/bash

# Start Agentic QA Dashboard
# This script starts both backend and frontend servers

echo "🚀 Starting Agentic QA Dashboard..."
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is not installed. Please install uv first."
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo "❌ Error: npm is not installed. Please install npm first."
    exit 1
fi

# Start backend in background
echo "📡 Starting backend server on port 8001..."
cd backend
uv sync > /dev/null 2>&1
uv run uvicorn app.main:app --reload --port 8001 &
BACKEND_PID=$!
cd ..

# Wait a bit for backend to start
sleep 2

# Start frontend
echo "🎨 Starting frontend server on port 5174..."
cd frontend
if [ ! -d "node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    npm install
fi
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ Dashboard started!"
echo ""
echo "📡 Backend:  http://localhost:8001"
echo "🎨 Frontend: http://localhost:5174"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

# Wait for user interrupt
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
