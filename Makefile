PYTHON ?= python3
PYTHONPATH_DIR := usr/share/openmediavault-notifier
PHP_FILES := $(wildcard usr/share/openmediavault/engined/*/*.inc)
YAML_FILES := $(wildcard usr/share/openmediavault/workbench/*/*.yaml)
JSON_FILES := $(wildcard usr/share/openmediavault/datamodels/*.json)

.PHONY: all test lint build clean

all:
	@true

test:
	PYTHONPATH=$(PYTHONPATH_DIR) $(PYTHON) -B -m unittest discover -s tests -v

lint:
	$(PYTHON) -B -m compileall -q $(PYTHONPATH_DIR) tests
	$(PYTHON) -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' usr/sbin/omv-notifier
	@for f in $(PHP_FILES); do php -l $$f || exit 1; done
	@$(PYTHON) -c 'import json,sys; [json.load(open(f)) for f in sys.argv[1:]]' $(JSON_FILES)
	@$(PYTHON) -c 'import sys,yaml; [yaml.safe_load(open(f)) for f in sys.argv[1:]]' $(YAML_FILES)
	@echo "lint ok"

build:
	dpkg-buildpackage -us -uc -b

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
