.PHONY: help run install-linux uninstall-linux test

PYTHON ?= python3

help:
	@echo "APRS PropView targets:"
	@echo "  make run              Run from the current checkout"
	@echo "  make test             Run Python unit tests"
	@echo "  make install-linux    Install/update systemd service on Linux"
	@echo "  make uninstall-linux  Remove Linux systemd service"

run:
	$(PYTHON) main.py

test:
	$(PYTHON) -m unittest discover

install-linux:
	sudo bash ./scripts/install_linux.sh

uninstall-linux:
	sudo bash ./scripts/uninstall_linux.sh
