PYTHON ?= python3

.PHONY: dist test check check-runtime check-external reproducible compare-genera audit-runtime-names clean

dist:
	$(PYTHON) scripts/build.py

test:
	$(PYTHON) -m unittest discover -s tests -v

check: dist test
	$(PYTHON) scripts/check_dist.py
	$(PYTHON) scripts/check_runtime_dist.py
	$(PYTHON) scripts/check_unicode_dist.py
	$(PYTHON) scripts/check_runtime_rendering.py --output dist

check-runtime: dist
	$(PYTHON) scripts/check_runtime_dist.py
	$(PYTHON) scripts/check_runtime_rendering.py --output dist

check-external: check
	$(PYTHON) scripts/check_dist.py --external-tools
	$(PYTHON) scripts/check_runtime_rendering.py --output dist --external

reproducible:
	$(PYTHON) scripts/check_reproducibility.py

compare-genera: dist
	$(PYTHON) scripts/compare_legacy_bdf.py

audit-runtime-names:
	$(PYTHON) scripts/check_runtime_name_evidence.py

clean:
	rm -rf -- dist
