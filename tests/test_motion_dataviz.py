from __future__ import annotations

import pytest

from narovva.motion.dataviz import comparison_viz, format_metric, parse_metric, stats_viz


@pytest.mark.parametrize(
    "fact, text, unit, label",
    [
        ("67% cheaper per token", "67%", "%", "cheaper per token"),
        ("3.2x faster responses", "3.2x", "x", "faster responses"),
        ("$1.2B saved by customers", "$1.2B", "$", "saved by customers"),
        ("14 models updated", "14", "", "models updated"),
        ("1,200 jobs cut", "1,200", "", "jobs cut"),
        ("€120 million raised", "€120M", "€", "raised"),
        ("40 percent of users", "40%", "%", "of users"),
        # a number that isn't first keeps the whole sentence as its caption
        ("Launch costs cut by an estimated 60%", "60%", "%", "Launch costs cut by an estimated 60%"),
    ],
)
def test_parse_metric_reads_the_stated_number(fact, text, unit, label):
    metric = parse_metric(fact)
    assert format_metric(metric) == text
    assert metric["unit"] == unit and metric["label"] == label


def test_parse_metric_scales_magnitudes_for_comparison_only():
    metric = parse_metric("$1.2B saved")
    assert metric["value"] == 1.2 and metric["decimals"] == 1  # what counts up on screen
    assert metric["base"] == pytest.approx(1.2e9)              # what bars are scaled by


@pytest.mark.parametrize(
    "fact",
    ["Prices were cut on all API tiers", "The tier shipped in 2026", "GPT-4 remains available", "Results due in Q3", ""],
)
def test_parse_metric_ignores_sentences_without_a_statistic(fact):
    assert parse_metric(fact) is None


def test_a_year_does_not_hide_the_real_number():
    assert format_metric(parse_metric("In 2026 it cut prices by 67%")) == "67%"


def test_stats_viz_picks_a_chart_per_fact_and_never_shares_a_scale_across_units():
    items = stats_viz(["67% cheaper per token", "3.2x faster responses", "$1.2B saved", "No new hardware"])["items"]
    assert [i["type"] for i in items] == ["ring", "number", "number", "text"]
    assert items[0]["frac"] == pytest.approx(0.67) and items[0]["text"] == "67%"
    assert "frac" not in items[1] and "frac" not in items[2]  # different units: no common scale
    assert items[3]["label"] == "No new hardware"


def test_stats_viz_draws_bars_to_one_scale_when_units_match():
    items = stats_viz(["$400M to cloud providers", "$1.2B to chipmakers", "12 firms involved"])["items"]
    assert [i["type"] for i in items] == ["bar", "bar", "number"]
    assert items[1]["frac"] == 1.0 and items[0]["frac"] == pytest.approx(1 / 3, abs=0.001)


def test_percentage_above_100_is_a_number_not_a_ring():
    assert stats_viz(["312% more engagement"])["items"][0]["type"] == "number"


def test_comparison_viz_scales_both_sides_and_states_the_change():
    viz = comparison_viz({"label_a": "Before", "value_a": "$15", "label_b": "After", "value_b": "$5"})
    assert viz["a"]["frac"] == 1.0 and viz["b"]["frac"] == pytest.approx(1 / 3, abs=0.001)
    assert viz["a"]["text"] == "$15" and viz["delta"] == "−67%"
    assert comparison_viz({"value_a": "10", "value_b": "12"})["delta"] == "+20%"
    assert comparison_viz({"value_a": "2", "value_b": "9"})["delta"] == "4.5x"
    assert comparison_viz({"value_a": "5", "value_b": "5"})["delta"] is None


@pytest.mark.parametrize(
    "pair",
    [
        None,
        {"value_a": "Slow", "value_b": "Fast"},     # not numbers
        {"value_a": "$15", "value_b": "5%"},        # different units
        {"value_a": "2024", "value_b": "2026"},     # years are labels, not magnitudes
    ],
)
def test_comparison_viz_refuses_to_imply_a_scale_it_does_not_have(pair):
    assert comparison_viz(pair) is None
