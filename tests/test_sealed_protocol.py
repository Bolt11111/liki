import pytest

from liki.core import DomainError, content_hash, uid
from liki.research import Research, ResearchObject, Trial
from tests.test_research_evaluation import candidate


def declare(research, credentials, obj, family):
    research.trial(credentials["research"], Trial(trial_event_id=uid("TRIAL"), campaign_id=obj.campaign_id,
        trial_family_id=family, strategy_version_id=obj.object_id, trial_type="hypothesis",
        selection_reason="predeclared holdout protocol fixture", semantic_configuration={"version": 1},
        dataset_snapshot_ids=(obj.artifact_id,), metric_ids=("net-pnl",), operation_key=uid("OP")))


def test_sealed_descendant_cannot_requery_by_renaming_family(store, credentials):
    research = Research(store)
    parent, _ = candidate(store, credentials)
    family, renamed_family, holdout = uid("FAMILY"), uid("FAMILY"), uid("HOLDOUT")
    with store.transaction(credentials["sealed_evaluator"]) as (conn, actor):
        aid = store.put_artifact(conn, actor, {"sealed_fixture": 42}, schema_name="sealed-data", classification="SEALED", policy_version="v1")
        conn.execute("INSERT INTO holdout_policies VALUES(%s,%s,'SEALED',%s,5,0,false,'v1','category')",
                     (holdout, aid, [family, renamed_family]))
    request = dict(holdout_id=holdout, strategy_version_id=parent.object_id, family_id=family,
                   request_hash=content_hash({"candidate": parent.object_id}), category="PASS")
    with pytest.raises(DomainError, match="SEALED_TRIAL_NOT_DECLARED"):
        research.sealed_result(credentials["sealed_evaluator"], **request)
    declare(research, credentials, parent, family)
    result = research.sealed_result(credentials["sealed_evaluator"], **request)
    assert research.sealed_result(credentials["sealed_evaluator"], **request) == result
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        research.sealed_result(credentials["sealed_evaluator"], **{**request, "category": "FAIL"})
    child = ResearchObject(object_id=uid("SV"), object_type="strategy_version", campaign_id=parent.campaign_id,
                           artifact_id=parent.artifact_id, parents={parent.object_id: "parameter_variant_of"})
    research.register(credentials["research"], child)
    declare(research, credentials, child, renamed_family)
    with pytest.raises(DomainError, match="SEALED_LINEAGE_ALREADY_EXPOSED"):
        research.sealed_result(credentials["sealed_evaluator"], **{**request,
            "strategy_version_id": child.object_id, "family_id": renamed_family,
            "request_hash": content_hash({"candidate": child.object_id})})
    with store.transaction(credentials["sealed_evaluator"]) as (conn, _):
        assert conn.execute("SELECT queries FROM holdout_policies WHERE holdout_id=%s", (holdout,)).fetchone()["queries"] == 1
