# Support

Quorvex AI is an open-source project. Use the channel that matches the type of help you need so bugs, questions, and security reports do not get mixed together.

## Bugs

Open a GitHub issue when you can provide:

- A clear description of the failure
- Steps to reproduce it
- The setup path you used: Minimal Docker, `make dev`, local native dev, or production/company external-nginx mode
- Relevant versions for Python, Node.js, Docker, browser, and Quorvex commit or tag
- Logs or screenshots with secrets removed

## Questions And Ideas

Use GitHub Discussions for usage questions, design ideas, implementation trade-offs, and workflow advice. Discussions are better than issues when there is no confirmed defect or scoped implementation task yet.

## Security Reports

Do not open public issues for vulnerabilities. Follow [SECURITY.md](SECURITY.md) so reports can be triaged privately before public disclosure.

## Commercial And Operational Support

There is no guaranteed response SLA for the public repository. Production operators are responsible for their own secrets, backups, network controls, TLS termination, and incident response. For company deployments, follow [docs/guides/company-deployment.md](docs/guides/company-deployment.md) and keep credentials in `.env.prod`, `.env`, `.env.local`, `.secrets/`, or deployment environment variables only.
