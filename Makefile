PYTHON ?= python3

.PHONY: dist test check check-external reproducible compare-genera audit-runtime-names clean

dist:
	$(PYTHON) scripts/build.py

test:
	$(PYTHON) -m unittest discover -s tests -v

check: dist test
	$(PYTHON) scripts/check_dist.py

check-external: check
	$(PYTHON) scripts/check_dist.py --external-tools

reproducible:
	$(PYTHON) scripts/check_reproducibility.py

compare-genera: dist
	$(PYTHON) scripts/compare_legacy_bdf.py

audit-runtime-names:
	$(PYTHON) scripts/check_runtime_name_evidence.py

clean:
	rm -rf -- dist
