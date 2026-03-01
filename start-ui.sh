#!/bin/bash
# Start Backend and Frontend for Playwright Agent UI

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Clean up on exit - graceful shutdown
cleanup() {
    echo -e "\n${YELLOW}Shutting down services gracefully...${NC}"
    # Send SIGTERM first (graceful)
    kill -15 0 2>/dev/null || true
    sleep 2
    # Force kill if still running
    kill -9 0 2>/dev/null || true
    echo -e "${GREEN}Services stopped.${NC}"
}
trap cleanup EXIT INT TERM

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}   Playwright Agent - Development Mode${NC}"
echo -e "${GREEN}============================================${NC}"

# ==========================================
# KILL EXISTING PROCESSES
# ==========================================
echo -e "\n${YELLOW}[0/3] Cleaning up existing processes...${NC}"

# Gracefully stop processes on port 8001 (Backend API)
if lsof -ti :8001 >/dev/null 2>&1; then
    echo -e "  Stopping existing process on port 8001 gracefully..."
    lsof -ti :8001 | xargs kill -15 2>/dev/null || true
    sleep 2
    # Force kill only if still running
    if lsof -ti :8001 >/dev/null 2>&1; then
        lsof -ti :8001 | xargs kill -9 2>/dev/null || true
        sleep 1
    fi
    echo -e "  ${GREEN}+${NC} Port 8001 cleared"
else
    echo -e "  ${GREEN}+${NC} Port 8001 is free"
fi

# Gracefully stop processes on port 3000 (Frontend)
if lsof -ti :3000 >/dev/null 2>&1; then
    echo -e "  Stopping existing process on port 3000 gracefully..."
    lsof -ti :3000 | xargs kill -15 2>/dev/null || true
    sleep 2
    # Force kill only if still running
    if lsof -ti :3000 >/dev/null 2>&1; then
        lsof -ti :3000 | xargs kill -9 2>/dev/null || true
        sleep 1
    fi
    echo -e "  ${GREEN}+${NC} Port 3000 cleared"
else
    echo -e "  ${GREEN}+${NC} Port 3000 is free"
fi

# ==========================================
# LOAD ENVIRONMENT
# ==========================================
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
    echo -e "  ${GREEN}+${NC} Loaded .env"
else
    echo -e "  ${YELLOW}!${NC} No .env file found - using defaults"
fi

# ==========================================
# CHECK VIRTUAL ENVIRONMENT
# ==========================================
if [ ! -d "venv" ]; then
    echo -e "${RED}ERROR: Virtual environment not found!${NC}"
    echo "Please run 'make setup' first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Verify Python dependencies
if ! python -c "import sqlmodel" 2>/dev/null; then
    echo -e "${RED}ERROR: sqlmodel not found in Python environment.${NC}"
    echo "Please run 'make setup' again."
    exit 1
fi

# ==========================================
# HELPER FUNCTIONS
# ==========================================

# Wait for PostgreSQL to be ready
wait_for_postgres() {
    local max_attempts=30
    local attempt=1

    echo -e "  Waiting for PostgreSQL..."

    while [ $attempt -le $max_attempts ]; do
        if docker exec quorvex-db-dev pg_isready -U postgres -d playwright_agent >/dev/null 2>&1; then
            echo -e "  ${GREEN}+${NC} PostgreSQL is ready"
            return 0
        fi
        printf "."
        sleep 1
        attempt=$((attempt + 1))
    done

    echo -e "\n  ${RED}x${NC} PostgreSQL failed to start after ${max_attempts} seconds"
    return 1
}

# Wait for Backend API to be ready
wait_for_backend() {
    local max_attempts=30
    local attempt=1

    echo -e "  Waiting for Backend API..."

    while [ $attempt -le $max_attempts ]; do
        if curl -s http://localhost:8001/docs >/dev/null 2>&1; then
            echo -e "  ${GREEN}+${NC} Backend API is ready"
            return 0
        fi
        printf "."
        sleep 1
        attempt=$((attempt + 1))
    done

    echo -e "\n  ${YELLOW}!${NC} Backend API slow to start - check api.log"
    return 0  # Don't fail, frontend can still start
}

# ==========================================
# DETERMINE DATABASE MODE
# ==========================================
USE_POSTGRES=false

if command -v docker &> /dev/null && docker info >/dev/null 2>&1; then
    USE_POSTGRES=true
fi

# ==========================================
# START DATABASE
# ==========================================
echo -e "\n${YELLOW}[1/4] Starting Database...${NC}"

if [ "$USE_POSTGRES" = true ]; then
    # Check if container exists and is running
    if docker ps --format '{{.Names}}' | grep -q "quorvex-db-dev"; then
        echo -e "  ${GREEN}+${NC} Database container already running"
    elif docker ps -a --format '{{.Names}}' | grep -q "quorvex-db-dev"; then
        docker start quorvex-db-dev >/dev/null
        echo -e "  ${GREEN}+${NC} Started existing database container"
    else
        docker-compose up -d db
        echo -e "  ${GREEN}+${NC} Created and started database container"
    fi

    # Wait for database to be ready
    wait_for_postgres || exit 1

    # Set DATABASE_URL for PostgreSQL (localhost:5434 for host access)
    export DATABASE_URL="postgresql://postgres:postgres@localhost:5434/playwright_agent"
else
    echo -e "  ${BLUE}i${NC} Docker not available - using SQLite database"
    export DATABASE_URL="sqlite:///./test.db"
fi

# ==========================================
# START BACKEND
# ==========================================
echo -e "\n${YELLOW}[2/4] Starting Backend API...${NC}"

export PYTHONPATH="${PYTHONPATH}:$(pwd)/orchestrator"
cd orchestrator
uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload > ../api.log 2>&1 &
BACKEND_PID=$!
cd ..
echo -e "  Backend starting (PID: $BACKEND_PID)"

# Wait for backend to be ready
wait_for_backend

# ==========================================
# START FRONTEND
# ==========================================
echo -e "\n${YELLOW}[3/4] Starting Frontend...${NC}"

cd web
npm run dev > ../web.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo -e "  Frontend starting (PID: $FRONTEND_PID)"

# Wait a moment for frontend to initialize
sleep 3

# ==========================================
# SUMMARY
# ==========================================
echo -e "\n${GREEN}============================================${NC}"
echo -e "${GREEN}   Services Started Successfully!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  ${GREEN}Dashboard:${NC} http://localhost:3000"
echo -e "  ${GREEN}API:${NC}       http://localhost:8001"
echo -e "  ${GREEN}API Docs:${NC}  http://localhost:8001/docs"
echo ""
echo -e "  ${BLUE}Database:${NC}  $DATABASE_URL"
echo ""
echo -e "  ${YELLOW}Logs:${NC}"
echo -e "    Backend:  tail -f api.log"
echo -e "    Frontend: tail -f web.log"
echo ""
echo -e "Press ${YELLOW}Ctrl+C${NC} to stop all services."

# Wait for processes
wait
