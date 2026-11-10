# make test: every check that needs nothing outside this repo (runs from a clean clone).
PY ?= python3
DEMO_DIR ?= .demo

.PHONY: demo desk test-desk
demo:
	$(PY) -B web/demo.py --output "$(DEMO_DIR)"

desk:
	$(PY) -B web/runtime.py --demo-dir "$(DEMO_DIR)"

test-desk:
	$(PY) -B web/test_desk.py ReviewerDesk.test_four_actions_follow_real_local_agent_forecast_and_checked_replay

.PHONY: test test-arena test-room test-members test-arrival
test:
	$(PY) -I tools/check_deps.py
	$(PY) -I tools/check_snap.py
	$(PY) -B tools/test_gate.py
	$(PY) -B tools/test_check_deps.py
	$(PY) -I lore/check_sheets.py --kits
	$(PY) -I lore/check_sheets.py --selftest
	$(PY) -I lore/check_personas.py
	$(PY) -I lore/check_personas.py --selftest
	$(MAKE) test-arena
	$(MAKE) test-room
	$(MAKE) test-members
	$(MAKE) test-arrival
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

test-room:
	cd .. && $(PY) -B -m unittest room.test_room room.test_identity room.test_policy room.test_recovery

test-members:
	$(PY) -B members/test_members.py MemberBoards.test_approved_b_flows_use_real_room_and_keep_recorded_answers
	$(MAKE) test-members-source

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
