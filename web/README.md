# Quorvex AI Web Dashboard

This is the Next.js dashboard for Quorvex AI. It gives QA and engineering teams a browser UI for creating specs, running AI-assisted test generation, reviewing runs, managing regression batches, and connecting CI/CD workflows.

## Local Development

Run the full project from the repository root when you need the backend, database, workers, and dashboard together:

```bash
make dev
```

For frontend-only work:

```bash
cd web
npm install
npm run dev
```

The dashboard runs at [http://localhost:3000](http://localhost:3000). The FastAPI backend normally runs at [http://localhost:8001](http://localhost:8001).

## Useful Commands

```bash
npm run dev      # Start the Next.js dev server
npm run build    # Build the dashboard
npm run lint     # Run the frontend linter
```

## Project Notes

- Application routes live under `src/app/`.
- Shared dashboard components live under `src/components/`.
- AI assistant action definitions and workflow capabilities live under `src/lib/ai/`.
- Root-level setup, architecture, and contribution instructions live in the main repository README and docs site.
