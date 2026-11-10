"""Read-only engine replay evidence for a separately assembled room result."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from room.policy import digest, validate

if __package__:
    from . import replay, sim
else:
    import replay
    import sim


def _prediction(row: dict) -> tuple[str, dict, dict | None]:
    """Keep the committed lock and full unsigned forecast, without rewriting ids."""
    lock, pick = row["prediction_lock"], row["pick"]
    try:
        validate("PredictionLock", lock)
        if lock["life_id"] != row["life_id"]:
            raise ValueError("prediction life mismatch")
        if lock["state"] == "none":
            if pick is not None or lock["prediction_hash"] is not None:
                raise ValueError("prediction none mismatch")
            return row["nft_token_id"], deepcopy(lock), None
        validate("PredictionRequest", pick)
        unsigned = {key: value for key, value in pick.items() if key != "signature"}
        if (pick["life_id"] != row["life_id"] or pick["nft_token_id"] != row["nft_token_id"]
                or digest(unsigned) != lock["prediction_hash"]
                or sum(pick["payload"]["spread_bps"].values()) != 10_000):
            raise ValueError("prediction commitment mismatch")
        return row["nft_token_id"], deepcopy(lock), deepcopy(unsigned)
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid archived prediction") from None


def _predictions(rows: list[dict]) -> tuple[dict, dict]:
    locks, predictions = {}, {}
    for row in rows:
        token, lock, unsigned = _prediction(row)
        if lock["life_id"] in locks or lock["lock_ref"] in predictions:
            raise ValueError("duplicate archived prediction")
        locks[lock["life_id"]] = (token, lock)
        predictions[lock["lock_ref"]] = unsigned
    return locks, predictions


def _completed_life(game: sim.Sim, event: dict, locks: dict) -> dict:
    fighter = game.state["fighters"][event["fighter"]]
    token, lock = locks[fighter["life_id"]]
    if token != fighter["id"] or event.get("life_id", fighter["life_id"]) != fighter["life_id"]:
        raise ValueError("completed life identity mismatch")
    return {"life_id": fighter["life_id"], "nft_token_id": token,
            "prediction_lock": deepcopy(lock), "ko_count": str(fighter["life_kos"]),
            "inventory_hash": sim.digest(fighter["bag"]), "completed": True}


def _check_metadata(record: dict, game: sim.Sim, completed: list[dict]) -> None:
    """Check duplicated native archive fields; do not substitute wire formulas."""
    names = set(game.state["fighters"])
    # An admitted member may still have its delayed join beyond this boundary.
    names.update(row["fighter_id"] for row in game.state["inputs"] if row["kind"] == "join")
    names.update(life["nft_token_id"] for life in completed)
    seed = str(game.state["seed"])
    expected = {
        "segment_id": "segment:" + str(record["initial_state"]["tick"] // game.rules["segment_ticks"]),
        "life_ids": sorted(life["life_id"] for life in completed),
        "nft_token_ids": sorted(names),
        "rules_hash": game.rules_hash,
        "seed": seed,
        "seed_hash": sim.digest(seed),
        "inputs_hash": sim.digest(record["sealed"]["input_events"]),
        "predictions_log_hash": sim.digest(record["predictions"]),
    }
    if any(record["sealed"].get(key) != value for key, value in expected.items()):
        raise ValueError("archived derived metadata mismatch")


def replay_evidence(record: dict, rules: Mapping | None = None) -> dict:
    """Derive lives from actual KO/leave events while replaying archived commands.

    This checks the engine's existing archival commitment and final state, then
    compares independently replayed life/KO/inventory facts with the archive.
    Forecasts are checked against their immutable locks and returned unsigned.
    An initial live body retains its actual life id across segment boundaries.

    Output is engine evidence, not a portable wire seal or a signed result.
    The room adapter must select the forecasts for its actual event record and
    establish the source-owned cross-segment lock/start provenance contract.
    Neither event indices, ticks, lock ids nor archived bytes are rewritten here.
    """
    record = deepcopy(record)
    if record["sealed"]["completed"] is not True or record["sealed"]["tick_count"] != "1200":
        raise ValueError("complete 1200-tick archive required")
    locks, predictions = _predictions(record["predictions"])
    completed, input_lives = [], []

    def input_life(game: sim.Sim, row: dict) -> None:
        if row["kind"] in ("join", "spawn"):
            life_id = row["payload"].get("life_id", row["fighter_id"] + ":0")
        elif row["kind"] in ("intent", "leave"):
            fighter = game.state["fighters"].get(row["fighter_id"])
            if fighter is None:
                raise ValueError("command life evidence missing")
            life_id = fighter["life_id"]
        else:
            return
        input_lives.append(dict(kind=row["kind"], tick=str(game.state["tick"]),
            fighter_id=row["fighter_id"], sequence=str(row["sequence"]), life_id=life_id))

    def observe(game: sim.Sim) -> None:
        for event in game.state["events"]:
            if event["kind"] in ("ko", "leave"):
                try:
                    completed.append(_completed_life(game, event, locks))
                except (KeyError, TypeError):
                    raise ValueError("completed life evidence missing") from None

    # The replay's observer receives the replay instance, avoiding snapshot
    # serialization and observing each actual step before the next command.
    game = replay.replay_segment(record, rules, frame_sink=observe, encoder=lambda value: value,
                                 input_sink=input_life)
    if completed != record["sealed"]["lives"]:
        raise ValueError("archived completed life mismatch")
    _check_metadata(record, game, completed)
    return {"final_state_hash": game.state_hash(), "lives": completed,
            "predictions": predictions, "input_lives": input_lives,
            "engine_commitment": record["sealed"]["sealed_result_hash"]}
