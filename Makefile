# Trenchie Arena: root Makefile. Run from the repository root.
#   make setup  install the Python packages, and the browser the member-page cases drive (needs the network)
#   make test   every check that needs nothing outside this repo (runs from a clean clone)
#   make demo   NOT BUILT yet: says so and exits 2
#   make live   the local DEV host with the house for LIVE_SECONDS (default 30), then a summary of what ran:
#               the live model with NEARAI_API_KEY set, else the deterministic house (it says so); without
#               TRENCHIE_BLOCKLIST every feed line is muted and it prints "guard list missing"
#   make play   everything for a local click-through: the DEV arena (a keyless house; LIVE=1 for the live house on
#               the NEAR AI Cloud key) and the same-origin web server; prints the URLs and agent commands; Ctrl-C stops it
#   make gate   the maintainers' pre-push scans (needs pattern files kept outside the repo; see near/tools/gate.py)
PY ?= python3

.PHONY: setup test demo live play gate

setup:
	$(PY) -m pip install -r near/requirements.txt
	cd near/members && npm ci && npx playwright install chromium

test:
	$(MAKE) --no-print-directory -C near test

demo:
	@echo "NOT BUILT: make demo (re-simulate the recorded segments and check each final-state hash against its settle transaction on archival RPC) does not exist yet."
	@echo "What runs today: (cd near && make demo) builds the reviewer-desk rehearsal from synthetic local records."
	@exit 2

LIVE_SECONDS ?= 30
LIVE_BUDGET ?= auto

live:
	$(PY) -B near/house/live_run.py --seconds $(LIVE_SECONDS) --budget $(LIVE_BUDGET)

# make play [PORT=8181] [ARENA_PORT=8765] [HOUSE=keyed|dev] [LIVE=1]; only LIVE=1 exactly goes live (LIVE=0/no/false
# stay keyless); exec, so make waits on it and Ctrl-C reaches it
play:
	exec $(PY) -B near/tools/play_local.py $(if $(filter 1,$(LIVE)),--live,) $(if $(PORT),--web-port $(PORT),) \
	  $(if $(ARENA_PORT),--arena-port $(ARENA_PORT),) $(if $(HOUSE),--house $(HOUSE),)

gate:
	$(PY) -I near/tools/gate.py
