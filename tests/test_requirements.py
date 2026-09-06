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
