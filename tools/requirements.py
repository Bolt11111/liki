"""Compile persistent SRS traceability; never infer acceptance from file existence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/LIKI_SRS.md"
REGISTRY = ROOT / "requirements_registry.json"
HARD = re.compile(r"\b(?:MUST|SHALL)(?: NOT)?\b")
HEADING = re.compile(r"^(#{1,6})\s+(.*)")


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def owner(anchor: str) -> tuple[str, int]:
    section = anchor.split(" ")[0].rstrip(".")
    n = section.split(".")[0]
    if n in {"8", "10"}:
        return "inference", 2
    if n in {"9", "29"}:
        return "scheduler", 3
    if n in {"11", "12", "27", "28"}:
        return "research", 4
    if n in {"13", "13A"}:
        return "data", 5
    if n in {"17", "18", "38A"}:
        return "finance", 6
    if n in {"14", "15", "16", "19", "20"} or n.startswith("G"):
        return "evaluation", 7
    if n in {"21", "22", "23", "24"}:
        return "governance", 9
    if n in {"31", "37", "38", "38B"}:
        return "operations", 10
    if n in {"25", "26", "28A", "30", "32", "32A"}:
        return "risk_security_reliability", 11
    if n in {"33", "34", "39", "40", "41", "42", "43A"}:
        return "acceptance", 12
    return "core", 1


def extract(text: str) -> list[dict]:
    """Keep a directive's subordinate list with it; ignore quoted/example blocks."""
    result: list[dict] = []
    sections: list[tuple[int, str]] = []
    lines = text.splitlines()
    fenced = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            fenced = not fenced
            i += 1
            continue
        if fenced or line.startswith(">"):
            i += 1
            continue
        match = HEADING.match(line)
        if match:
            level, title = len(match[1]), match[2]
            sections = [(depth, name) for depth, name in sections if depth < level]
            sections.append((level, title))
            i += 1
            continue
        anchor = sections[-1][1] if sections else "preamble"
        parents = [t for _, t in sections]
        informative = any(t.startswith("43.") or t.startswith("Additional hardening") for t in parents)
        constitutional = any(t.startswith("C-") for t in parents)
        acceptance = any(t.startswith("34.") for t in parents)
        directive = bool(HARD.search(line)) or ((constitutional or acceptance) and bool(line.strip()))
        if directive and not informative and not line.startswith(("---", "|")):
            start = i
            block = [line]
            i += 1
            # A list after a normative introduction is part of the requirement, not lost prose.
            while i < len(lines):
                nxt = lines[i]
                if HEADING.match(nxt) or nxt.startswith(("```", "---", ">")):
                    break
                if not nxt.strip():
                    if i + 1 < len(lines) and re.match(r"^(?:- |\d+\. )", lines[i + 1]) and block[-1].rstrip().endswith(":"):
                        block.append(nxt)
                        i += 1
                        continue
                    break
                if HARD.search(nxt) and not re.match(r"^(?:- |\d+\. )", nxt):
                    break
                block.append(nxt)
                i += 1
            requirement = "\n".join(block).strip()
            module, phase = owner(anchor)
            result.append({"source_anchor": anchor, "source_line": start + 1,
                           "requirement_text": requirement, "text_hash": digest(requirement),
                           "owning_module": module, "phase": phase,
                           "kind": "acceptance" if acceptance else "constitutional" if constitutional else "normative"})
            continue
        i += 1
    return result


def compile_registry(spec: str, previous: dict | None = None) -> dict:
    old = (previous or {}).get("requirements", [])
    lookup = {(r["source_anchor"], r["text_hash"]): r for r in old}
    entries = []
    for req in extract(spec):
        key = req["source_anchor"], req["text_hash"]
        prior = lookup.pop(key, None)
        entry = prior or {"requirement_id": "LKI-REQ-" + str(uuid.uuid4()),
                          "introduced_by": "LIKI_SRS_v1.4", "status": "NOT_STARTED",
                          "criticality": "CRITICAL", "implementation_refs": [], "test_refs": [],
                          "acceptance_evidence": [], "dependencies": [], "history": [],
                          "cross_cutting": ["constitution", "provenance", "authorization", "units", "idempotency"]}
        entries.append({**entry, **req})
    if lookup:
        raise ValueError("Requirements changed/disappeared; explicit retained-ID revision or governance supersession required")
    return {"schema_version": 1, "srs_version": "1.4", "source_hash": digest(spec), "requirements": entries}


def validate(registry: dict, spec: str, *, acceptance: bool = False) -> list[str]:
    errors = []
    extracted = extract(spec)
    expected = {(x["source_anchor"], x["text_hash"]) for x in extracted}
    entries = registry["requirements"]
    actual = {(x["source_anchor"], x["text_hash"]) for x in entries}
    if expected != actual or len(extracted) != len(entries):
        errors.append("SRS coverage mismatch: missing, extra, or duplicate directive")
    ids = [r["requirement_id"] for r in entries]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate persistent requirement ID")
    if registry["source_hash"] != digest(spec):
        errors.append("Source hash changed without registry review")
    for entry in entries:
        rid = entry["requirement_id"]
        if digest(entry["requirement_text"]) != entry["text_hash"]:
            errors.append(f"{rid}: text hash mismatch")
        for ref in entry["implementation_refs"] + entry["test_refs"]:
            path = (ROOT / ref.split("::")[0]).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file():
                errors.append(f"{rid}: invalid reference {ref}")
        if entry["status"] == "ACCEPTED" or acceptance:
            if not all(entry[field] for field in ("implementation_refs", "test_refs", "acceptance_evidence")):
                errors.append(f"{rid}: missing implementation/test/acceptance evidence")
            if entry["status"] != "ACCEPTED":
                errors.append(f"{rid}: not accepted ({entry['status']})")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("bootstrap", "check", "report", "acceptance"))
    args = parser.parse_args()
    spec = SPEC.read_text()
    registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else None
    if args.action == "bootstrap":
        registry = compile_registry(spec, registry)
        REGISTRY.write_text(json.dumps(registry, indent=2) + "\n")
    if registry is None:
        raise SystemExit("Missing persistent registry; bootstrap first")
    errors = validate(registry, spec, acceptance=args.action == "acceptance")
    counts: dict[str, int] = {}
    for r in registry["requirements"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(json.dumps({"requirements": len(registry["requirements"]), "status": counts,
                      "errors": errors, "accepted": not errors and set(counts) == {"ACCEPTED"}}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
