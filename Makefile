# Trenchie Arena: root Makefile. Run from the repository root.
#   make setup  install the Python packages, and the browser the member-page cases drive (needs the network)
#   make test   every check that needs nothing outside this repo (runs from a clean clone)
#   make demo   NOT BUILT yet: says so and exits 2
#   make live   NOT BUILT yet: says so and exits 2
#   make gate   the maintainers' pre-push scans (needs pattern files kept outside the repo; see near/tools/gate.py)
PY ?= python3

.PHONY: setup test demo live gate

setup:
	$(PY) -m pip install -r near/requirements.txt
	cd near/members && npm ci && npx playwright install chromium

test:
	$(MAKE) -C near test

demo:
	@echo "NOT BUILT: make demo (re-simulate the recorded segments and check each final-state hash against its settle transaction on archival RPC) does not exist yet."
	@echo "What runs today: make -C near demo builds the reviewer-desk rehearsal from synthetic local records."
	@exit 2

live:
	@echo "NOT BUILT: make live (snap in to the hosted arena) does not exist yet. No hosted arena is up."
	@echo "What runs today: the synthetic local run in near/SNAP.md."
	@exit 2

gate:
	$(PY) -I near/tools/gate.py
