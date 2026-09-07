import copy

import pytest

from tools.requirements import compile_registry, extract, validate


def test_ids_survive_insertion():
    before = "# 1. Rules\nA MUST be stable.\n\nB SHALL fail closed.\n"
    first = compile_registry(before)
    after = "# 1. Rules\nNew MUST work.\n\nA MUST be stable.\n\nB SHALL fail closed.\n"
    second = compile_registry(after, first)
    assert [r["requirement_id"] for r in second["requirements"]][1:] == [r["requirement_id"] for r in first["requirements"]]


def test_changed_text_requires_explicit_revision():
    first = compile_registry("# 1\nA MUST work.\n")
    with pytest.raises(ValueError, match="explicit"):
        compile_registry("# 1\nA MUST be optional.\n", first)


def test_examples_quotes_and_references_are_not_requirements():
    text = "# 1\n```\nMUST ignore\n```\n> MUST ignore\n\nA MUST include:\n\n- foo;\n- bar.\n\n# 43. References\nMUST ignore\n"
    result = extract(text)
    assert len(result) == 1
    assert "- bar." in result[0]["requirement_text"]


def test_acceptance_cannot_be_inferred_from_registry_presence():
    spec = "# 1\nA MUST work.\n"
    registry = compile_registry(spec)
    assert not validate(registry, spec)
    assert validate(registry, spec, acceptance=True)
    corrupt = copy.deepcopy(registry)
    corrupt["requirements"][0]["status"] = "ACCEPTED"
    assert validate(corrupt, spec)


def test_omitted_critical_requirement_is_rejected():
    spec = "# 1\nA MUST work.\n"
    registry = compile_registry(spec)
    registry["requirements"] = []
    assert validate(registry, spec)


def test_explicit_requirement_and_artifact_lists_are_not_omitted():
    spec = "# G5 — Full Protocol Backtest\nRequirements:\n\n- pinned code;\n- complete ledger.\n\n" \
           "# G6 — Economics\nMust evaluate relevant:\n\n- fees;\n- funding.\n\n" \
           "# 17.2 Required outputs\nEvery full backtest artifact includes:\n\n- gross PnL;\n- net PnL.\n\n" \
           "# 17.6 Tiers\nEvery experiment declares one reproducibility tier:\n\n- BITWISE;\n- STATISTICAL.\n"
    entries = extract(spec)
    assert len(entries) == 4
    assert "complete ledger" in entries[0]["requirement_text"]
    assert "net PnL" in entries[2]["requirement_text"]
    assert not validate(compile_registry(spec), spec)


def test_new_list_contracts_preserve_existing_requirement_ids():
    original = "# 17.3 Accounting\nMoney MUST be exact.\n"
    before = compile_registry(original)
    after = compile_registry(original + "\n# G5\nRequirements:\n\n- replay.\n", before)
    assert after["requirements"][0]["requirement_id"] == before["requirements"][0]["requirement_id"]
    assert after["requirements"][1]["status"] == "NOT_STARTED"
