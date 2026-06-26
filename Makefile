.PHONY: help build test-discovery test-fetcher clean logs

help:
	@echo "BriefBerlin - Development Commands"
	@echo ""
	@echo "  make build           - Build Docker container"
	@echo "  make test-discovery  - Test topic discovery"
	@echo "  make test-fetcher    - Test content fetcher"
	@echo "  make logs            - Tail local logs"
	@echo "  make clean           - Clean generated files"
	@echo ""
	@echo "Manual generation: uv run briefberlin-manual private-input/source-1.source.txt"
	@echo ""

build:
	docker compose build

test-discovery:
	docker compose run generator python scripts/test_discovery.py

test-fetcher:
	docker compose run generator python scripts/test_fetcher.py

logs:
	tail -f logs/local.log

clean:
	rm -rf logs/*.log
	rm -rf output/_posts/*
	rm -rf output/logs/*
	rm -rf output/metrics/*
	@echo "Cleaned generated files"
