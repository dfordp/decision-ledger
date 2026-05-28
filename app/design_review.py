"""
Design-data-first ReviewGraph intake.

This module treats engineering drawing/design revisions as the primary source
for ReviewGraph. DFMEA entries and historical incidents are linked as evidence,
not used as the starting point.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from psycopg2.extras import Json

from app.database import execute_query, fetch_all, fetch_one
from app.review_graph import (
    _ensure_graph_edge,
    _ensure_graph_node,
    _get_rule_id,
    _max_risk,
    get_review_session,
)
from app.drawing_validation import (
    build_drawing_review_summary,
    get_mock_bracket_variants,
    persist_drawing_extraction,
    update_reference_baseline_and_pairs,
    validate_drawing_revision,
)


FEATURE_BUCKETS = {
    "dimensions": "DIMENSION",
    "tolerances": "TOLERANCE",
    "gdt": "GD_T",
    "materials": "MATERIAL",
    "fasteners": "FASTENER",
    "interfaces": "INTERFACE",
    "annotations": "ANNOTATION",
    "manufacturing_constraints": "MANUFACTURING_CONSTRAINT",
    "validation_requirements": "VALIDATION_REQUIREMENT",
    "inspection_requirements": "INSPECTION_REQUIREMENT",
}

DRAWING_ASSET_DIR = Path("app/static/drawings")


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _jsonable(row: Any) -> Any:
    if isinstance(row, dict):
        return {key: _jsonable(value) for key, value in row.items()}
    if isinstance(row, list):
        return [_jsonable(value) for value in row]
    if hasattr(row, "isoformat"):
        return row.isoformat()
    return row


def _feature_key(feature_type: str, item: dict, index: int) -> str:
    raw = item.get("id") or item.get("name") or item.get("feature") or item.get("callout") or index
    return f"{feature_type}:{_normalize_key(raw)}"


def _iter_features(design_data: dict) -> Iterable[dict]:
    for bucket, feature_type in FEATURE_BUCKETS.items():
        values = design_data.get(bucket) or []
        if isinstance(values, dict):
            values = [
                {"name": key, "value": value}
                for key, value in values.items()
            ]

        for index, item in enumerate(values, start=1):
            if not isinstance(item, dict):
                item = {"value": item}
            key = _feature_key(feature_type, item, index)
            yield {
                "feature_type": feature_type,
                "feature_key": key,
                "display_name": item.get("name") or item.get("feature") or item.get("callout") or key,
                "value": item,
                "unit": item.get("unit"),
                "source_reference": item.get("source") or item.get("sheet") or item.get("zone"),
                "criticality": _classify_feature_criticality(feature_type, item),
            }


def _classify_feature_criticality(feature_type: str, item: dict) -> str:
    text = " ".join(str(value).lower() for value in item.values())
    if item.get("safety_critical") is True or "safety" in text or "airbag" in text or "brake" in text:
        return "SAFETY_CRITICAL"
    if feature_type in {"TOLERANCE", "INTERFACE", "MATERIAL"}:
        return "HIGH"
    if feature_type in {"FASTENER", "MANUFACTURING_CONSTRAINT", "VALIDATION_REQUIREMENT", "INSPECTION_REQUIREMENT"}:
        return "HIGH"
    return "MEDIUM"


def _flatten_features(design_data: dict) -> dict:
    return {feature["feature_key"]: feature for feature in _iter_features(design_data or {})}


def _numeric(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _tolerance_band(item: dict) -> Optional[float]:
    plus = _numeric(item.get("plus") or item.get("upper"))
    minus = _numeric(item.get("minus") or item.get("lower"))
    if plus is not None and minus is not None:
        return abs(plus) + abs(minus)
    tol = _numeric(item.get("tolerance"))
    if tol is not None:
        return abs(tol) * 2
    return None


def diff_design_data(previous_data: dict, design_data: dict) -> list[dict]:
    old_features = _flatten_features(previous_data)
    new_features = _flatten_features(design_data)
    changes: list[dict] = []

    for key in sorted(set(old_features) | set(new_features)):
        old = old_features.get(key)
        new = new_features.get(key)
        if old == new:
            continue

        if old is None:
            change_type = f"{new['feature_type']}_ADDED"
            importance = new["criticality"]
            reason = "New drawing/design feature added."
        elif new is None:
            change_type = f"{old['feature_type']}_REMOVED"
            importance = old["criticality"]
            reason = "Existing drawing/design feature removed."
        else:
            change_type = f"{new['feature_type']}_CHANGED"
            importance = _classify_change_importance(old, new)
            reason = _change_reason(old, new)

        changes.append({
            "change_type": change_type,
            "feature_key": key,
            "field_path": key,
            "old_value": old["value"] if old else None,
            "new_value": new["value"] if new else None,
            "importance": importance,
            "deterministic_reason": reason,
        })

    return changes


def _classify_change_importance(old: dict, new: dict) -> str:
    if "SAFETY_CRITICAL" in {old.get("criticality"), new.get("criticality")}:
        return "SAFETY_CRITICAL"

    if new["feature_type"] == "TOLERANCE":
        old_band = _tolerance_band(old["value"])
        new_band = _tolerance_band(new["value"])
        if old_band is not None and new_band is not None and new_band < old_band:
            return "HIGH"

    if new["feature_type"] in {"MATERIAL", "INTERFACE", "FASTENER", "MANUFACTURING_CONSTRAINT"}:
        return "HIGH"

    old_nominal = _numeric(old["value"].get("nominal") or old["value"].get("value"))
    new_nominal = _numeric(new["value"].get("nominal") or new["value"].get("value"))
    if old_nominal is not None and new_nominal is not None:
        baseline = abs(old_nominal) if old_nominal else 1
        if abs(new_nominal - old_nominal) / baseline >= 0.05:
            return "HIGH"

    return "MEDIUM"


def _change_reason(old: dict, new: dict) -> str:
    if new["feature_type"] == "TOLERANCE":
        old_band = _tolerance_band(old["value"])
        new_band = _tolerance_band(new["value"])
        if old_band is not None and new_band is not None:
            if new_band < old_band:
                return "Tolerance band tightened; manufacturing capability and inspection method may be affected."
            if new_band > old_band:
                return "Tolerance band loosened; fit, function, and validation assumptions may change."
    if new["feature_type"] == "MATERIAL":
        return "Material callout changed; supplier capability, validation, and historical incident evidence must be reviewed."
    if new["feature_type"] in {"INTERFACE", "FASTENER"}:
        return "Assembly interface or fastener changed; downstream fit and propagation review is required."
    return "Feature value changed between design revisions."


def create_design_artifact(data: dict) -> dict:
    artifact = fetch_one("""
        INSERT INTO design_artifacts (
            artifact_number,
            title,
            artifact_type,
            domain,
            owning_team,
            supplier,
            material,
            linked_part_number,
            metadata_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (artifact_number)
        DO UPDATE SET
            title = EXCLUDED.title,
            artifact_type = EXCLUDED.artifact_type,
            domain = EXCLUDED.domain,
            owning_team = EXCLUDED.owning_team,
            supplier = EXCLUDED.supplier,
            material = EXCLUDED.material,
            linked_part_number = EXCLUDED.linked_part_number,
            metadata_json = design_artifacts.metadata_json || EXCLUDED.metadata_json,
            updated_at = NOW()
        RETURNING *
    """, (
        data["artifact_number"],
        data["title"],
        data.get("artifact_type", "ENGINEERING_DRAWING"),
        data.get("domain"),
        data.get("owning_team"),
        data.get("supplier"),
        data.get("material"),
        data.get("linked_part_number"),
        Json(data.get("metadata_json") or {}),
    ))
    return artifact


def create_design_revision(artifact_id: str, data: dict) -> dict:
    latest = fetch_one("""
        SELECT revision_sequence, design_data_json
        FROM design_revisions
        WHERE artifact_id = %s::uuid
        ORDER BY revision_sequence DESC
        LIMIT 1
    """, (artifact_id,))
    previous_data = latest["design_data_json"] if latest else {}
    next_sequence = data.get("revision_sequence") or ((latest["revision_sequence"] if latest else 0) + 1)
    revision_code = data.get("revision_code") or f"R{next_sequence}"
    design_data = data.get("design_data_json") or {}
    features = list(_iter_features(design_data))
    changes = diff_design_data(previous_data, design_data)

    revision = fetch_one("""
        INSERT INTO design_revisions (
            artifact_id,
            revision_code,
            revision_sequence,
            change_summary,
            source_filename,
            previous_data_json,
            design_data_json,
            extraction_summary_json,
            changed_by,
            approval_status
        )
        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, 'draft')
        RETURNING *
    """, (
        artifact_id,
        revision_code,
        next_sequence,
        data.get("change_summary"),
        data.get("source_filename"),
        Json(previous_data),
        Json(design_data),
        Json({
            "feature_count": len(features),
            "change_count": len(changes),
            "source": "structured_design_data",
        }),
        data.get("changed_by", "system"),
    ))

    drawing_counts = persist_drawing_extraction(str(revision["id"]), design_data)
    validation_results = validate_drawing_revision(str(revision["id"]), design_data)
    update_reference_baseline_and_pairs(str(revision["id"]), artifact_id, design_data)

    for feature in features:
        execute_query("""
            INSERT INTO design_extracted_features (
                design_revision_id,
                feature_type,
                feature_key,
                display_name,
                value_json,
                unit,
                source_reference,
                criticality
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)
        """, (
            revision["id"],
            feature["feature_type"],
            feature["feature_key"],
            feature["display_name"],
            Json(feature["value"]),
            feature["unit"],
            feature["source_reference"],
            feature["criticality"],
        ))

    for change in changes:
        execute_query("""
            INSERT INTO design_revision_changes (
                design_revision_id,
                change_type,
                feature_key,
                field_path,
                old_value,
                new_value,
                importance,
                deterministic_reason
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)
        """, (
            revision["id"],
            change["change_type"],
            change["feature_key"],
            change["field_path"],
            Json(change["old_value"]),
            Json(change["new_value"]),
            change["importance"],
            change["deterministic_reason"],
        ))

    execute_query("""
        UPDATE design_revisions
        SET extraction_summary_json = extraction_summary_json || %s
        WHERE id = %s::uuid
    """, (
        Json({
            **drawing_counts,
            "drawing_validation_result_count": len(validation_results),
            "validation_source": "deterministic_drawing_rules",
        }),
        revision["id"],
    ))

    return revision


def _load_design_review_context(design_revision_id: str) -> dict:
    revision = fetch_one("""
        SELECT
            dr.*,
            da.artifact_number,
            da.title as artifact_title,
            da.artifact_type,
            da.domain,
            da.owning_team,
            da.supplier,
            da.material,
            da.linked_part_number
        FROM design_revisions dr
        JOIN design_artifacts da ON dr.artifact_id = da.id
        WHERE dr.id = %s::uuid
    """, (design_revision_id,))
    if not revision:
        raise ValueError("Design revision not found")

    previous_revision = fetch_one("""
        SELECT id, revision_code, revision_sequence
        FROM design_revisions
        WHERE artifact_id = %s::uuid AND revision_sequence < %s
        ORDER BY revision_sequence DESC
        LIMIT 1
    """, (revision["artifact_id"], revision["revision_sequence"]))

    changes = fetch_all("""
        SELECT *
        FROM design_revision_changes
        WHERE design_revision_id = %s::uuid
        ORDER BY
            CASE importance WHEN 'SAFETY_CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
            feature_key
    """, (design_revision_id,))

    features = fetch_all("""
        SELECT *
        FROM design_extracted_features
        WHERE design_revision_id = %s::uuid
        ORDER BY feature_type, feature_key
    """, (design_revision_id,))

    drawing_entities = fetch_all("""
        SELECT *
        FROM drawing_feature_entities
        WHERE design_revision_id = %s::uuid
        ORDER BY entity_type, entity_key
    """, (design_revision_id,))

    drawing_dimensions = fetch_all("""
        SELECT *
        FROM drawing_dimensions
        WHERE design_revision_id = %s::uuid
        ORDER BY is_critical DESC, chain_key NULLS LAST, dimension_key
    """, (design_revision_id,))

    drawing_annotations = fetch_all("""
        SELECT *
        FROM drawing_annotations
        WHERE design_revision_id = %s::uuid
        ORDER BY annotation_type, annotation_key
    """, (design_revision_id,))

    drawing_validation_results = fetch_all("""
        SELECT *
        FROM drawing_validation_results
        WHERE design_revision_id = %s::uuid
        ORDER BY
            CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'MAJOR' THEN 1 WHEN 'MINOR' THEN 2 ELSE 3 END,
            rule_key
    """, (design_revision_id,))

    reference_pair = fetch_one("""
        SELECT rp.*, base.revision_code as baseline_revision_code
        FROM drawing_revision_pairs rp
        JOIN design_revisions base ON rp.baseline_revision_id = base.id
        WHERE rp.compared_revision_id = %s::uuid
        ORDER BY rp.created_at DESC
        LIMIT 1
    """, (design_revision_id,))

    linked_pfmea = fetch_one("""
        SELECT *
        FROM pfmea_records
        WHERE part_number = %s
        ORDER BY updated_at DESC NULLS LAST, created_at DESC
        LIMIT 1
    """, (revision.get("linked_part_number"),))

    dfmea_entries = []
    process_steps = []
    if linked_pfmea:
        process_steps = fetch_all("""
            SELECT id, step_number, step_name, function_hierarchy, design_intent, critical_parameters
            FROM process_steps
            WHERE pfmea_record_id = %s
            ORDER BY step_number
        """, (linked_pfmea["id"],))
        dfmea_entries = fetch_all("""
            SELECT
                pfe.id,
                pfe.process_step_id,
                pfe.process_step_number,
                ps.step_name as process_step_name,
                fm.canonical_name as failure_mode_name,
                pfe.potential_effect,
                pfe.rpn_user_calculated,
                pfe.rpn_suggested,
                pfe.rpn_risk_class
            FROM pfmea_failure_mode_entries pfe
            JOIN failure_mode_taxonomy fm ON pfe.failure_mode_id = fm.id
            LEFT JOIN process_steps ps ON pfe.process_step_id = ps.id
            WHERE pfe.pfmea_record_id = %s
            ORDER BY pfe.process_step_number, pfe.id
        """, (linked_pfmea["id"],))

    incidents = fetch_all("""
        SELECT
            hi.id,
            hi.part_number,
            hi.incident_date,
            hi.location,
            hi.description,
            hi.design_margin_loss,
            hi.severity_actual,
            hi.impact_hours,
            hi.corrective_action,
            fmt.canonical_name as failure_mode_name
        FROM historical_incidents hi
        LEFT JOIN failure_mode_taxonomy fmt ON hi.failure_mode_id = fmt.id
        WHERE hi.part_number = %s
        ORDER BY hi.incident_date DESC
        LIMIT 10
    """, (revision.get("linked_part_number"),))

    return {
        "revision": revision,
        "previous_revision": previous_revision,
        "changes": changes,
        "features": features,
        "drawing_entities": drawing_entities,
        "drawing_dimensions": drawing_dimensions,
        "drawing_annotations": drawing_annotations,
        "drawing_validation_results": drawing_validation_results,
        "reference_pair": reference_pair,
        "linked_pfmea": linked_pfmea,
        "process_steps": process_steps,
        "dfmea_entries": dfmea_entries,
        "incidents": incidents,
    }


def _evaluate_design_rules(context: dict) -> list[dict]:
    validation_results = context.get("drawing_validation_results") or []
    if validation_results:
        rules = []
        for result in validation_results:
            affected_entities = result.get("affected_entities") or []
            affected_regions = result.get("affected_regions") or []
            severity = result.get("severity")
            rules.append({
                "rule_key": result["rule_key"],
                "triggered": True,
                "status": result["status"],
                "confidence": 94 if severity == "CRITICAL" else 88 if severity == "MAJOR" else 78,
                "title": result.get("title"),
                "explanation": (
                    f"{result.get('what_is_wrong')} Impact: {result.get('why_it_matters')}"
                ),
                "what_is_wrong": result.get("what_is_wrong"),
                "why_it_matters": result.get("why_it_matters"),
                "affected_entities": affected_entities,
                "affected_regions": affected_regions,
                "evidence": {
                    "validation_result_id": str(result["id"]),
                    "affected_entities": affected_entities,
                    "affected_regions": affected_regions,
                    "evidence": result.get("evidence_json") or {},
                },
                "recommended_actions": [result.get("recommended_action")],
            })
        return rules

    changes = context["changes"]
    incidents = context["incidents"]
    dfmea_entries = context["dfmea_entries"]

    tolerance_changes = [c for c in changes if "TOLERANCE" in c["change_type"]]
    safety_changes = [c for c in changes if c["importance"] == "SAFETY_CRITICAL"]
    material_changes = [c for c in changes if "MATERIAL" in c["change_type"]]
    interface_changes = [c for c in changes if "INTERFACE" in c["change_type"] or "FASTENER" in c["change_type"]]
    inspection_changes = [
        c for c in changes
        if "INSPECTION" in c["change_type"] or "TOLERANCE" in c["change_type"] or "MANUFACTURING_CONSTRAINT" in c["change_type"]
    ]
    high_rpn_entries = [
        entry for entry in dfmea_entries
        if (entry.get("rpn_user_calculated") or entry.get("rpn_suggested") or 0) > 70
    ]

    severe_incidents = [incident for incident in incidents if (incident.get("severity_actual") or 0) >= 8]

    return [
        {
            "rule_key": "DRAWING_TOLERANCE_TIGHTENED",
            "triggered": bool(tolerance_changes),
            "status": "WARN" if tolerance_changes else "SAFE",
            "confidence": 86 if tolerance_changes else 70,
            "explanation": f"{len(tolerance_changes)} tolerance-related drawing change(s) require manufacturing and inspection review." if tolerance_changes else "No tolerance-related drawing changes detected.",
            "evidence": tolerance_changes,
            "recommended_actions": ["Confirm supplier capability for tightened tolerances.", "Update inspection method and gauge plan."] if tolerance_changes else [],
        },
        {
            "rule_key": "SAFETY_CRITICAL_DIMENSION_CHANGED",
            "triggered": bool(safety_changes),
            "status": "BLOCK" if safety_changes else "SAFE",
            "confidence": 92 if safety_changes else 70,
            "explanation": f"{len(safety_changes)} safety-critical design feature(s) changed." if safety_changes else "No safety-critical design feature changes detected.",
            "evidence": safety_changes,
            "recommended_actions": ["Require design authority approval.", "Require validation evidence before release."] if safety_changes else [],
        },
        {
            "rule_key": "MATERIAL_SUBSTITUTION_REVIEW",
            "triggered": bool(material_changes),
            "status": "BLOCK" if material_changes and severe_incidents else "WARN" if material_changes else "SAFE",
            "confidence": 90 if material_changes and severe_incidents else 84 if material_changes else 70,
            "explanation": "Material changed and severe historical incidents exist for this part number." if material_changes and severe_incidents else f"{len(material_changes)} material change(s) require engineering review." if material_changes else "No material substitutions detected.",
            "evidence": {"material_changes": material_changes, "incidents": incidents[:5]},
            "recommended_actions": ["Review historical incidents and corrective actions.", "Require material/supplier signoff."] if material_changes else [],
        },
        {
            "rule_key": "FASTENER_OR_INTERFACE_CHANGED",
            "triggered": bool(interface_changes),
            "status": "WARN" if interface_changes else "SAFE",
            "confidence": 84 if interface_changes else 70,
            "explanation": f"{len(interface_changes)} interface or fastener change(s) may propagate to assemblies." if interface_changes else "No fastener or interface propagation changes detected.",
            "evidence": interface_changes,
            "recommended_actions": ["Review downstream assembly fit.", "Confirm mating part compatibility."] if interface_changes else [],
        },
        {
            "rule_key": "INSPECTION_METHOD_IMPACTED",
            "triggered": bool(inspection_changes),
            "status": "WARN" if inspection_changes else "SAFE",
            "confidence": 82 if inspection_changes else 70,
            "explanation": f"{len(inspection_changes)} change(s) may alter inspection or validation planning." if inspection_changes else "No inspection-impacting changes detected.",
            "evidence": inspection_changes,
            "recommended_actions": ["Update inspection plan.", "Confirm validation coverage for changed callouts."] if inspection_changes else [],
        },
        {
            "rule_key": "HIGH_RPN_CARRY_FORWARD",
            "triggered": bool(high_rpn_entries),
            "status": "WARN" if high_rpn_entries else "SAFE",
            "confidence": 78 if high_rpn_entries else 70,
            "explanation": f"{len(high_rpn_entries)} linked DFMEA high-RPN entries should be reviewed as evidence." if high_rpn_entries else "No linked high-RPN DFMEA entries found.",
            "evidence": high_rpn_entries[:8],
            "recommended_actions": ["Review linked DFMEA entries affected by drawing changes."] if high_rpn_entries else [],
        },
    ]


def _persist_rule_results(session_id: str, rule_results: list[dict]) -> None:
    for result in rule_results:
        rule_id = _get_rule_id(result["rule_key"])
        row = fetch_one("""
            INSERT INTO engineering_review_rule_results (
                session_id, rule_id, rule_key, status, confidence, triggered,
                explanation, evidence_json, recommended_actions
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            session_id,
            rule_id,
            result["rule_key"],
            result["status"],
            result["confidence"],
            result["triggered"],
            result["explanation"],
            Json(_jsonable(result.get("evidence") or [])),
            Json(result.get("recommended_actions") or []),
        ))

        if result["triggered"]:
            explanation = result.get("explanation")
            if result.get("what_is_wrong") and result.get("why_it_matters"):
                explanation = (
                    f"What: {result['what_is_wrong']}\n"
                    f"Why: {result['why_it_matters']}\n"
                    f"Affected regions: {', '.join(result.get('affected_regions') or [])}"
                )
            finding = fetch_one("""
                INSERT INTO engineering_review_findings (
                    session_id, rule_result_id, finding_type, title, status,
                    explanation, affected_entity_type, affected_entity_id, recommended_action
                )
                VALUES (%s::uuid, %s::uuid, 'DESIGN_RULE_TRIGGER', %s, %s, %s, 'design_revisions', %s, %s)
                RETURNING id
            """, (
                session_id,
                row["id"],
                result["rule_key"].replace("_", " ").title(),
                result["status"],
                explanation,
                result["rule_key"],
                "; ".join(result.get("recommended_actions") or []),
            ))
            execute_query("""
                INSERT INTO engineering_review_evidence (
                    session_id, finding_id, evidence_type, source_type, source_id,
                    title, excerpt, relevance_score, payload_json
                )
                VALUES (%s::uuid, %s::uuid, 'DETERMINISTIC_RULE_EVIDENCE', 'engineering_review_rule_results', %s, %s, %s, 1.0, %s)
            """, (
                session_id,
                finding["id"],
                str(row["id"]),
                f"Evidence for {result['rule_key']}",
                result["explanation"],
                Json(_jsonable(result.get("evidence") or [])),
            ))


def _persist_design_graph(context: dict) -> dict:
    revision = context["revision"]
    artifact_node = _ensure_graph_node(
        "DesignArtifact",
        revision["artifact_id"],
        f"{revision['artifact_number']} - {revision['artifact_title']}",
        {
            "artifact_type": revision.get("artifact_type"),
            "linked_part_number": revision.get("linked_part_number"),
        },
    )
    revision_node = _ensure_graph_node(
        "DesignRevision",
        revision["id"],
        f"{revision['artifact_number']} {revision['revision_code']}",
        {"revision_sequence": revision.get("revision_sequence")},
    )
    _ensure_graph_edge(revision_node, artifact_node, "REVISED_FROM" if context["previous_revision"] else "AFFECTS")

    if context["previous_revision"]:
        previous_node = _ensure_graph_node(
            "DesignRevision",
            context["previous_revision"]["id"],
            f"{revision['artifact_number']} {context['previous_revision']['revision_code']}",
        )
        _ensure_graph_edge(revision_node, previous_node, "REVISED_FROM")

    for change in context["changes"]:
        change_node = _ensure_graph_node(
            "DesignChange",
            change["id"],
            f"{change['change_type']} - {change['feature_key']}",
            {"importance": change.get("importance"), "reason": change.get("deterministic_reason")},
        )
        _ensure_graph_edge(revision_node, change_node, "IMPACTS", confidence=85)

    for entity in context.get("drawing_entities", [])[:40]:
        entity_node = _ensure_graph_node(
            "DrawingEntity",
            entity["id"],
            entity.get("display_name") or entity.get("entity_key"),
            {
                "entity_type": entity.get("entity_type"),
                "drawing_region": entity.get("drawing_region"),
            },
        )
        _ensure_graph_edge(revision_node, entity_node, "CONTAINS_ENTITY", confidence=88)

    for validation in context.get("drawing_validation_results", []):
        finding_node = _ensure_graph_node(
            "DrawingValidationResult",
            validation["id"],
            validation.get("title") or validation.get("rule_key"),
            {
                "rule_key": validation.get("rule_key"),
                "severity": validation.get("severity"),
                "status": validation.get("status"),
                "affected_regions": validation.get("affected_regions") or [],
            },
        )
        _ensure_graph_edge(revision_node, finding_node, "TRIGGERS_FINDING", confidence=94)

    if context["linked_pfmea"]:
        pfmea = context["linked_pfmea"]
        pfmea_node = _ensure_graph_node(
            "PFMEARecord",
            pfmea["id"],
            f"DFMEA #{pfmea['id']} - {pfmea['part_name']}",
            {"part_number": pfmea.get("part_number"), "status": pfmea.get("status")},
        )
        _ensure_graph_edge(revision_node, pfmea_node, "VALIDATED_BY", confidence=75)

    for incident in context["incidents"][:8]:
        incident_node = _ensure_graph_node(
            "HistoricalIncident",
            incident["id"],
            incident.get("failure_mode_name") or f"Incident {incident['id']}",
            {"severity_actual": incident.get("severity_actual"), "part_number": incident.get("part_number")},
        )
        _ensure_graph_edge(revision_node, incident_node, "FAILED_AS", confidence=70)

    return {
        "artifact_node_id": artifact_node,
        "design_revision_node_id": revision_node,
    }


def create_review_session_from_design_revision(design_revision_id: str, created_by: str = "system") -> dict:
    context = _load_design_review_context(design_revision_id)
    revision = context["revision"]

    existing = fetch_one("""
        SELECT id
        FROM engineering_review_sessions
        WHERE design_revision_id = %s::uuid
        ORDER BY created_at DESC
        LIMIT 1
    """, (design_revision_id,))
    if existing:
        return get_review_session(str(existing["id"]))

    graph_refs = _persist_design_graph(context)
    rule_results = _evaluate_design_rules(context)
    risk_status = _max_risk([result["status"] for result in rule_results if result["triggered"]])
    session_number = f"RG-{revision['artifact_number']}-{revision['revision_code']}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    title = f"{revision['artifact_title']} {revision['revision_code']} Drawing Review"
    summary = {
        "source": "drawing_validation",
        "artifact_number": revision.get("artifact_number"),
        "artifact_title": revision.get("artifact_title"),
        "revision_code": revision.get("revision_code"),
        "linked_part_number": revision.get("linked_part_number"),
        "change_count": len(context["changes"]),
        "feature_count": len(context["features"]),
        "drawing_entity_count": len(context.get("drawing_entities", [])),
        "drawing_dimension_count": len(context.get("drawing_dimensions", [])),
        "drawing_annotation_count": len(context.get("drawing_annotations", [])),
        "validation_result_count": len(context.get("drawing_validation_results", [])),
        "reference_comparison": (context.get("reference_pair") or {}).get("comparison_summary_json"),
        "incident_count": len(context["incidents"]),
        "linked_dfmea_entry_count": len(context["dfmea_entries"]),
        "graph": graph_refs,
    }
    summary.update(build_drawing_review_summary(design_revision_id))

    session = fetch_one("""
        INSERT INTO engineering_review_sessions (
            session_number,
            review_type,
            title,
            status,
            risk_status,
            design_revision_id,
            summary_json,
            created_by
        )
        VALUES (%s, 'DRAWING_REVIEW', %s, 'DRAFT', %s, %s::uuid, %s, %s)
        RETURNING id
    """, (
        session_number,
        title,
        risk_status,
        design_revision_id,
        Json(summary),
        created_by,
    ))
    session_id = str(session["id"])

    for validation in context.get("drawing_validation_results", []):
        execute_query("""
            INSERT INTO engineering_review_items (
                session_id, item_type, title, description, source_type, source_id, payload_json, risk_status
            )
            VALUES (%s::uuid, 'DRAWING_FINDING', %s, %s, 'drawing_validation_results', %s, %s, %s)
        """, (
            session_id,
            validation.get("title") or validation.get("rule_key"),
            validation.get("what_is_wrong"),
            str(validation["id"]),
            Json(_jsonable(dict(validation))),
            validation.get("status"),
        ))

    for change in context["changes"]:
        status = "BLOCK" if change["importance"] == "SAFETY_CRITICAL" else "WARN" if change["importance"] == "HIGH" else "SAFE"
        execute_query("""
            INSERT INTO engineering_review_items (
                session_id, item_type, title, description, source_type, source_id, payload_json, risk_status
            )
            VALUES (%s::uuid, 'REVISION_CHANGE', %s, %s, 'design_revision_changes', %s, %s, %s)
        """, (
            session_id,
            f"{change['change_type']} - {change['feature_key']}",
            change.get("deterministic_reason"),
            str(change["id"]),
            Json(_jsonable(dict(change))),
            status,
        ))

    for incident in context["incidents"][:8]:
        execute_query("""
            INSERT INTO engineering_review_evidence (
                session_id, evidence_type, source_type, source_id, title, excerpt, relevance_score, payload_json
            )
            VALUES (%s::uuid, 'HISTORICAL_INCIDENT', 'historical_incidents', %s, %s, %s, 0.82, %s)
        """, (
            session_id,
            str(incident["id"]),
            incident.get("failure_mode_name") or "Historical incident",
            incident.get("description") or incident.get("corrective_action"),
            Json(_jsonable(dict(incident))),
        ))

    _persist_rule_results(session_id, rule_results)
    execute_query("""
        INSERT INTO review_audit_log (session_id, action, actor, new_values, comments)
        VALUES (%s::uuid, 'CREATED', %s, %s, 'Drawing validation review session generated from deterministic rules.')
    """, (session_id, created_by, Json(summary)))

    return get_review_session(session_id)


def list_design_artifacts() -> list[dict]:
    return fetch_all("""
        SELECT
            da.*,
            COUNT(dr.id) as revision_count,
            MAX(dr.revision_sequence) as latest_revision_sequence
        FROM design_artifacts da
        LEFT JOIN design_revisions dr ON dr.artifact_id = da.id
        GROUP BY da.id
        ORDER BY da.updated_at DESC NULLS LAST, da.created_at DESC
    """)


def build_revision_comparison(artifact_id: str) -> dict:
    """Build a cross-revision pivot of dimensions and features for the comparison table."""
    revisions = fetch_all("""
        SELECT id, revision_code, revision_sequence, design_data_json
        FROM design_revisions
        WHERE artifact_id = %s::uuid
        ORDER BY revision_sequence ASC
    """, (artifact_id,))

    if not revisions:
        return {"revisions": [], "dimensions": [], "features": []}

    rev_codes = [r["revision_code"] for r in revisions]

    rev_info = []
    for r in revisions:
        dd = r.get("design_data_json") or {}
        if not isinstance(dd, dict):
            dd = {}
        tb = dd.get("title_block") or {}
        if not isinstance(tb, dict):
            tb = {}
        raw_status = dd.get("approval_status") or tb.get("approval_status") or "DRAFT"
        if raw_status in ("APPROVED_REFERENCE", "RELEASED"):
            badge = "SAFE"
        elif raw_status == "BLOCKED":
            badge = "BLOCK"
        else:
            badge = "WARN"
        rev_info.append({
            "revision_code": r["revision_code"],
            "revision_sequence": r["revision_sequence"],
            "approval_status": raw_status,
            "badge": badge,
        })

    # --- dimension pivot ---
    dim_rows = fetch_all("""
        SELECT
            dd.dimension_key,
            dd.display_name,
            dd.nominal_value,
            dd.unit,
            dd.is_critical,
            dd.drawing_region,
            dd.tolerance_json,
            dr.revision_code
        FROM drawing_dimensions dd
        JOIN design_revisions dr ON dd.design_revision_id = dr.id
        WHERE dr.artifact_id = %s::uuid
        ORDER BY dr.revision_sequence, dd.is_critical DESC, dd.dimension_key
    """, (artifact_id,))

    dim_map: dict[str, dict] = {}
    for row in dim_rows:
        key = row["dimension_key"]
        if key not in dim_map:
            dim_map[key] = {
                "dimension_key": key,
                "display_name": row["display_name"],
                "unit": row["unit"] or "mm",
                "is_critical": bool(row["is_critical"]),
                "drawing_region": row["drawing_region"] or "—",
                "per_rev": {},
            }
        nominal = row["nominal_value"]
        try:
            nominal = float(nominal) if nominal is not None else None
        except (TypeError, ValueError):
            nominal = None
        tol = row["tolerance_json"]
        if not isinstance(tol, dict):
            tol = {}
        dim_map[key]["per_rev"][row["revision_code"]] = {
            "nominal": nominal,
            "tol_plus": tol.get("plus"),
            "tol_minus": tol.get("minus"),
        }

    ref_code = rev_codes[-1]

    dimensions = list(dim_map.values())
    for dim in dimensions:
        nominals = [v["nominal"] for v in dim["per_rev"].values() if v["nominal"] is not None]
        dim["has_change"] = len({round(v, 4) for v in nominals}) > 1 if nominals else False

        ref_nominal = dim["per_rev"].get(ref_code, {}).get("nominal")
        ordered = []
        for rc in rev_codes:
            info = dim["per_rev"].get(rc)
            if info is None:
                ordered.append(None)
            else:
                cur = info["nominal"]
                if ref_nominal is not None and cur is not None:
                    diff = abs(float(cur) - float(ref_nominal)) > 0.0001
                elif ref_nominal is None and cur is not None:
                    diff = True
                else:
                    diff = False
                ordered.append({
                    "nominal": cur,
                    "nominal_str": f"{cur:g}" if cur is not None else "—",
                    "tol_plus": info.get("tol_plus"),
                    "tol_minus": info.get("tol_minus"),
                    "diff_from_ref": diff,
                    "is_ref": rc == ref_code,
                })
        dim["rev_vals"] = ordered

    dimensions.sort(key=lambda d: (not d["is_critical"], d["dimension_key"]))

    # --- feature entity pivot ---
    entity_rows = fetch_all("""
        SELECT
            dfe.entity_key,
            dfe.display_name,
            dfe.entity_type,
            dfe.drawing_region,
            dr.revision_code
        FROM drawing_feature_entities dfe
        JOIN design_revisions dr ON dfe.design_revision_id = dr.id
        WHERE dr.artifact_id = %s::uuid
          AND dfe.entity_type IN ('MOUNTING_HOLE', 'CUTOUT', 'FLANGE', 'BEND')
        ORDER BY dfe.entity_type, dfe.entity_key
    """, (artifact_id,))

    entity_map: dict[str, dict] = {}
    for row in entity_rows:
        key = row["entity_key"]
        if key not in entity_map:
            entity_map[key] = {
                "entity_key": key,
                "display_name": row["display_name"],
                "entity_type": row["entity_type"],
                "drawing_region": row["drawing_region"] or "—",
                "present_set": set(),
            }
        entity_map[key]["present_set"].add(row["revision_code"])

    ref_keys = {k for k, v in entity_map.items() if ref_code in v["present_set"]}

    features = []
    for feat in entity_map.values():
        present = feat["present_set"]
        in_ref = feat["entity_key"] in ref_keys
        features.append({
            "entity_key": feat["entity_key"],
            "display_name": feat["display_name"],
            "entity_type": feat["entity_type"],
            "drawing_region": feat["drawing_region"],
            "rev_presence": [
                {
                    "present": rc in present,
                    "is_ref": rc == ref_code,
                    "warn": (rc in present) and not in_ref,
                }
                for rc in rev_codes
            ],
        })
    features.sort(key=lambda f: (f["entity_type"], f["entity_key"]))

    return {"revisions": rev_info, "dimensions": dimensions, "features": features}


def get_design_artifact_detail(artifact_id: str) -> dict:
    artifact = fetch_one("SELECT * FROM design_artifacts WHERE id = %s::uuid", (artifact_id,))
    if not artifact:
        raise ValueError("Design artifact not found")
    revisions = fetch_all("""
        SELECT
            dr.*,
            COUNT(drc.id) as change_count,
            MAX(CASE WHEN drc.importance = 'SAFETY_CRITICAL' THEN 1 ELSE 0 END) as has_safety_change
        FROM design_revisions dr
        LEFT JOIN design_revision_changes drc ON drc.design_revision_id = dr.id
        WHERE dr.artifact_id = %s::uuid
        GROUP BY dr.id
        ORDER BY dr.revision_sequence DESC
    """, (artifact_id,))
    for revision in revisions:
        revision["asset_url"] = _drawing_asset_url(revision.get("source_filename"))
        revision["prt_asset_url"] = _drawing_asset_url((revision.get("design_data_json") or {}).get("prt_filename"))
    comparison = build_revision_comparison(artifact_id)
    return {"artifact": artifact, "revisions": revisions, "comparison": comparison}


def _drawing_asset_url(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    clean_name = Path(filename).name
    if (DRAWING_ASSET_DIR / clean_name).exists():
        return f"/static/drawings/{clean_name}"
    return None


def seed_mock_bracket_review_data() -> dict:
    """Create/update the bracket drawing demo variants and return the artifact detail."""
    # Ensure new engineering rules exist (idempotent — safe to run on existing DBs)
    for rule_key, display_name, description, severity, rule_group in [
        ("FEATURE_OUTSIDE_REFERENCE_ENVELOPE", "Feature outside reference envelope",
         "Blocks release when a feature in this revision is absent from the approved reference drawing; requires ECN.",
         "BLOCK", "ASSEMBLY_INTERFACE"),
        ("BEND_RADIUS_BELOW_MINIMUM", "Bend radius below 1×t minimum",
         "Blocks release when the specified inside bend radius is below the 1×material-thickness minimum for CRCA IS 513.",
         "BLOCK", "MANUFACTURING_CONSTRAINT"),
        ("MIXED_FASTENER_SIZES", "Mixed fastener/hole sizes",
         "Flags asymmetric hole diameters that imply different fastener standards; requires BOM confirmation.",
         "WARN", "ASSEMBLY_INTERFACE"),
    ]:
        execute_query(
            """
            INSERT INTO engineering_review_rules (rule_key, display_name, description, severity, rule_group)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (rule_key) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                description  = EXCLUDED.description,
                severity     = EXCLUDED.severity,
                rule_group   = EXCLUDED.rule_group
            """,
            (rule_key, display_name, description, severity, rule_group),
        )

    variants = get_mock_bracket_variants()
    artifact = create_design_artifact(variants[0]["artifact"])

    created_revisions = []
    for variant in variants:
        revision_data = variant["revision"]
        existing = fetch_one("""
            SELECT id
            FROM design_revisions
            WHERE artifact_id = %s::uuid AND revision_code = %s
        """, (artifact["id"], revision_data["revision_code"]))
        if existing:
            execute_query("DELETE FROM design_revisions WHERE id = %s::uuid", (existing["id"],))
        revision = create_design_revision(str(artifact["id"]), revision_data)
        created_revisions.append(revision)

    return {
        "artifact": artifact,
        "revision_count": len(created_revisions),
        "redirect_url": f"/design-artifacts/{artifact['id']}",
    }
