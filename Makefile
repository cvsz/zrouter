# Makefile — NVIDIA Free-Model Router
#
# Usage:
#   make setup          # create venv + install dependencies
#   make test           # run the test suite
#   make run            # run zrouter.py (chat example)
#   make serve          # run the OpenAI-compatible proxy
#   make lint           # ruff check + format check
#   make format         # ruff format
#   make clean          # remove venv and caches
#   make all            # setup + lint + test
#   make build          # default build (setup + lint + test + exe)
#   make build:gui      # build GUI executable (PyInstaller)
#   make build:tui      # build TUI package
#   make build:web      # build web deployment package
#   make build:desktops # build desktop application packages (.desktop + launcher)
#   make build:dev      # development build with dev tools
#   make build:prod     # production-optimized build (PyInstaller onefile)
#   make build:ent      # enterprise build with all features
#   make build:exe      # build native CLI executable using PyInstaller
#   make build:exe:win  # build Windows .exe (requires Wine)
#   make build:android  # build Android package (requires Buildozer)
#   make build:ios      # build iOS package (requires BeeWare/Kivy, macOS)
#   make build:zrouter   # build zrouter CLI entry point
#   make gui            # launch zrouter GUI
#   make install:zrouter # install zrouter to $(PREFIX)/bin
#   make uninstall:zrouter # remove zrouter from $(PREFIX)/bin

.PHONY: all setup test run serve lint format clean help venv install-deps build build\:all build\:web build\:web\:all build\:web\:dev build\:web\:prod build\:web\:ent build\:desktops build\:dev build\:prod build\:ent build\:exe build\:exe\:win build\:gui build\:tui build\:android build\:ios build\:zrouter build\:packages build\:wheel build\:sdist install\:zrouter uninstall\:zrouter zrouter gui docker\:build docker\:run build\:web\:start build\:deploy build\:zbot
.PHONY: all setup test run serve lint format clean help venv install-deps build build\:all build\:web build\:web\:all build\:web\:dev build\:web\:prod build\:web\:ent build\:desktops build\:dev build\:prod build\:ent build\:exe build\:exe\:win build\:gui build\:tui build\:android build\:ios build\:zrouter build\:packages build\:wheel build\:sdist install\:zrouter uninstall\:zrouter zrouter gui docker\:build docker\:run build\:web\:start build\:deploy build\:zbot

PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
REQUIREMENTS := requests keyring pytest ruff flask gunicorn
PREFIX ?= /usr/local
DIST := dist
BUILD := build

# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #

all: setup lint test

help: ## Show this help
	@echo "NVIDIA Free-Model Router — Make targets:"
	@echo
	@echo "Core targets:"
	@echo "  make setup        create virtualenv and install dependencies"
	@echo "  make install      install/upgrade dependencies (requires existing venv)"
	@echo "  make test         run the pytest suite"
	@echo "  make lint         ruff check + ruff format --check"
	@echo "  make format       ruff format (in place)"
	@echo "  make clean        remove .venv, build/, dist/ and Python caches"
	@echo "  make all          setup + lint + test"
	@echo
	@echo "Run targets:"
	@echo "  make run          run zrouter.py chat (requires NVIDIA_API_KEYS)"
	@echo "  make serve        run the OpenAI-compatible proxy (requires keys)"
	@echo "  make gui          launch zrouter GUI"
	@echo
	@echo "Model/Provider targets:"
	@echo "  make models       list catalog models with free/paid/provider metadata"
	@echo "  make models-free  list only free models"
	@echo "  make models-paid  list only paid models"
	@echo "  make providers    list configured providers with API key counts and base URLs"
	@echo "  make discover     auto-discover models from NVIDIA API and update models.json"
	@echo
	@echo "Build targets:"
	@echo "  make build        default build (setup + lint + test + exe)"
	@echo "  make build:all    build all variants (exe + gui + web + desktops + dev + prod + ent + zbot)"
	@echo "  make build:exe    build native CLI executable using PyInstaller"
	@echo "  make build:exe:win build Windows .exe (requires Wine)"
	@echo "  make build:gui    build GUI executable using PyInstaller"
	@echo "  make build:tui    build TUI package"
	@echo "  make build:zbot   build cross-platform zbot CLI executable"
	@echo "  make build:web    build web deployment package"
	@echo "  make build:web:all build all web variants (dev + prod + ent)"
	@echo "  make build:web:dev build web dev package (hot-reload, debug)"
	@echo "  make build:web:prod build web production package (gunicorn, optimized)"
	@echo "  make build:web:ent build web enterprise package (all features)"
	@echo "  make build:web:start  start the web server from dist/web/"
	@echo "  make build:deploy     full deploy: build web package + start server"
	@echo "  make build:desktops build desktop application packages (.desktop files)"
	@echo "  make build:dev    development build with dev tools"
	@echo "  make build:prod   production-optimized build (PyInstaller onefile)"
	@echo "  make build:ent    enterprise build with all features"
	@echo "  make build:android build Android package (requires Buildozer)"
	@echo "  make build:ios    build iOS package (requires BeeWare/Kivy, macOS)"
	@echo
	@echo "zrouter targets:"
	@echo "  make build:zrouter  build zrouter CLI entry point"
	@echo "  make build:packages   build Python packages (wheel + sdist)"
	@echo "  make build:wheel      build wheel distribution"
	@echo "  make build:sdist      build source distribution"
	@echo "  make install:zrouter install zrouter to $(PREFIX)/bin"
	@echo "  make uninstall:zrouter remove zrouter from $(PREFIX)/bin"
	@echo "  make zrouter        alias for build:zrouter"
	@echo
	@echo "Docker targets:"
	@echo "  make docker:build   build Docker image"
	@echo "  make docker:run     run Docker container"
	@echo "  make docker:up      alias for docker:run"

setup: venv install-deps ## Create venv and install dependencies

venv: ## Create the virtual environment if missing
	@if [ ! -d "$(VENV)" ]; then \
		echo "==> Creating virtual environment at $(VENV)"; \
		$(PYTHON) -m venv $(VENV); \
	else \
		echo "==> Virtual environment already exists at $(VENV)"; \
	fi

install-deps: ## Install / upgrade pip and project dependencies
	@echo "==> Upgrading pip"
	$(VENV_PIP) install --upgrade pip
	@echo "==> Installing dependencies: $(REQUIREMENTS)"
	$(VENV_PIP) install $(REQUIREMENTS)

test: ## Run the test suite
	@echo "==> Running tests"
	$(VENV_PYTHON) -m pytest -v

models: ## List catalog models with free/paid/provider metadata
	@echo "==> Listing catalog models"
	$(VENV_PYTHON) zrouter.py models

models-free: ## List only free models
	@echo "==> Listing free models"
	$(VENV_PYTHON) zrouter.py models --free

models-paid: ## List only paid models
	@echo "==> Listing paid models"
	$(VENV_PYTHON) zrouter.py models --paid

discover: ## Auto-discover models from NVIDIA API and update models.json (requires NVIDIA_API_KEYS)
	@echo "==> Discovering models from NVIDIA API"
	$(VENV_PYTHON) zrouter.py discover

models-update: discover ## Alias for discover (update the models catalog)

providers: ## List configured providers with API key counts and base URLs
	@echo "==> Listing configured providers"
	$(VENV_PYTHON) zrouter.py providers

run: ## Run zrouter.py chat example (set NVIDIA_API_KEYS first)
	@echo "==> Running zrouter.py chat"
	$(VENV_PYTHON) zrouter.py chat "write a regex for emails"

serve: ## Run the OpenAI-compatible proxy on :8000 (set keys + token first)
	@echo "==> Starting proxy on http://127.0.0.1:8000/v1"
	$(VENV_PYTHON) zrouter.py serve --port 8000

lint: ## Run ruff check and ruff format --check
	@echo "==> Linting with ruff"
	$(VENV_PYTHON) -m ruff check zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py test_zrouter.py test_zrouter_core.py test_zrouter_bot.py test_zrouter_bot_models.py test_zrouter_bot_storage.py test_zrouter_runtime.py test_zrouter_http.py zrouter-gui.py zrouter-tui.py zrouter-tui.py
	$(VENV_PYTHON) -m ruff format --check zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py test_zrouter.py test_zrouter_core.py test_zrouter_bot.py test_zrouter_bot_models.py test_zrouter_bot_storage.py test_zrouter_runtime.py test_zrouter_http.py zrouter-gui.py zrouter-tui.py zrouter-tui.py

format: ## Format code with ruff
	@echo "==> Formatting with ruff"
	$(VENV_PYTHON) -m ruff format zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py test_zrouter.py test_zrouter_core.py test_zrouter_bot.py test_zrouter_bot_models.py test_zrouter_bot_storage.py test_zrouter_runtime.py test_zrouter_http.py zrouter-gui.py zrouter-tui.py

clean: ## Remove virtualenv, build artifacts, dist, and Python caches
	@echo "==> Cleaning"
	rm -rf $(VENV) $(DIST) $(BUILD) __pycache__ .pytest_cache .ruff_cache
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	find . -name "*.pyc" -delete
	find . -name "test_*_tmp.json" -delete
	find . -name "test_*_dirty.json" -delete
	find . -name "test_*_corrupt.json" -delete
	rm -rf test_proxy_stats

# --------------------------------------------------------------------------- #
# Build targets — REAL BUILDS (not just copies)
# --------------------------------------------------------------------------- #

build: setup lint test ## Default build: setup + lint + test + native executable
	@echo "==> Building default variant"
	$(MAKE) build\:exe
	@echo "==> Build complete"

build\:all: build ## Build all variants
	@echo "==> Building all variants"
	$(MAKE) build\:exe
	$(MAKE) build\:gui
	$(MAKE) build\:web
	$(MAKE) build\:desktops
	$(MAKE) build\:dev
	$(MAKE) build\:prod
	$(MAKE) build\:ent
	$(MAKE) build\:zbot
	@echo "==> All variants built"

build\:exe: setup lint test ## Build native CLI executable using PyInstaller
	@echo "==> Building native CLI executable"
	@mkdir -p $(DIST)/exe
	$(VENV_PYTHON) -m PyInstaller \
		--noconfirm \
		--clean \
		--onefile \
		--icon nvidia.ico \
		--name zrouter \
		--distpath $(DIST)/exe \
		--workpath $(BUILD)/pyinstaller \
		--specpath $(BUILD)/pyinstaller \
		zrouter.py
	cp nvidia.ico nvidia.png make_icon.py models.json $(DIST)/exe/
	@echo "==> Native executable ready: $(DIST)/exe/zrouter"
	@echo "==> Data files: $(DIST)/exe/models.json, $(DIST)/exe/nvidia.ico, $(DIST)/exe/nvidia.png"

build\:exe\:win: setup lint test ## Build Windows .exe (requires Wine for cross-compilation)
	@echo "==> Building Windows .exe"
	@mkdir -p $(DIST)/exe/win
	@if command -v wine >/dev/null 2>&1; then \
		$(VENV_PYTHON) -m PyInstaller \
			--noconfirm \
			--clean \
			--onefile \
			--icon nvidia.ico \
			--name zrouter \
			--distpath $(DIST)/exe/win \
			--workpath $(BUILD)/pyinstaller-win \
			--specpath $(BUILD)/pyinstaller-win \
			zrouter.py; \
		cp nvidia.ico nvidia.png make_icon.py models.json $(DIST)/exe/win/; \
		echo "==> Windows .exe ready: $(DIST)/exe/win/zrouter.exe"; \
	else \
		echo "==> Wine not found. Install wine to cross-compile Windows .exe."; \
		echo "==>   sudo apt install wine"; \
		echo "==>   Then run: make build:exe:win"; \
	fi

build\:gui: setup lint test ## Build GUI executable using PyInstaller
	@echo "==> Building GUI executable"
	@mkdir -p $(DIST)/gui
	$(VENV_PYTHON) -m PyInstaller \
		--noconfirm \
		--clean \
		--onefile \
		--windowed \
		--icon nvidia.ico \
		--name zrouter-gui \
		--distpath $(DIST)/gui \
		--workpath $(BUILD)/pyinstaller-gui \
		--specpath $(BUILD)/pyinstaller-gui \
		--add-data "$(CURDIR)/models.json:." \
		--add-data "$(CURDIR)/nvidia.ico:." \
		--add-data "$(CURDIR)/nvidia.png:." \
		zrouter-gui.py
	cp nvidia.ico nvidia.png make_icon.py models.json $(DIST)/gui/
	@echo "==> GUI executable ready: $(DIST)/gui/zrouter-gui"

build\:tui: setup lint test ## Build TUI package with textual
	@echo "==> Building TUI package"
	@mkdir -p $(DIST)/tui
	$(VENV_PIP) install textual rich
	$(VENV_PYTHON) -m py_compile zrouter.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py test_zrouter.py
	cp nvidia.ico nvidia.png make_icon.py zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py models.json zrouter $(DIST)/tui/
	chmod +x $(DIST)/tui/zrouter
	@echo "==> TUI package ready in $(DIST)/tui/"
	@echo "==> Run: $(DIST)/tui/zrouter providers"

build\:web: setup lint test ## Build full web deployment package (Flask + Gunicorn + UI)
	@echo "==> Building web deployment package"
	@rm -rf $(DIST)/web
	@mkdir -p $(DIST)/web/templates $(DIST)/web/static/img
	@echo "==> Compiling Python sources"
	$(VENV_PYTHON) -m py_compile zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py zrouter-gui.py web_app.py
	@echo "==> Copying application files"
	cp zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py models.json nvidia.ico nvidia.png make_icon.py $(DIST)/web/
	cp web_app.py gunicorn.conf.py Procfile Dockerfile.web docker-compose.web.yml runtime.txt .env.web.example README.web.md .dockerignore.web $(DIST)/web/
	mv $(DIST)/web/.dockerignore.web $(DIST)/web/.dockerignore
	@echo "==> Copying templates and static assets"
	cp -r templates/* $(DIST)/web/templates/
	cp -r static/* $(DIST)/web/static/
	@echo "==> Writing requirements.txt"
	printf 'flask==3.1.0\ngunicorn==23.0.0\nrequests==2.34.2\n' > $(DIST)/web/requirements.txt
	@echo "==> Web package ready in $(DIST)/web/"
	@echo "==> Run: cd $(DIST)/web && pip install -r requirements.txt && NVIDIA_API_KEYS=\"...\" python web_app.py"
	@echo "==> Or with gunicorn: gunicorn -c gunicorn.conf.py web_app:app"

build\:web\:dev: setup lint test ## Build web dev package (hot-reload, debug)
	@echo "==> Building web dev package"
	@rm -rf $(DIST)/web
	@mkdir -p $(DIST)/web/templates $(DIST)/web/static/img
	$(VENV_PYTHON) -m py_compile zrouter.py web_app.py
	cp zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py models.json nvidia.ico nvidia.png make_icon.py $(DIST)/web/
	cp web_app.py gunicorn.conf.py Procfile Dockerfile.web docker-compose.web.yml runtime.txt .env.web.example README.web.md .dockerignore.web $(DIST)/web/
	mv $(DIST)/web/.dockerignore.web $(DIST)/web/.dockerignore
	cp -r templates/* $(DIST)/web/templates/
	cp -r static/* $(DIST)/web/static/
	printf 'flask==3.1.0\ngunicorn==23.0.0\nrequests==2.34.2\n' > $(DIST)/web/requirements.txt
	@echo "==> Web dev package ready in $(DIST)/web/"
	@echo "==> Run: cd $(DIST)/web && pip install -r requirements.txt && NVIDIA_API_KEYS=\"...\" WEB_DEBUG=1 python web_app.py"

build\:web\:prod: setup lint test ## Build web production package (gunicorn, optimized)
	@echo "==> Building web production package"
	@rm -rf $(DIST)/web
	@mkdir -p $(DIST)/web/templates $(DIST)/web/static/img
	$(VENV_PYTHON) -m py_compile zrouter.py web_app.py
	cp zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py models.json nvidia.ico nvidia.png make_icon.py $(DIST)/web/
	cp web_app.py gunicorn.conf.py Procfile Dockerfile.web docker-compose.web.yml runtime.txt .env.web.example README.web.md .dockerignore.web $(DIST)/web/
	mv $(DIST)/web/.dockerignore.web $(DIST)/web/.dockerignore
	cp -r templates/* $(DIST)/web/templates/
	cp -r static/* $(DIST)/web/static/
	printf 'flask==3.1.0\ngunicorn==23.0.0\nrequests==2.34.2\n' > $(DIST)/web/requirements.txt
	@echo "==> Web production package ready in $(DIST)/web/"
	@echo "==> Run: cd $(DIST)/web && pip install -r requirements.txt && gunicorn -c gunicorn.conf.py web_app:app"

build\:web\:ent: setup lint test ## Build web enterprise package (all features + monitoring)
	@echo "==> Building web enterprise package"
	@rm -rf $(DIST)/web
	@mkdir -p $(DIST)/web/templates $(DIST)/web/static/img
	$(VENV_PYTHON) -m py_compile zrouter.py web_app.py
	cp zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py models.json nvidia.ico nvidia.png make_icon.py $(DIST)/web/
	cp web_app.py gunicorn.conf.py Procfile Dockerfile.web docker-compose.web.yml runtime.txt .env.web.example README.web.md .dockerignore.web $(DIST)/web/
	mv $(DIST)/web/.dockerignore.web $(DIST)/web/.dockerignore
	cp -r templates/* $(DIST)/web/templates/
	cp -r static/* $(DIST)/web/static/
	printf 'flask==3.1.0\ngunicorn==23.0.0\nrequests==2.34.2\n' > $(DIST)/web/requirements.txt
	@echo "==> Web enterprise package ready in $(DIST)/web/"
	@echo "==> Run: cd $(DIST)/web && pip install -r requirements.txt && gunicorn -c gunicorn.conf.py web_app:app"

build\:web\:all: build\:web\:dev build\:web\:prod build\:web\:ent ## Build all web variants (dev + prod + ent)
	@echo "==> All web variants built"

build\:web\:start: ## Start the web server from dist/web/ (requires NVIDIA_API_KEYS)
	@echo "==> Starting zrouter web server"
	@if [ ! -d "$(DIST)/web" ]; then \
		echo "==> dist/web not found. Building web package first..."; \
		$(MAKE) build\:web; \
	fi
	@PIDFILE="$(CURDIR)/$(DIST)/web/gunicorn.pid"; \
	if [ -f "$$PIDFILE" ] && kill -0 "$$(cat "$$PIDFILE")" 2>/dev/null; then \
		echo "==> Stopping existing zrouter-web (PID $$(cat "$$PIDFILE"))"; \
		kill "$$(cat "$$PIDFILE")" 2>/dev/null || true; \
		sleep 1; \
	fi; \
	cd $(DIST)/web && "$(CURDIR)/$(VENV_PIP)" install -q -r requirements.txt && \
		if [ "$$WEB_DEBUG" = "1" ]; then \
			NVIDIA_API_KEYS="$$NVIDIA_API_KEYS" WEB_HOST="$$WEB_HOST" WEB_PORT="$$WEB_PORT" WEB_DEBUG=1 "$(CURDIR)/$(VENV_PYTHON)" web_app.py; \
		else \
			NVIDIA_API_KEYS="$$NVIDIA_API_KEYS" "$(CURDIR)/$(VENV_PYTHON)" -m gunicorn -c gunicorn.conf.py --pid "$$PIDFILE" web_app:app; \
		fi

build\:deploy: setup lint test ## Full deploy: build web package + start server (requires NVIDIA_API_KEYS)
	@echo "==> Deploying zrouter web"
	$(MAKE) build\:web
	$(MAKE) build\:web:start

build\:desktops: setup lint test ## Build desktop application packages (.desktop files)
	@echo "==> Building desktop application packages"
	@mkdir -p $(DIST)/desktops
	$(VENV_PYTHON) -m py_compile zrouter.py zrouter_contracts.py zrouter_http.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py test_zrouter.py zrouter_core.py zrouter_bot.py zrouter-gui.py
	cp nvidia.ico nvidia.png make_icon.py zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py zrouter-gui.py models.json zrouter $(DIST)/desktops/
	chmod +x $(DIST)/desktops/zrouter
	@printf '[Desktop Entry]\nName=zrouter\nComment=NVIDIA Free-Model Router\nExec=zrouter %%f\nIcon=zrouter\nTerminal=false\nType=Application\nCategories=Network;Chat;\n' > $(DIST)/desktops/zrouter.desktop
	@echo "==> Desktop package ready in $(DIST)/desktops/"
	@echo "==> Desktop entry: $(DIST)/desktops/zrouter.desktop"

build\:dev: setup lint test ## Development build with dev tools
	@echo "==> Building development variant"
	$(VENV_PIP) install --upgrade pytest ruff
	$(VENV_PYTHON) -m py_compile zrouter.py zrouter_contracts.py zrouter_http.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py test_zrouter.py zrouter_core.py zrouter_bot.py zrouter-gui.py
	@mkdir -p $(DIST)/dev
	cp nvidia.ico nvidia.png make_icon.py zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py zrouter-gui.py test_zrouter.py models.json zrouter $(DIST)/dev/
	chmod +x $(DIST)/dev/zrouter
	@echo "==> Dev build ready in $(DIST)/dev/"
	@echo "==> Run: $(DIST)/dev/zrouter providers"

build\:prod: setup lint test ## Production-optimized build (PyInstaller onefile)
	@echo "==> Building production variant"
	@mkdir -p $(DIST)/prod
	$(VENV_PYTHON) -m PyInstaller \
		--noconfirm \
		--clean \
		--onefile \
		--icon nvidia.ico \
		--name zrouter \
		--distpath $(DIST)/prod \
		--workpath $(BUILD)/pyinstaller-prod \
		--specpath $(BUILD)/pyinstaller-prod \
		zrouter.py
	cp nvidia.ico nvidia.png make_icon.py models.json $(DIST)/prod/
	@echo "==> Production executable ready: $(DIST)/prod/zrouter"

build\:ent: setup lint test ## Enterprise build with all features
	@echo "==> Building enterprise variant"
	@mkdir -p $(DIST)/ent
	$(VENV_PYTHON) -m PyInstaller \
		--noconfirm \
		--clean \
		--onefile \
		--windowed \
		--icon nvidia.ico \
		--name zrouter-enterprise \
		--distpath $(DIST)/ent \
		--workpath $(BUILD)/pyinstaller-ent \
		--specpath $(BUILD)/pyinstaller-ent \
		--add-data "$(CURDIR)/models.json:." \
		--add-data "$(CURDIR)/nvidia.ico:." \
		--add-data "$(CURDIR)/nvidia.png:." \
		zrouter-gui.py
	cp nvidia.ico nvidia.png make_icon.py zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py zrouter-gui.py models.json zrouter $(DIST)/ent/
	chmod +x $(DIST)/ent/zrouter
	@echo "==> Enterprise package ready in $(DIST)/ent/"
	@echo "==> GUI: $(DIST)/ent/zrouter-enterprise"
	@echo "==> CLI: $(DIST)/ent/zrouter"

build\:android: setup lint test ## Build Android package (requires Buildozer)
	@echo "==> Building Android package"
	@mkdir -p $(DIST)/android
	$(VENV_PYTHON) -m py_compile zrouter.py zrouter_contracts.py zrouter_http.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py test_zrouter.py zrouter_core.py zrouter_bot.py zrouter-gui.py
	cp nvidia.ico nvidia.png make_icon.py zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py zrouter-gui.py models.json zrouter $(DIST)/android/
	chmod +x $(DIST)/android/zrouter
	@printf '[app]\ntitle = zrouter\npackage.name = zrouter\npackage.domain = com.nvidia.router\nsource.dir = .\nsource.include_exts = py,png,jpg,kv,atlas\nversion = 1.0\nrequirements = python3,kivy,requests\nosx.python_version = 3\nosx.kivy_version = 2.1.0\nandroid.archs = arm64-v8a\nandroid.api = 31\nandroid.minapi = 24\n' > $(DIST)/android/buildozer.spec
	@echo "==> Android package ready in $(DIST)/android/"
	@echo "==> To build APK: cd $(DIST)/android && buildozer android debug"

build\:ios: setup lint test ## Build iOS package (requires BeeWare/Kivy, macOS only)
	@echo "==> Building iOS package"
	@mkdir -p $(DIST)/ios
	$(VENV_PYTHON) -m py_compile zrouter.py zrouter_contracts.py zrouter_http.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py test_zrouter.py zrouter_core.py zrouter_bot.py zrouter-gui.py
	cp nvidia.ico nvidia.png make_icon.py zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py zrouter-gui.py models.json zrouter $(DIST)/ios/
	chmod +x $(DIST)/ios/zrouter
	@printf '// swift-tools-version:5.5\nimport PackageDescription\n\nlet package = Package(\n    name: "zrouter",\n    platforms: [.iOS(.v15)],\n    products: [\n        .executable(name: "zrouter", targets: ["zrouter"])\n    ],\n    targets: [\n        .executableTarget(\n            name: "zrouter",\n            dependencies: [],\n            path: "."\n        )\n    ]\n)\n' > $(DIST)/ios/Package.swift
	@echo "==> iOS package ready in $(DIST)/ios/"
	@echo "==> To build: cd $(DIST)/ios && swift build (macOS required)"

# --------------------------------------------------------------------------- #
# zrouter executable entry point
# --------------------------------------------------------------------------- #

build\:zrouter: setup lint test ## Build zrouter CLI entry point
	@echo "==> Building zrouter executable"
	@chmod +x zrouter
	@mkdir -p $(DIST)/bin
	cp zrouter $(DIST)/bin/zrouter
	cp zrouter.py zrouter_contracts.py zrouter_http.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py $(DIST)/bin/
	cp models.json $(DIST)/bin/models.json
	cp 
	cp nvidia.ico $(DIST)/bin/nvidia.ico
	cp nvidia.png $(DIST)/bin/nvidia.png
	cp make_icon.py $(DIST)/bin/make_icon.py
	@echo "==> zrouter ready: $(DIST)/bin/zrouter"

build\:zbot: setup lint test ## Build zbot CLI executable using PyInstaller (cross-platform)
	@echo "==> Building zbot CLI executable"
	@mkdir -p $(DIST)/dev
	$(VENV_PYTHON) -m PyInstaller \
		--noconfirm \
		--clean \
		--onefile \
		--icon nvidia.ico \
		--name zbot \
		--distpath $(DIST)/dev \
		--workpath $(BUILD)/pyinstaller-zbot \
		--specpath $(BUILD)/pyinstaller-zbot \
		zrouter.py
	cp nvidia.ico nvidia.png make_icon.py models.json $(DIST)/dev/
	@echo "==> Zbot executable ready: $(DIST)/dev/zbot"

build\:packages: setup lint test ## Build all Python packages (wheel + sdist)
	@echo "==> Building Python packages"
	@mkdir -p $(DIST)/packages
	$(VENV_PYTHON) -m build
	@echo "==> Python packages ready in $(DIST)/"

build\:wheel: setup lint test ## Build wheel distribution
	@echo "==> Building wheel package"
	@mkdir -p $(DIST)/wheel
	$(VENV_PYTHON) -m pip wheel --no-deps --wheel-dir $(DIST)/wheel .
	@echo "==> Wheel package ready in $(DIST)/wheel/"

build\:sdist: setup lint test ## Build source distribution
	@echo "==> Building source distribution"
	@mkdir -p $(DIST)/sdist
	$(VENV_PYTHON) -m build --sdist --outdir $(DIST)/sdist
	@echo "==> Source distribution ready in $(DIST)/sdist/"

install\:zrouter: build\:zrouter ## Install zrouter to /usr/local/bin (or PREFIX)
	@echo "==> Installing zrouter to $(PREFIX)/bin"
	@mkdir -p "$(PREFIX)/bin"
	cp zrouter "$(PREFIX)/bin/zrouter"
	chmod +x "$(PREFIX)/bin/zrouter"
	@echo "==> Installed. Run: zrouter providers"

uninstall\:zrouter: ## Remove zrouter from $(PREFIX)/bin
	@echo "==> Removing zrouter from $(PREFIX)/bin"
	rm -f "$(PREFIX)/bin/zrouter"
	@echo "==> Removed"

zrouter: build\:zrouter ## Alias for build:zrouter
	@echo "==> zrouter executable at ./zrouter"

gui: ## Launch zrouter GUI
	@echo "==> Launching zrouter GUI"
	$(VENV_PYTHON) zrouter-gui.py

# --------------------------------------------------------------------------- #
# Docker targets
# --------------------------------------------------------------------------- #

docker\:build: ## Build Docker image
	@echo "==> Building Docker image"
	docker build -t zrouter:latest .
	docker tag zrouter:latest zrouter:$$(date +%Y%m%d)
	@echo "==> Docker image ready: zrouter:latest"

docker\:run: docker\:build ## Run Docker container (requires NVIDIA_API_KEYS)
	@echo "==> Running Docker container"
	@if [ -z "$(NVIDIA_API_KEYS)" ]; then \
		echo "Warning: NVIDIA_API_KEYS not set. Set it before running:"; \
		echo "  export NVIDIA_API_KEYS=\"nvapi-aaa,nvapi-bbb\""; \
	fi
	docker run --rm -d \
		--name zrouter \
		-p 8000:8000 \
		-e NVIDIA_API_KEYS="$$NVIDIA_API_KEYS" \
		-e NVIDIA_BASE_URL="$$NVIDIA_BASE_URL" \
		-e NVIDIA_RPM="$$NVIDIA_RPM" \
		-e NVIDIA_CACHE_TTL="$$NVIDIA_CACHE_TTL" \
		-e NVIDIA_TIMEOUT="$$NVIDIA_TIMEOUT" \
		-e NVIDIA_MAX_WAIT="$$NVIDIA_MAX_WAIT" \
		zrouter:latest \
		serve --host 0.0.0.0 --port 8000
	@echo "==> Container running at http://localhost:8000/v1"
	@echo "==> Test: curl http://localhost:8000/health"

docker\:up: docker\:run ## Alias for docker:run

