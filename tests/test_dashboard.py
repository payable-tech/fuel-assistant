# Tests that the Plans view never waits for Samsara on a plan built before, and which plans the background loop builds.
import time

import pytest

from jobs import dashboard


# Replaces the slow build (DB + Samsara) with one that counts its calls, on an empty cache; returns the calls.
@pytest.fixture
def builds(monkeypatch):
    calls = []

    # Records the call and keeps a payload numbered by how many builds there were.
    def build(plan_id):
        calls.append(plan_id)
        payload = {"build": len(calls)}
        dashboard._trips[plan_id] = (time.monotonic(), payload)
        return payload

    monkeypatch.setattr(dashboard, "_build", build)
    monkeypatch.setattr(dashboard, "_trips", {})
    return calls


# Waits up to a second for the background rebuild to have happened.
def wait_for(condition):
    deadline = time.monotonic() + 1
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)


# A plan never built waits for its build; a fresh build is reused; a stale one is answered at once and rebuilt behind.
def test_plan_answered_from_last_build(builds):
    assert dashboard.plan_payload(5) == {"build": 1}
    assert dashboard.plan_payload(5) == {"build": 1} and builds == [5]
    dashboard._trips[5] = (time.monotonic() - dashboard.TRIP_CACHE_S, {"build": 1})
    assert dashboard.plan_payload(5) == {"build": 1}
    wait_for(lambda: len(builds) == 2)
    assert dashboard.plan_payload(5) == {"build": 2}


# Each truck's newest plan is built once; after that only an open load's stale build is rebuilt.
def test_newest_plans_warmed(builds):
    stale = time.monotonic() - dashboard.TRIP_CACHE_S
    dashboard._trips.update({2: (stale, {}), 3: (stale, {}), 4: (time.monotonic(), {})})
    trucks = [{"plans": [{"plan_id": 1, "active": False}, {"plan_id": 9, "active": False}]},  # never built
              {"plans": [{"plan_id": 2, "active": True}]},  # open load, stale build
              {"plans": [{"plan_id": 3, "active": False}]},  # finished load, stale build
              {"plans": [{"plan_id": 4, "active": True}]},  # open load, fresh build
              {"plans": []}]  # no plan yet
    assert dashboard._to_warm(trucks) == [1, 2]
