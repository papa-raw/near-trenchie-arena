# make test: every check that needs nothing outside this repo (runs from a clean clone).
# GNU make 4 prints "Entering/Leaving directory" for -C and for sub-makes; README shows the output without them,
# so README runs (cd near && make …) and every recursive call below passes --no-print-directory.
MAKEFLAGS += --no-print-directory
PY ?= python3
DEMO_DIR ?= .demo

# make demo: re-simulate every segment in replay/MANIFEST and check it against its settle tx, read from testnet archival
# RPC (no key; network only). make rehearsal: the reviewer desk's synthetic local life (no network); make desk serves it.
.PHONY: demo rehearsal desk test-desk
demo:
	$(PY) -I replay/demo.py

rehearsal:
	$(PY) -B web/demo.py --output "$(DEMO_DIR)"

desk:
	$(PY) -B web/runtime.py --demo-dir "$(DEMO_DIR)"

test-desk:
	$(PY) -B web/test_desk.py ReviewerDesk.test_four_actions_follow_real_local_agent_forecast_and_checked_replay

.PHONY: test test-arena test-room test-members test-arrival test-chain
test:
	$(PY) -I tools/check_deps.py
	$(PY) -I tools/check_snap.py
	$(PY) -I tools/check_words.py --selftest
	$(PY) -I tools/check_words.py
	$(PY) -B tools/test_gate.py
	$(PY) -B tools/test_check_deps.py
	$(PY) -I lore/check_sheets.py --kits
	$(PY) -I lore/check_sheets.py --selftest
	$(PY) -I lore/check_personas.py
	$(PY) -I lore/check_personas.py --selftest
	$(MAKE) --no-print-directory test-arena
	$(MAKE) --no-print-directory test-room
	$(MAKE) --no-print-directory test-members
	$(MAKE) --no-print-directory test-arrival
	$(MAKE) --no-print-directory test-chain
	$(MAKE) --no-print-directory test-replay
	@echo "old-names: private mode only (needs the TRENCHIE_DENY_FILE env var; the retired-name list is not in this repo)"

test-arena:
	$(PY) -B arena/test_sim.py
	$(PY) -B arena/test_server.py
	$(PY) -B arena/test_bridge.py
	$(PY) -B arena/test_room_host.py
	$(PY) -B arena/test_cold_join.py
	$(PY) -B arena/test_snap_cold.py
	$(PY) -B arena/test_record_life_binding.py
	$(PY) -B arena/test_record_reuse.py
	$(PY) -B arena/test_record_applications.py RecordApplications.test_join_and_spawn_cannot_publish_one_application_twice
	$(PY) -B arena/test_policy.py
	$(PY) -B arena/test_replay.py
	$(PY) -B arena/test_engine_evidence.py
	$(PY) -B arena/test_returns.py
	$(PY) -B arena/test_balance.py
	$(PY) -B arena/test_predict.py

test-chain:
	$(PY) -I chain/test_chain.py
	$(PY) -I chain/test_predict_chain.py

.PHONY: test-replay
test-replay:
	$(PY) -B replay/test_demo.py

# Read every pinned settled batch back from archival RPC (no key; network only).
.PHONY: verify-batches
verify-batches:
	$(PY) -I chain/archival.py

test-room:
	cd .. && $(PY) -B -m unittest room.test_room room.test_identity room.test_policy room.test_recovery

test-members:
	$(PY) -B members/test_members.py MemberBoards.test_approved_b_flows_use_real_room_and_keep_recorded_answers
	$(MAKE) --no-print-directory test-members-source

# Focused cases for fault exits, applied timing and current-render captures.
.PHONY: test-members-repair
test-members-repair:
	$(PY) -B members/test_member_repair.py MemberRepair.test_fault_exit_context_and_applied_terms_use_fresh_room_facts

.PHONY: test-members-presentation
test-members-presentation:
	$(PY) -B members/test_member_presentation.py MemberPresentation.test_applied_and_fault_return_match_additive_drawings

.PHONY: test-members-source
test-members-source:
	$(PY) -B members/test_member_source.py MemberSource
	$(PY) -B members/test_member_unpublished.py MemberUnpublished.test_signed_unpublished_state_stays_distinct_from_failure_and_publish_requires_review

test-arrival:
	$(PY) -B onboarding/test_arrival.py Arrival
