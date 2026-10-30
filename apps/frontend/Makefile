.PHONY: install typecheck lint test schema build check format

install:
	npm ci

typecheck:
	npm run typecheck

lint:
	npm run lint

test:
	npm run test -- --run

schema:
	npm run schema:validate

build:
	npm run build

format:
	npm run format

# The mandatory gate (AC-14): install, typecheck, lint, unit tests, schema
# validation, and production build.
check: install typecheck lint test schema build
	@echo "make check: ALL CHECKS PASSED"