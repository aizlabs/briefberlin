.PHONY: help build test-discovery test-fetcher clean logs

help:
	@echo "AutoSpanishBlog - Development Commands (Phase 1)"
	@echo ""
	@echo "  make build           - Build Docker container"
	@echo "  make test-discovery  - Test topic discovery"
	@echo "  make test-fetcher    - Test content fetcher (when available)"
	@echo "  make logs            - Tail local logs"
	@echo "  make clean           - Clean generated files"
	@echo ""
	@echo "Note: Full pipeline (make run) will be available in Phase 2"
	@echo ""

build:
	docker compose build

# Phase 1: Topic Discovery test (current)
test-discovery:
	docker compose run generator python scripts/test_discovery.py

# Phase 1: Content Fetcher test (when on feature/content-fetcher branch)
test-fetcher:
	docker compose run generator python scripts/test_fetcher.py

# Phase 2: Full pipeline (not yet implemented)
# Commented out until scripts/main.py is created
# run:
# 	docker compose run generator python scripts/main.py
#
# dry-run:
# 	DRY_RUN=true docker compose run generator python scripts/main.py

logs:
	tail -f logs/local.log

clean:
	rm -rf logs/*.log
	rm -rf output/_posts/*
	rm -rf output/logs/*
	rm -rf output/metrics/*
	@echo "Cleaned generated files"
