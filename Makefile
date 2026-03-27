.PHONY: setup run tunnel battle clean

setup:
	pip install -r requirements.txt

run:
	python server.py

tunnel:
	cloudflared tunnel --url http://localhost:3000

battle:
	cd kahoot && python game.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	find . -type f -name '*.pyo' -delete 2>/dev/null || true
	@echo "Cleaned."
