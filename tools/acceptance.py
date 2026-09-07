"""Record executed pytest evidence; validate closure against pinned source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def local_file(root: Path, ref: str) -> Path:
    path = (root / ref).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("evidence references must resolve to repository files")
    return path


def test_results(xml: Path) -> list[dict]:
    root = ET.parse(xml).getroot()
    results = []
    for case in root.iter("testcase"):
        name, module = case.get("name", ""), case.get("classname", "")
        path = case.get("file") or module.replace(".", "/") + ".py"
        status = ("failed" if case.find("failure") is not None or case.find("error") is not None
                  else "skipped" if case.find("skipped") is not None else "passed")
        results.append({"nodeid": path + "::" + name, "status": status})
    if not results or any(result["status"] != "passed" for result in results):
        raise ValueError("acceptance evidence requires executed tests with no failures or skips")
    for suite in root.iter("testsuite"):
        if int(suite.get("errors", 0)) or int(suite.get("failures", 0)) or int(suite.get("skipped", 0)):
            raise ValueError("acceptance evidence cannot omit collection failures or skipped tests")
    return results


def matches(nodeid: str, ref: str) -> bool:
    return nodeid == ref or nodeid.startswith(ref + "[")


def record(registry: dict, ids: list[str], junit: Path, root: Path = ROOT) -> dict:
    entries = [entry for entry in registry["requirements"] if entry["requirement_id"] in ids]
    if len(entries) != len(set(ids)) or not entries:
        raise ValueError("every requested requirement ID must exist")
    results = test_results(junit)
    sources = {"uv.lock", "docs/LIKI_SRS.md"}
    for entry in entries:
        if not entry["implementation_refs"] or not entry["test_refs"]:
            raise ValueError("requirement lacks implementation/test traceability")
        for ref in entry["test_refs"]:
            if "::" not in ref or not any(matches(case["nodeid"], ref) for case in results):
                raise ValueError("requirement test was not executed: " + ref)
        sources.update(ref.split("::")[0] for ref in entry["implementation_refs"] + entry["test_refs"])
    return {"schema_version": 1, "recorded_at": datetime.now(UTC).isoformat(),
            "srs_source_hash": registry["source_hash"], "requirement_ids": sorted(set(ids)),
            "junit_sha256": file_hash(junit), "tests": results,
            "source_hashes": {ref: file_hash(local_file(root, ref)) for ref in sorted(sources)}}


def validate_evidence(entry: dict, source_hash: str, root: Path = ROOT) -> list[str]:
    errors = []
    required_paths = {ref.split("::")[0] for ref in entry["implementation_refs"] + entry["test_refs"]}
    required_paths.update({"uv.lock", "docs/LIKI_SRS.md"})
    for ref in entry["acceptance_evidence"]:
        try:
            manifest = json.loads(local_file(root, ref).read_text())
            if (manifest["schema_version"] != 1 or manifest["srs_source_hash"] != source_hash
                    or entry["requirement_id"] not in manifest["requirement_ids"]):
                raise ValueError("evidence does not bind this requirement and SRS")
            hashes = manifest["source_hashes"]
            if not required_paths <= set(hashes):
                raise ValueError("evidence omits required source/test hashes")
            for path, digest in hashes.items():
                if file_hash(local_file(root, path)) != digest:
                    raise ValueError("evidence is stale for " + path)
            cases = manifest["tests"]
            if not cases or any(case["status"] != "passed" for case in cases):
                raise ValueError("evidence contains unexecuted or failing tests")
            for test in entry["test_refs"]:
                if "::" not in test or not any(matches(case["nodeid"], test) for case in cases):
                    raise ValueError("evidence does not include required test " + test)
        except (ValueError, KeyError, TypeError, OSError) as error:
            errors.append(f"{entry['requirement_id']}: invalid acceptance evidence {ref}: {error}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requirement", action="append", required=True)
    parser.add_argument("--tests", nargs="+", default=["tests"])
    args = parser.parse_args()
    registry = json.loads((ROOT / "requirements_registry.json").read_text())
    if args.output.exists():
        parser.error("evidence manifests are immutable; choose a new output path")
    entries = [entry for entry in registry["requirements"] if entry["requirement_id"] in args.requirement]
    paths = {"uv.lock", "docs/LIKI_SRS.md", "tools/acceptance.py", "tools/requirements.py"}
    paths.update(ref.split("::")[0] for entry in entries
                 for ref in entry["implementation_refs"] + entry["test_refs"])
    baseline = {ref: file_hash(local_file(ROOT, ref)) for ref in sorted(paths)}
    command = [sys.executable, "-m", "pytest", *args.tests, "-q"]
    started_at = datetime.now(UTC).isoformat()
    with tempfile.TemporaryDirectory(prefix="liki-acceptance-") as directory:
        junit = Path(directory) / "results.xml"
        result = subprocess.run([*command, "--junitxml=" + str(junit)], cwd=ROOT, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)
        manifest = record(registry, args.requirement, junit)
    if any(file_hash(local_file(ROOT, ref)) != digest for ref, digest in baseline.items()):
        raise SystemExit("Source changed during verification; no acceptance evidence was recorded")
    manifest.update({"source_hashes": baseline, "started_at": started_at,
                     "command": ["python", "-m", "pytest", *args.tests, "-q"]})
    with args.output.open("x") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
