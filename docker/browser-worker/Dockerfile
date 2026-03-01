# ============================================
# Browser Worker Container
# Isolated Playwright browser for parallel test execution
# ============================================
# Using official Playwright image which already has browsers installed
FROM mcr.microsoft.com/playwright:v1.49.0-jammy

WORKDIR /app

# Set environment variables
ENV PLAYWRIGHT_WORKERS=1
ENV HEADLESS=true

# Copy package files and install dependencies
# Note: We need @playwright/test for running tests
# Install with NODE_ENV=development to include devDependencies (playwright)
COPY package.json package-lock.json ./
RUN npm ci

# Now set production mode for runtime
ENV NODE_ENV=production

# Browsers are already installed in the base image
# No need to run: npx playwright install

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
