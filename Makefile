.PHONY: help install verify server demo demo-ols clean

help:
	@echo "MCP Approval Sample - Available Commands"
	@echo "========================================"
	@echo ""
	@echo "  make install    - Install Python dependencies with uv"
	@echo "  make verify     - Verify installation"
	@echo "  make server     - Start the MCP server"
	@echo "  make demo       - Run the LangGraph demo"
	@echo "  make demo-ols   - Run the OLS-style demo"
	@echo "  make clean      - Clean temporary files"
	@echo ""

install:
	@echo "Installing dependencies with uv..."
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	fi
	uv pip install -e ".[all]"
	@echo "✓ Installation complete"

verify:
	@echo "Verifying code format and quality..."
	@. .venv/bin/activate && python -m black --check *.py || (echo "❌ Run 'black *.py' to fix formatting"; exit 1)
	@. .venv/bin/activate && python -m ruff check *.py || (echo "❌ Run 'ruff check --fix *.py' to fix issues"; exit 1)
	@echo "✓ All checks passed"

server:
	@echo "Starting MCP server on http://localhost:3000"
	@echo "Press Ctrl+C to stop"
	python3 mcp_server.py

demo:
	@echo "Running LangGraph demo (make sure server is running in another terminal)..."
	python3 demo_approval_client.py

demo-ols:
	@echo "Running OLS-style demo (make sure server is running in another terminal)..."
	python3 demo_ols_approval_client.py

clean:
	@echo "Cleaning temporary files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleanup complete"
