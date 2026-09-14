from collections import Counter

from app.evaluation.hybrid import (
    DATASET_VERSION,
    SCENARIO_COUNT,
    SCENARIO_END,
    build_hybrid_scenarios,
    scenario_dataset_hash,
)


def test_hybrid_scenarios_are_balanced_and_chronologically_valid():
    scenarios = build_hybrid_scenarios()

    assert len(scenarios) == SCENARIO_COUNT
    assert len({scenario.case_id for scenario in scenarios}) == SCENARIO_COUNT
    assert Counter(scenario.expected_district for scenario in scenarios) == {
        "San Joaquin": 30,
        "Barrantes": 30,
        "Llorente": 30,
    }
    assert Counter(scenario.channel for scenario in scenarios) == {
        "anonymous": 23,
        "identified_full": 31,
        "identified_partial": 18,
        "staff": 18,
    }
    assert all(
        scenario.expected_event_at <= scenario.recorded_at <= SCENARIO_END
        for scenario in scenarios
    )


def test_hybrid_actor_context_excludes_gold_classification_labels():
    scenario = build_hybrid_scenarios()[0]

    actor_context = scenario.actor_context()

    assert "expected_category" not in actor_context
    assert "cluster_group" not in actor_context
    assert scenario.expected_category not in actor_context.values()
    assert len(scenario_dataset_hash([scenario])) == 64
    assert DATASET_VERSION == "hybrid-flores-v1"
