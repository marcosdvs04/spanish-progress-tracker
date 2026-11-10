.PHONY: install demo test serve lint reset clean

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"

demo:
	.venv/bin/python -m progress_tracker.cli demo

test:
	.venv/bin/python -m pytest

lint:
	.venv/bin/python -m pytest tests/test_architecture.py -v

serve:
	.venv/bin/python -m progress_tracker.cli serve

reset:
	.venv/bin/python -m progress_tracker.cli reset

clean:
	rm -rf data exports .pytest_cache
