import json

import pytest

from tools.acceptance import record, test_results as read_results, validate_evidence
from tools.requirements import compile_registry, validate


@pytest.fixture
def evidence_project(tmp_path):
    spec = "# 1. Rule\nAn operation MUST be verified.\n"
    for path, text in {"docs/LIKI_SRS.md": spec, "uv.lock": "test-only lock",
                       "service.py": "def execute(): return 1\n",
                       "test_service.py": "def test_execute(): assert True\n"}.items():
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    registry = compile_registry(spec)
    entry = registry["requirements"][0]
    entry.update({"implementation_refs": ["service.py"], "test_refs": ["test_service.py::test_execute"],
                  "acceptance_evidence": ["evidence.json"], "status": "ACCEPTED"})
    return tmp_path, registry, entry


def xml(path, *, name="test_execute", result="", suite_attributes=""):
    file = path / "pytest.xml"
    file.write_text(f'<testsuites><testsuite {suite_attributes}><testcase classname="test_service" '
                    f'name="{name}">{result}</testcase></testsuite></testsuites>')
    return file


def test_evidence_binds_executed_parametrized_test_requirement_and_source(evidence_project):
    root, registry, entry = evidence_project
    manifest = record(registry, [entry["requirement_id"]], xml(root, name="test_execute[value]"), root)
    (root / "evidence.json").write_text(json.dumps(manifest))
    assert not validate_evidence(entry, registry["source_hash"], root)
    (root / "service.py").write_text("changed after test")
    assert "stale" in validate_evidence(entry, registry["source_hash"], root)[0]


@pytest.mark.parametrize("result", ['<failure message="bug"/>', '<error/>', '<skipped/>'])
def test_failing_or_skipped_tests_cannot_create_acceptance_evidence(evidence_project, result):
    root, registry, entry = evidence_project
    with pytest.raises(ValueError, match="no failures or skips"):
        record(registry, [entry["requirement_id"]], xml(root, result=result), root)


def test_collection_failure_cannot_be_hidden_by_passing_testcases(evidence_project):
    root, _, _ = evidence_project
    with pytest.raises(ValueError, match="collection"):
        read_results(xml(root, suite_attributes='errors="1"'))


def test_missing_required_test_and_cross_requirement_evidence_are_rejected(evidence_project):
    root, registry, entry = evidence_project
    with pytest.raises(ValueError, match="not executed"):
        record(registry, [entry["requirement_id"]], xml(root, name="test_other"), root)
    manifest = record(registry, [entry["requirement_id"]], xml(root), root)
    manifest["requirement_ids"] = ["another-requirement"]
    (root / "evidence.json").write_text(json.dumps(manifest))
    assert validate_evidence(entry, registry["source_hash"], root)


def test_unexecuted_status_and_missing_hashes_are_not_closure(evidence_project):
    root, registry, entry = evidence_project
    manifest = record(registry, [entry["requirement_id"]], xml(root), root)
    for changed in ({**manifest, "source_hashes": {}}, {**manifest, "tests": []},
                    {**manifest, "tests": [{"nodeid": entry["test_refs"][0], "status": "skipped"}]}):
        (root / "evidence.json").write_text(json.dumps(changed))
        assert validate_evidence(entry, registry["source_hash"], root)


def test_status_symbols_and_evidence_paths_fail_closed(evidence_project, monkeypatch):
    root, registry, entry = evidence_project
    monkeypatch.setattr("tools.requirements.ROOT", root)
    spec = (root / "docs/LIKI_SRS.md").read_text()
    entry["status"] = "FINISHED_TRUST_ME"
    assert any("unknown status" in error for error in validate(registry, spec))
    entry["status"] = "ACCEPTED"
    entry["test_refs"] = ["test_service.py::test_missing"]
    entry["acceptance_evidence"] = ["../outside.json"]
    errors = validate(registry, spec)
    assert any("missing test symbol" in error for error in errors)
    assert any("invalid acceptance evidence" in error for error in errors)
