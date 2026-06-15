# ============================================
# Browser Worker Container
# Isolated Playwright browser for parallel test execution
# ============================================
# Use a slim Node runtime and install only Chromium instead of carrying the
# official all-browser Playwright image.
FROM node:22-bookworm-slim

WORKDIR /app

# Set environment variables
ENV PLAYWRIGHT_WORKERS=1
ENV HEADLESS=true
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=300000

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy package files and install dependencies
# Install production MCP/runtime packages plus the Playwright test runner only.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && \
    mv package.json package.full.json && \
    mv package-lock.json package-lock.full.json && \
    npm install --package-lock=false --no-save @playwright/test@1.61.0 && \
    mv package.full.json package.json && \
    mv package-lock.full.json package-lock.json && \
    npx playwright install --with-deps chromium && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/*

# Now set production mode for runtime
ENV NODE_ENV=production

# Copy test configuration and tests
COPY playwright.config.ts ./
COPY tests/ ./tests/
COPY specs/ ./specs/

# Note: Running as root for simplicity since workers are ephemeral containers
# and need write access to shared volumes (test-results).
# For stricter security, use an init container to set volume permissions.

# Expose port for health checks (optional - workers don't need external access)
EXPOSE 3000

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD node -e "console.log('ok')" || exit 1

# Default: Run single test (overridden by orchestrator)
# Workers receive test files via shared volume or job queue
CMD ["npx", "playwright", "test", "--workers=1", "--project=chromium"]
