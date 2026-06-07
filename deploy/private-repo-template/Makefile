.PHONY: bootstrap deploy deploy-dry-run rollback doctor status logs config pull

VERSION ?=

bootstrap:
	@./scripts/bootstrap.sh

doctor:
	@./scripts/doctor.sh

deploy:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make deploy VERSION=v1.2.3"; \
		exit 2; \
	fi
	@./scripts/deploy.sh "$(VERSION)"

deploy-dry-run:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make deploy-dry-run VERSION=v1.2.3"; \
		exit 2; \
	fi
	@./scripts/deploy.sh --dry-run "$(VERSION)"

rollback:
	@./scripts/rollback.sh

status:
	@./scripts/doctor.sh --status-only

logs:
	@./scripts/doctor.sh --logs

config:
	@./scripts/deploy.sh --dry-run "$${VERSION:-v0.0.0}"

pull:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make pull VERSION=v1.2.3"; \
		exit 2; \
	fi
	@./scripts/deploy.sh --pull-only "$(VERSION)"
