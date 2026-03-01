#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}   Playwright Agent Setup${NC}"
echo -e "${GREEN}============================================${NC}"

# Track if there are warnings
WARNINGS=0

# ==========================================
# 1. PREREQUISITE CHECKS
# ==========================================
echo -e "\n${YELLOW}[1/7] Checking prerequisites...${NC}"

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "  ${RED}x${NC} Python 3 is not installed!"
    echo "    Please install Python 3.10+ from https://python.org"
    exit 1
fi
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "  ${GREEN}+${NC} Python $PYTHON_VERSION"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "  ${RED}x${NC} Node.js is not installed!"
    echo "    Please install Node.js 20+ from https://nodejs.org"
    exit 1
fi
NODE_VERSION=$(node -v)
echo -e "  ${GREEN}+${NC} Node.js $NODE_VERSION"

# Check npm
if ! command -v npm &> /dev/null; then
    echo -e "  ${RED}x${NC} npm is not installed!"
    exit 1
fi
echo -e "  ${GREEN}+${NC} npm $(npm -v)"

# Check Docker (optional but recommended)
DOCKER_AVAILABLE=false
if command -v docker &> /dev/null; then
    if docker info >/dev/null 2>&1; then
        echo -e "  ${GREEN}+${NC} Docker $(docker -v | cut -d ' ' -f3 | tr -d ',')"
        DOCKER_AVAILABLE=true
    else
        echo -e "  ${YELLOW}!${NC} Docker installed but daemon not running"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "  ${YELLOW}!${NC} Docker not found (optional - needed for PostgreSQL)"
    WARNINGS=$((WARNINGS + 1))
fi

# ==========================================
# 2. ENVIRONMENT FILE SETUP
# ==========================================
echo -e "\n${YELLOW}[2/7] Setting up environment configuration...${NC}"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "  ${GREEN}+${NC} Created .env from .env.example"
        echo -e "  ${YELLOW}!${NC} Please edit .env with your API credentials"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "  ${YELLOW}!${NC} .env.example not found, creating minimal .env..."
        cat > .env << 'EOF'
# ==========================================
# PLAYWRIGHT AGENT - MINIMAL CONFIGURATION
# ==========================================
# Please add your API credentials below

# [REQUIRED] Claude API Configuration
ANTHROPIC_AUTH_TOKEN=your-token-here
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-20250514

# [OPTIONAL] Memory System (requires OpenAI key for embeddings)
MEMORY_ENABLED=false
OPENAI_API_KEY=

# [OPTIONAL] Database (defaults to SQLite)
DATABASE_URL=sqlite:///./test.db
EOF
        echo -e "  ${YELLOW}+${NC} Minimal .env created"
        echo -e "  ${YELLOW}!${NC} Please edit .env with your API credentials"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "  ${GREEN}+${NC} .env file already exists"
fi

# ==========================================
# 3. PYTHON VIRTUAL ENVIRONMENT
# ==========================================
echo -e "\n${YELLOW}[3/7] Setting up Python virtual environment...${NC}"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "  ${GREEN}+${NC} Created virtual environment"
else
    echo -e "  ${GREEN}+${NC} Virtual environment exists"
fi

source venv/bin/activate

# ==========================================
# 4. PYTHON DEPENDENCIES
# ==========================================
echo -e "\n${YELLOW}[4/7] Installing Python dependencies...${NC}"

pip install --upgrade pip --quiet 2>/dev/null

if [ -f "pyproject.toml" ]; then
    pip install -e . --quiet 2>/dev/null
    echo -e "  ${GREEN}+${NC} Installed Python packages (from pyproject.toml)"
elif [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet 2>/dev/null
    echo -e "  ${GREEN}+${NC} Installed Python packages (from requirements.txt)"
else
    echo -e "  ${RED}x${NC} No pyproject.toml or requirements.txt found!"
    exit 1
fi

# ==========================================
# 5. ROOT NODE.JS DEPENDENCIES
# ==========================================
echo -e "\n${YELLOW}[5/7] Installing root Node.js dependencies...${NC}"

if [ -f "package.json" ]; then
    npm install --silent 2>/dev/null
    echo -e "  ${GREEN}+${NC} Installed npm packages"
else
    echo -e "  ${YELLOW}!${NC} package.json not found in root"
    WARNINGS=$((WARNINGS + 1))
fi

# ==========================================
# 6. PLAYWRIGHT BROWSERS
# ==========================================
echo -e "\n${YELLOW}[6/7] Installing Playwright browsers...${NC}"

# Install only Chromium by default (faster setup)
npx playwright install chromium 2>/dev/null
echo -e "  ${GREEN}+${NC} Installed Chromium browser"
echo -e "  ${BLUE}i${NC} Run 'npx playwright install' for all browsers"

# ==========================================
# 7. FRONTEND SETUP
# ==========================================
echo -e "\n${YELLOW}[7/7] Setting up Web Dashboard...${NC}"

if [ -d "web" ]; then
    cd web
    npm install --silent 2>/dev/null
    cd ..
    echo -e "  ${GREEN}+${NC} Installed frontend packages"
else
    echo -e "  ${RED}x${NC} web directory not found!"
    exit 1
fi

# ==========================================
# CREATE NECESSARY DIRECTORIES
# ==========================================
mkdir -p runs specs tests/generated data/chromadb prds

# ==========================================
# VALIDATE ENVIRONMENT
# ==========================================
echo -e "\n${YELLOW}Validating configuration...${NC}"

# Source .env to check variables
set +e
source .env 2>/dev/null
set -e

if [ -z "$ANTHROPIC_AUTH_TOKEN" ] || [ "$ANTHROPIC_AUTH_TOKEN" = "your-token-here" ]; then
    echo -e "  ${YELLOW}!${NC} ANTHROPIC_AUTH_TOKEN not configured"
    WARNINGS=$((WARNINGS + 1))
else
    echo -e "  ${GREEN}+${NC} ANTHROPIC_AUTH_TOKEN is set"
fi

if [ -z "$ANTHROPIC_BASE_URL" ]; then
    echo -e "  ${YELLOW}!${NC} ANTHROPIC_BASE_URL not configured"
    WARNINGS=$((WARNINGS + 1))
else
    echo -e "  ${GREEN}+${NC} ANTHROPIC_BASE_URL: $ANTHROPIC_BASE_URL"
fi

# ==========================================
# SUMMARY
# ==========================================
echo -e "\n${GREEN}============================================${NC}"
if [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}   Setup Complete (with $WARNINGS warnings)${NC}"
else
    echo -e "${GREEN}   Setup Complete!${NC}"
fi
echo -e "${GREEN}============================================${NC}"

echo ""
echo -e "${BLUE}Next steps:${NC}"
if [ "$ANTHROPIC_AUTH_TOKEN" = "your-token-here" ] || [ -z "$ANTHROPIC_AUTH_TOKEN" ]; then
    echo -e "  1. Edit ${YELLOW}.env${NC} with your API credentials"
    echo -e "  2. Run ${YELLOW}make dev${NC} to start the dashboard"
else
    echo -e "  1. Run ${YELLOW}make dev${NC} to start the dashboard"
fi
echo -e "  3. Visit ${YELLOW}http://localhost:3000${NC}"

echo ""
echo -e "${BLUE}Quick commands:${NC}"
echo -e "  ${YELLOW}make dev${NC}                        - Start web dashboard"
echo -e "  ${YELLOW}make run SPEC=specs/test.md${NC}     - Run a test spec"
echo -e "  ${YELLOW}make check-env${NC}                  - Validate configuration"

if [ "$DOCKER_AVAILABLE" = true ]; then
    echo ""
    echo -e "${BLUE}Docker mode:${NC}"
    echo -e "  ${YELLOW}make docker-up${NC}                  - Run everything in containers"
fi

echo ""
