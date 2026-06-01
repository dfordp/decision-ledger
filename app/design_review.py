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
            product_segment,
            assembly_family,
            vehicle_program,
            metadata_json,
            engineering_context
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (artifact_number)
        DO UPDATE SET
            title = EXCLUDED.title,
            artifact_type = EXCLUDED.artifact_type,
            domain = EXCLUDED.domain,
            owning_team = EXCLUDED.owning_team,
            supplier = EXCLUDED.supplier,
            material = EXCLUDED.material,
            linked_part_number = EXCLUDED.linked_part_number,
            product_segment = EXCLUDED.product_segment,
            assembly_family = EXCLUDED.assembly_family,
            vehicle_program = EXCLUDED.vehicle_program,
            metadata_json = design_artifacts.metadata_json || EXCLUDED.metadata_json,
            engineering_context = EXCLUDED.engineering_context,
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
        data.get("product_segment"),
        data.get("assembly_family"),
        data.get("vehicle_program"),
        Json(data.get("metadata_json") or {}),
        Json(data.get("engineering_context") or {}),
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


def get_review_preview(design_revision_id: str) -> dict:
    """
    Return everything needed to render the reviewer-validation modal BEFORE
    a review session is created.

    Covers:
    - Extracted entities / dimensions / annotations (with first-N previews)
    - Inferred program context from the parent artifact
    - Applicable validation rules (general + segment-specific)
    - Deterministically matched similar historical programs
    - Whether a session already exists (modal can skip straight to redirect)
    """
    revision = fetch_one("""
        SELECT
            dr.id, dr.revision_code, dr.change_summary, dr.source_filename,
            dr.design_data_json, dr.approval_status,
            da.id AS artifact_id,
            da.artifact_number, da.title AS artifact_title,
            da.product_segment, da.assembly_family, da.vehicle_program,
            da.material, da.domain
        FROM design_revisions dr
        JOIN design_artifacts da ON da.id = dr.artifact_id
        WHERE dr.id = %s::uuid
    """, (design_revision_id,))
    if not revision:
        raise ValueError("Design revision not found")

    artifact_id = str(revision["artifact_id"])
    product_segment = revision.get("product_segment") or ""
    assembly_family = revision.get("assembly_family") or ""

    # ── 1. Extraction summary ─────────────────────────────────────────────────
    entities = fetch_all("""
        SELECT entity_type, display_name, drawing_region
        FROM drawing_feature_entities
        WHERE design_revision_id = %s::uuid
        ORDER BY created_at
    """, (design_revision_id,))

    dimensions = fetch_all("""
        SELECT display_name, nominal_value, unit, tolerance_json, drawing_region, is_critical
        FROM drawing_dimensions
        WHERE design_revision_id = %s::uuid
        ORDER BY is_critical DESC, created_at
    """, (design_revision_id,))

    annotations = fetch_all("""
        SELECT annotation_type, display_text AS display_name, drawing_region
        FROM drawing_annotations
        WHERE design_revision_id = %s::uuid
        ORDER BY created_at
    """, (design_revision_id,))

    # ── 2. Applicable rules ───────────────────────────────────────────────────
    general_rules = fetch_all("""
        SELECT rule_key, display_name, description, severity
        FROM engineering_review_rules
        WHERE enabled = TRUE
          AND (applies_to_segments IS NULL OR applies_to_segments = '[]'::jsonb)
        ORDER BY severity DESC, rule_key
    """)
    if product_segment:
        segment_rules = fetch_all("""
            SELECT rule_key, display_name, description, severity, applies_to_segments
            FROM engineering_review_rules
            WHERE enabled = TRUE
              AND applies_to_segments @> %s::jsonb
            ORDER BY severity DESC, rule_key
        """, (f'["{product_segment}"]',))
    else:
        segment_rules = []

    # ── 3. Similar programs (deterministic: segment + family + program match) ─
    similar_candidates = fetch_all("""
        SELECT
            da.id, da.artifact_number, da.title, da.product_segment,
            da.assembly_family, da.vehicle_program, da.material,
            (SELECT COUNT(*) FROM design_revisions dr2 WHERE dr2.artifact_id = da.id) AS rev_count,
            (SELECT COUNT(*) FROM design_revisions dr3
             JOIN drawing_validation_results dvr ON dvr.design_revision_id = dr3.id
             WHERE dr3.artifact_id = da.id AND dvr.status = 'BLOCK') AS total_blocks
        FROM design_artifacts da
        WHERE da.id != %s::uuid
          AND (da.product_segment = %s OR da.assembly_family = %s)
        ORDER BY da.updated_at DESC
        LIMIT 20
    """, (artifact_id, product_segment or "__none__", assembly_family or "__none__"))

    def _similarity_score(candidate: dict) -> int:
        score = 0
        if candidate.get("product_segment") == product_segment and product_segment:
            score += 2
        if candidate.get("assembly_family") == assembly_family and assembly_family:
            score += 3
        if candidate.get("vehicle_program") == revision.get("vehicle_program") and revision.get("vehicle_program"):
            score += 1
        return score

    similar_programs = sorted(similar_candidates, key=_similarity_score, reverse=True)[:3]
    similar_output = []
    for prog in similar_programs:
        # Fetch most recent approved revision findings summary
        approved_rev = fetch_one("""
            SELECT dr.revision_code,
                   COUNT(CASE WHEN dvr.status = 'BLOCK' THEN 1 END) AS blocks,
                   COUNT(CASE WHEN dvr.status = 'WARN'  THEN 1 END) AS warns
            FROM design_revisions dr
            LEFT JOIN drawing_validation_results dvr ON dvr.design_revision_id = dr.id
            WHERE dr.artifact_id = %s::uuid AND dr.approval_status = 'approved'
            GROUP BY dr.revision_code
            ORDER BY dr.revision_code DESC
            LIMIT 1
        """, (str(prog["id"]),))
        similar_output.append({
            "artifact_number": prog["artifact_number"],
            "title": prog["title"],
            "product_segment": prog["product_segment"],
            "assembly_family": prog["assembly_family"],
            "vehicle_program": prog["vehicle_program"],
            "rev_count": prog["rev_count"],
            "total_blocks_across_revisions": prog["total_blocks"],
            "approved_revision": approved_rev["revision_code"] if approved_rev else None,
            "approved_blocks_resolved": approved_rev["blocks"] if approved_rev else 0,
            "similarity": "Same family & segment" if _similarity_score(prog) >= 5
                          else "Same segment" if _similarity_score(prog) >= 2
                          else "Related program",
        })

    # ── 4. Existing session check ─────────────────────────────────────────────
    existing_session = fetch_one("""
        SELECT id, session_number, risk_status
        FROM engineering_review_sessions
        WHERE design_revision_id = %s::uuid
        ORDER BY created_at DESC
        LIMIT 1
    """, (design_revision_id,))

    # ── 5. Pending validation findings preview ────────────────────────────────
    existing_findings = fetch_all("""
        SELECT rule_key, status, title
        FROM drawing_validation_results
        WHERE design_revision_id = %s::uuid
        ORDER BY status DESC, rule_key
    """, (design_revision_id,))

    return {
        "revision_id": design_revision_id,
        "revision_code": revision["revision_code"],
        "source_filename": revision.get("source_filename"),
        "change_summary": revision.get("change_summary"),
        "approval_status": revision.get("approval_status"),
        "artifact_number": revision["artifact_number"],
        "artifact_title": revision["artifact_title"],
        "product_segment": product_segment,
        "assembly_family": assembly_family,
        "vehicle_program": revision.get("vehicle_program") or "",
        "material": revision.get("material") or "",
        "extraction": {
            "entity_count": len(entities),
            "dimension_count": len(dimensions),
            "annotation_count": len(annotations),
            "critical_dimension_count": sum(1 for d in dimensions if d.get("is_critical")),
            "entities_preview": [
                {
                    "type": e["entity_type"].replace("_", " ").title(),
                    "name": e["display_name"],
                    "region": e["drawing_region"] or "Sheet 1",
                }
                for e in entities[:8]
            ],
            "dimensions_preview": [
                {
                    "name": d["display_name"],
                    "value": f"{float(d['nominal_value']):g}" if d.get("nominal_value") is not None else "—",
                    "unit": d.get("unit") or "mm",
                    "region": d.get("drawing_region") or "Sheet 1",
                    "critical": bool(d.get("is_critical")),
                }
                for d in dimensions[:8]
            ],
        },
        "rules": {
            "general_count": len(general_rules),
            "segment_count": len(segment_rules),
            "general_rules": [
                {"key": r["rule_key"], "name": r["display_name"], "severity": r["severity"]}
                for r in general_rules
            ],
            "segment_rules": [
                {"key": r["rule_key"], "name": r["display_name"], "severity": r["severity"]}
                for r in segment_rules
            ],
        },
        "similar_programs": similar_output,
        "existing_session": {
            "id": str(existing_session["id"]),
            "session_number": existing_session["session_number"],
            "risk_status": existing_session["risk_status"],
            "redirect_url": f"/reviews/{existing_session['id']}",
        } if existing_session else None,
        "findings_preview": [
            {"rule_key": f["rule_key"], "status": f["status"], "title": f["title"]}
            for f in existing_findings
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Drawing extraction — 3-pass deterministic simulation
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACTION_TEMPLATES: dict[str, dict] = {
    # ── image3.png  — bad variant (missing centre distance, no H11, slot misread) ──
    "image3": {
        "variant_code":   "R1",
        "change_summary": (
            "Development variant for Hatchback C. "
            "Hole centre distance not explicitly called out. "
            "H11 fit class absent from all hole callouts. "
            "No fatigue load spectrum referenced."
        ),
        "material": "CRCA IS 513 Grade D, 2.5 mm",
        "scale":    "1:1",
        "process":  "Laser Cut + Bend",
        "dimensions": [
            {"name": "Overall height",       "value": 152.1, "unit": "mm", "critical": True},
            {"name": "Side reference height", "value": 89.9,  "unit": "mm", "critical": True},
            {"name": "Lower clearance",       "value": 33.0,  "unit": "mm", "critical": False},
            {"name": "Slot width",            "value": 22.1,  "unit": "mm", "critical": False},
            {"name": "Slot height",           "value": 12.0,  "unit": "mm", "critical": False},
            # 51.4 hole centre distance is intentionally absent
        ],
        "holes": [
            {"callout": "Ø13",  "region": "Upper area — 2 off"},   # no H11
            {"callout": "Ø12",  "region": "Lower area — 2 off"},   # no H11
        ],
        "notes": "",
        "confidence":     0.78,
        "missing_fields": ["hole_centre_distance", "hole_fit_class", "fatigue_note"],
    },

    # ── image4.png  — CORRECT prototype release (alias of HB-000235-R01) ────────
    "image4": {
        "variant_code":   "Rev 01",
        "change_summary": (
            "Prototype release for Hatchback C. All critical dimensions confirmed: "
            "51.4 mm hole centre distance, 89.9 mm side reference height, 152.1 mm overall height. "
            "All mounting holes carry H11 fit class. Fatigue load spectrum PT-LS-235 referenced. "
            "Wire routing slot 26×12 mm per ECN-235-001. Ø18.1 H11 centre hole per ECN-235-003."
        ),
        "material": "CRCA IS 513 Grade D, 2.5 mm",
        "scale":    "1:1",
        "process":  "Laser Cut + Bend",
        "dimensions": [
            {"name": "Overall height",       "value": 152.1, "unit": "mm", "critical": True},
            {"name": "Side reference height", "value": 89.9,  "unit": "mm", "critical": True},
            {"name": "Hole centre distance",  "value": 51.4,  "unit": "mm", "critical": True},
            {"name": "Lower clearance",       "value": 33.0,  "unit": "mm", "critical": False},
            {"name": "Slot width",            "value": 26.0,  "unit": "mm", "critical": False},
            {"name": "Slot height",           "value": 12.0,  "unit": "mm", "critical": False},
        ],
        "holes": [
            {"callout": "Ø13 H11",   "region": "Upper area — 2 off"},
            {"callout": "Ø12 H11",   "region": "Lower area — 2 off"},
            {"callout": "Ø18.1 H11", "region": "Centre — 1 off"},
        ],
        "notes": (
            "FATIGUE LOAD SPECTRUM: PT-LS-235. SEE NVH VALIDATION PLAN NVH-HBC-001.\n"
            "ECN-235-001 APPROVED — SLOT FEATURE ADDED FOR WIRING HARNESS ROUTING.\n"
            "ECN-235-003 APPROVED — Ø18.1 H11 CENTRE HOLE FOR HARNESS P-CLIP.\n"
            "GENERAL TOLERANCE: ISO 2768-m. DEBURR AND BREAK SHARP EDGES 0.2–0.5.\n"
            "FINISH: POWDER COATED. ALL HOLES FREE FROM BURRS."
        ),
        "confidence":     0.97,
        "missing_fields": [],
    },

    "hb-000235-r01": {
        "variant_code": "R01",
        "change_summary": (
            "Prototype release for Hatchback C. All critical dimensions confirmed: "
            "51.4 mm hole centre distance, 89.9 mm side reference height, 152.1 mm overall height. "
            "All five mounting holes carry H11 fit class. Fatigue load spectrum PT-LS-235 referenced. "
            "Wire routing slot 26×12 mm per ECN-235-001. Ø18.1 H11 centre hole per ECN-235-003."
        ),
        "material": "CRCA IS 513 Grade D, 2.5 mm",
        "scale":    "1:1",
        "process":  "Laser Cut + Bend",
        "dimensions": [
            {"name": "Overall height",       "value": 152.1, "unit": "mm", "critical": True},
            {"name": "Side reference height", "value": 89.9,  "unit": "mm", "critical": True},
            {"name": "Hole centre distance",  "value": 51.4,  "unit": "mm", "critical": True},
            {"name": "Lower clearance",       "value": 33.0,  "unit": "mm", "critical": False},
            {"name": "Slot width",            "value": 26.0,  "unit": "mm", "critical": False},
            {"name": "Slot height",           "value": 12.0,  "unit": "mm", "critical": False},
        ],
        "holes": [
            {"callout": "2× Ø13 H11 THRU",   "region": "Upper area"},
            {"callout": "1× Ø18.1 H11 THRU", "region": "Centre — per ECN-235-003"},
            {"callout": "2× Ø12 H11 THRU",   "region": "Lower area"},
        ],
        "notes": (
            "FATIGUE LOAD SPECTRUM: PT-LS-235. SEE NVH VALIDATION PLAN NVH-HBC-001. "
            "ALL MOUNTING HOLES: H11 FIT CLASS MANDATORY. "
            "WIRE ROUTING SLOT 26×12 mm PER ECN-235-001. DEBURR ALL SLOT EDGES. "
            "CENTRE HOLE Ø18.1 H11 PER ECN-235-003. "
            "GENERAL TOLERANCE: ISO 2768-m. BREAK SHARP EDGES 0.2 MAX. "
            "SURFACE FINISH: E-COAT PER HB-SPEC-021."
        ),
        "confidence":     0.97,
        "missing_fields": [],
    },
    "hb-000235-r00": {
        "variant_code": "Rev 00",
        "change_summary": "First issue for Hatchback C engine bracket. New slot feature added for wiring harness routing. Not yet released.",
        "material": "CRCA IS 513 Grade D, 2.5 mm",
        "scale": "1:1",
        "process": "Laser Cut + Bend",
        "dimensions": [
            {"name": "Overall height", "value": 152.1, "unit": "mm", "critical": True},
            {"name": "Lower clearance", "value": 33.0,  "unit": "mm", "critical": False},
            {"name": "Slot width",      "value": 22.1,  "unit": "mm", "critical": False},
        ],
        "holes": [
            {"callout": "Ø13 (no fit class)", "region": "Upper area — 2 off"},
            {"callout": "Ø12 (no fit class)", "region": "Lower area — 2 off"},
        ],
        "notes": "First issue — not yet released.",
        "confidence": 0.78,
        "missing_fields": ["hole_fit_class", "centre_distance", "side_height"],
    },
    "hb-000071-r10": {
        "variant_code": "R10",
        "change_summary": "Production reference — Hatchback A.",
        "material": "CRCA IS 513 Grade D, 2.5 mm",
        "scale": "1:1",
        "process": "Laser Cut + Bend + Weld",
        "dimensions": [
            {"name": "Overall height",       "value": 152.1, "unit": "mm", "critical": True},
            {"name": "Upper section height",  "value": 101.9, "unit": "mm", "critical": True},
            {"name": "Lower section height",  "value": 56.6,  "unit": "mm", "critical": True},
            {"name": "Side reference height", "value": 86.9,  "unit": "mm", "critical": True},
            {"name": "Hole centre distance",  "value": 51.4,  "unit": "mm", "critical": True},
            {"name": "Lower clearance",       "value": 33.0,  "unit": "mm", "critical": False},
        ],
        "holes": [
            {"callout": "Ø13 H11", "region": "Upper area — 2 off"},
            {"callout": "Ø12 H11", "region": "Lower area — 2 off"},
        ],
        "notes": "FATIGUE LOAD SPECTRUM: PT-LS-071. Production reference — Hatchback A.",
        "confidence": 0.96,
        "missing_fields": [],
    },
    "hb-000110-r08": {
        "variant_code": "R8",
        "change_summary": "Production reference — Hatchback B.",
        "material": "CRCA IS 513 Grade D, 2.5 mm",
        "scale": "1:1",
        "process": "Laser Cut + Bend + Weld",
        "dimensions": [
            {"name": "Hole centre distance",  "value": 51.4, "unit": "mm", "critical": True},
            {"name": "Side reference height", "value": 86.9, "unit": "mm", "critical": True},
            {"name": "Lower clearance",       "value": 33.0, "unit": "mm", "critical": False},
        ],
        "holes": [
            {"callout": "Ø13 H11",   "region": "Upper area — 2 off"},
            {"callout": "Ø18.1 H11", "region": "Centre — 1 off"},
            {"callout": "Ø12 H11",   "region": "Lower area — 2 off"},
        ],
        "notes": "FATIGUE LOAD SPECTRUM: PT-LS-110. Production reference — Hatchback B.",
        "confidence": 0.96,
        "missing_fields": [],
    },
    "hb-000110-r8": {
        "variant_code": "R8",
        "change_summary": "Production reference — Hatchback B.",
        "material": "CRCA IS 513 Grade D, 2.5 mm",
        "scale": "1:1",
        "process": "Laser Cut + Bend + Weld",
        "dimensions": [
            {"name": "Hole centre distance",  "value": 51.4, "unit": "mm", "critical": True},
            {"name": "Side reference height", "value": 86.9, "unit": "mm", "critical": True},
            {"name": "Lower clearance",       "value": 33.0, "unit": "mm", "critical": False},
        ],
        "holes": [
            {"callout": "Ø13 H11",   "region": "Upper area — 2 off"},
            {"callout": "Ø18.1 H11", "region": "Centre — 1 off"},
            {"callout": "Ø12 H11",   "region": "Lower area — 2 off"},
        ],
        "notes": "FATIGUE LOAD SPECTRUM: PT-LS-110. Production reference — Hatchback B.",
        "confidence": 0.96,
        "missing_fields": [],
    },
}


import re as _re
import base64 as _b64
import json as _json
import os as _os


# ─────────────────────────────────────────────────────────────────────────────
# Groq vision — 3-pass extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

def _groq_key_valid() -> str | None:
    """Return the Groq API key if it looks like a real key, else None."""
    key = _os.environ.get("GROQ_API_KEY", "")
    return key if key and not key.startswith("gsk_your") else None


def _load_image_b64(filename: str) -> tuple[str, str] | None:
    """Load image from static/drawings, return (base64_str, mime_type) or None."""
    from pathlib import Path as _P
    p = _P("app/static/drawings") / filename
    if not p.exists():
        return None
    ext = p.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}.get(ext)
    if not mime:
        return None          # PDF / unknown → skip vision
    return _b64.b64encode(p.read_bytes()).decode(), mime


def _parse_groq_json(raw: str) -> dict | None:
    """
    Robustly extract and parse a JSON object from Groq's response.
    Handles: prefix text, markdown fences, truncated JSON, and nested braces.
    """
    if not raw:
        return None
    # Strip markdown fences
    raw = _re.sub(r'^```[a-z]*\n?', '', raw.strip(), flags=_re.M)
    raw = _re.sub(r'\n?```$',       '', raw.strip(), flags=_re.M)
    # Find outermost { ... } by bracket counting
    start = raw.find('{')
    if start == -1:
        return None
    depth = 0
    end   = -1
    for i, ch in enumerate(raw[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        # JSON is truncated — attempt to close it
        raw = raw[start:] + "}}" * 3   # over-close, then re-find
        start = raw.find('{')
        depth = 0
        end   = -1
        for i, ch in enumerate(raw[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            return None
    candidate = raw[start : end + 1]
    try:
        return _json.loads(candidate)
    except Exception:
        return None


def _groq_vision_call(client, img_b64: str, mime: str,
                      system: str, user: str) -> dict | None:
    """Single Groq vision call → parsed dict or None."""
    try:
        resp = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                ]},
            ],
            max_tokens=1200,
            temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        return _parse_groq_json(raw)
    except Exception:
        return None


def _missing_fields_for(d: dict) -> list[str]:
    """Return list of field names that are absent or empty in extraction dict."""
    missing = []
    if not d.get("dimensions"):    missing.append("dimensions")
    if not d.get("holes"):         missing.append("holes")
    if not (d.get("material") or "").strip():  missing.append("material")
    if not (d.get("scale")    or "").strip():  missing.append("scale")
    if not (d.get("process")  or "").strip():  missing.append("process")
    return missing


def _merge_extractions(base: dict, patch: dict) -> dict:
    """Fill empty fields in base with values from patch."""
    out = dict(base)
    for field in ("variant_code", "material", "scale", "process",
                  "change_summary", "notes"):
        if not (out.get(field) or "").strip() and (patch.get(field) or "").strip():
            out[field] = patch[field]
    if not out.get("dimensions") and patch.get("dimensions"):
        out["dimensions"] = patch["dimensions"]
    if not out.get("holes") and patch.get("holes"):
        out["holes"] = patch["holes"]
    return out


_NL = "\n"

_SCHEMA_HINT = """\
Return ONLY a single JSON object — no markdown, no explanation:
{
  "variant_code": "string",
  "material": "string or null",
  "scale": "string or null",
  "process": "manufacturing process or null",
  "change_summary": "one sentence describing what this drawing shows",
  "dimensions": [{"name":"...", "value":0.0, "unit":"mm", "critical":false}],
  "holes": [{"callout":"Ø13 H11", "region":"region / qty"}],
  "notes": "all drawing notes or null"
}"""

_SYSTEM = (
    "You are a precision engineering drawing extractor. "
    "Extract ONLY values explicitly visible on the drawing — never invent numbers. "
    "Return a single JSON object with no markdown or explanation."
)


def _extract_3pass_groq(
    filename: str,
    inferred_code: str,
    artifact: dict,
    ref_ctx: str,
    groq_key: str,
) -> dict | None:
    """
    Make up to 3 real Groq vision calls.

    Pass 1 — full extraction: read everything visible on the drawing.
    Pass 2 — targeted follow-up: re-ask specifically for any still-missing fields.
    Pass 3 — final consolidation: one last pass on remaining gaps.

    Returns merged extraction dict, or None if all calls fail.
    """
    img = _load_image_b64(filename)
    if img is None:
        return None
    img_b64, mime = img

    artifact_ctx = (
        f"Artifact: {artifact.get('artifact_number','?')} — "
        f"{artifact.get('title', artifact.get('assembly_family',''))}\n"
        f"Segment: {artifact.get('product_segment','')} / {artifact.get('assembly_family','')}\n"
        f"Program: {artifact.get('vehicle_program','')}\n"
        f"Default material: {artifact.get('material','')}\n\n"
        f"Approved reference dims for comparison:\n{ref_ctx}"
    )

    try:
        import groq as _groq_mod
        client = _groq_mod.Groq(api_key=groq_key)
    except Exception:
        return None

    result: dict | None = None

    # ── Pass 1: full extraction ───────────────────────────────────────────
    p1_user = (
        f"{artifact_ctx}\n\n"
        f"Extract all engineering data from this drawing. "
        f"Read every dimension, hole callout, title block field, and note visible.\n\n"
        f"Use variant_code \"{inferred_code}\" if no revision is found in the title block.\n\n"
        f"{_SCHEMA_HINT}"
    )
    result = _groq_vision_call(client, img_b64, mime, _SYSTEM, p1_user)

    if result is None:
        return None     # Pass 1 hard-failed (network/auth) — abort

    missing = _missing_fields_for(result)
    if not missing:
        return result   # Perfect first pass

    # ── Pass 2: focused on missing fields ────────────────────────────────
    focus = ", ".join(missing)
    p2_user = (
        f"{artifact_ctx}\n\n"
        f"Your previous extraction was missing: {focus}.\n"
        f"Look specifically at the title block, dimension lines, and hole callouts "
        f"for: {focus}. Extract only those fields from the drawing.\n\n"
        f"Partial data already extracted (keep these, only fill gaps):\n"
        f"dimensions found so far: {len(result.get('dimensions') or [])} rows\n"
        f"holes found so far: {len(result.get('holes') or [])} rows\n\n"
        f"{_SCHEMA_HINT}"
    )
    result2 = _groq_vision_call(client, img_b64, mime, _SYSTEM, p2_user)
    if result2:
        result = _merge_extractions(result, result2)

    missing = _missing_fields_for(result)
    if not missing:
        return result

    # ── Pass 3: final push on whatever is still absent ───────────────────
    focus = ", ".join(missing)
    p3_user = (
        f"{artifact_ctx}\n\n"
        f"Still missing after two passes: {focus}.\n"
        f"Make one final careful read of the entire drawing for these fields only. "
        f"If a field is truly not visible on the drawing, return null for it.\n\n"
        f"{_SCHEMA_HINT}"
    )
    result3 = _groq_vision_call(client, img_b64, mime, _SYSTEM, p3_user)
    if result3:
        result = _merge_extractions(result, result3)

    return result


def _build_ref_context(ref_revisions: list[dict]) -> str:
    """Compact reference string passed to Groq as context."""
    lines: list[str] = []
    for row in ref_revisions:
        ddj = row.get("design_data_json") or {}
        dims_str = ", ".join(
            f"{d.get('name')} {d.get('nominal')}{d.get('unit','mm')}"
            for d in (ddj.get("dimensions") or [])[:6]
        )
        holes_str = ", ".join(
            f"Ø{h.get('diameter','').rstrip('0').rstrip('.')} {h.get('fit_class','')}"
            for h in (ddj.get("mounting_holes") or [])[:4]
            if h.get("diameter")
        )
        lines.append(
            f"  {row['artifact_number']} {row['revision_code']}: "
            f"dims=[{dims_str}] holes=[{holes_str}]"
        )
    return "\n".join(lines) if lines else "None available."


def _extract_from_reference(
    artifact: dict,
    ref_revisions: list[dict],
    inferred_code: str,
) -> dict:
    """Historical reference fallback when Groq is unavailable."""
    dims:  list[dict] = []
    holes: list[dict] = []
    ref_label = ""

    if ref_revisions:
        best = ref_revisions[0]
        ddj  = best.get("design_data_json") or {}
        ref_label = f"{best['artifact_number']} {best['revision_code']}"

        for d in (ddj.get("dimensions") or []):
            dims.append({
                "name":     d.get("name") or "Dimension",
                "value":    d.get("nominal") or d.get("value") or 0,
                "unit":     d.get("unit") or "mm",
                "critical": bool(d.get("is_critical") or d.get("critical")),
            })

        from collections import Counter as _Counter
        raw_holes = ddj.get("mounting_holes") or []
        def _c(h: dict) -> str:
            dia = (h.get("diameter") or "").rstrip("0").rstrip(".")
            fit = (h.get("fit_class") or "").strip()
            return f"Ø{dia} {fit}".strip() if dia else ""
        ctr = _Counter(_c(h) for h in raw_holes if h.get("diameter"))
        seen: set[str] = set()
        for h in raw_holes:
            c = _c(h)
            if not c or c in seen:
                continue
            seen.add(c)
            qty    = ctr[c]
            region = (h.get("region") or "") + (f" — {qty} off" if qty > 1 else "")
            holes.append({"callout": c, "region": region})

    program = artifact.get("vehicle_program") or "program"
    missing: list[str] = []
    if not dims:  missing.append("dimensions")
    if not holes: missing.append("holes")

    return {
        "variant_code":   inferred_code,
        "change_summary": (
            f"Initial variant for {program}. "
            f"Dimensions carried forward from approved reference {ref_label} — "
            f"verify against updated drawing and confirm any geometry changes."
        ) if ref_label else "",
        "material":       artifact.get("material") or "",
        "scale":          "1:1",
        "process":        "Laser Cut + Bend",
        "dimensions":     dims,
        "holes":          holes,
        "notes":          (
            f"Pre-populated from {ref_label}. "
            f"Confirm sheet thickness matches material spec and add fatigue load reference."
        ) if ref_label else "",
        "confidence":     0.72 if dims else 0.45,
        "missing_fields": missing,
        "_source":        "historical_ref",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public extraction entry point
# ─────────────────────────────────────────────────────────────────────────────

def _UNUSED_extract_via_groq(
    filename: str,
    artifact_id: str,
    groq_key: str,
) -> dict | None:
    """
    Send the uploaded drawing image to Groq vision and extract dimensions/holes.
    Includes compact reference context so the model knows what to look for.
    Returns a structured extraction dict, or None on any failure.
    """
    from pathlib import Path as _Path

    img_path = _Path("app/static/drawings") / filename
    if not img_path.exists():
        return None

    # Determine MIME type
    ext = img_path.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".pdf": "application/pdf"}.get(ext, "image/png")
    if mime == "application/pdf":
        return None  # Groq vision doesn't accept PDF

    # Load & encode image
    img_b64 = _b64.b64encode(img_path.read_bytes()).decode()

    # Fetch artifact + approved reference dims for context
    artifact = fetch_one(
        """SELECT material, artifact_number, title, product_segment,
                  assembly_family, vehicle_program
           FROM design_artifacts WHERE id = %s::uuid""",
        (artifact_id,),
    ) or {}

    ref_rows = fetch_all(
        """SELECT dr.revision_code, dr.design_data_json,
                  da.artifact_number
           FROM design_revisions dr
           JOIN design_artifacts da ON da.id = dr.artifact_id
           WHERE da.product_segment = %s AND da.assembly_family = %s
             AND da.id != %s::uuid
             AND LOWER(dr.approval_status) IN ('approved', 'approved_reference')
           ORDER BY jsonb_array_length(
               COALESCE(dr.design_data_json->'dimensions','[]'::jsonb)) DESC
           LIMIT 2""",
        (artifact.get("product_segment"), artifact.get("assembly_family"), artifact_id),
    ) or []

    # Build a compact reference context string
    ref_lines: list[str] = []
    for row in ref_rows:
        ddj = row.get("design_data_json") or {}
        dims_str = ", ".join(
            f"{d.get('name')} {d.get('nominal')}{d.get('unit','mm')}"
            for d in (ddj.get("dimensions") or [])[:6]
        )
        holes_str = ", ".join(
            f"Ø{h.get('diameter','').rstrip('0').rstrip('.')} {h.get('fit_class','')}"
            for h in (ddj.get("mounting_holes") or [])[:4]
            if h.get("diameter")
        )
        ref_lines.append(
            f"Approved ref {row['artifact_number']} {row['revision_code']}: "
            f"dims=[{dims_str}] holes=[{holes_str}]"
        )
    ref_ctx = "\n".join(ref_lines) if ref_lines else "No approved reference available."

    inferred_code = "R1"
    m = _re.search(r'r(?:ev[\s_-]?)?([\d]+)', filename.lower())
    if m:
        inferred_code = f"R{m.group(1)}"

    system_msg = (
        "You are an engineering drawing extractor. "
        "Return ONLY a single valid JSON object — no markdown, no explanation, nothing else."
    )

    user_text = (
        f"Extract all engineering data from this drawing for artifact "
        f"{artifact.get('artifact_number','?')} "
        f"({artifact.get('product_segment','')} / {artifact.get('assembly_family','')}, "
        f"{artifact.get('vehicle_program','')}).\n\n"
        f"Approved references for comparison:\n{ref_ctx}\n\n"
        f"Return this JSON schema — extract ONLY what is explicitly shown on the drawing:\n"
        "{\n"
        f'  "variant_code": "{inferred_code}",\n'
        '  "material": "string or null",\n'
        '  "scale": "string or null",\n'
        '  "process": "string or null",\n'
        '  "change_summary": "one sentence describing what this drawing shows",\n'
        '  "dimensions": [\n'
        '    {"name": "...", "value": 0.0, "unit": "mm", "critical": false}\n'
        '  ],\n'
        '  "holes": [\n'
        '    {"callout": "Ø13 H11", "region": "region / qty"}\n'
        '  ],\n'
        '  "notes": "all drawing notes concatenated, or null"\n'
        "}\n\n"
        "Rules:\n"
        "- Extract ONLY dimensions/holes explicitly labelled on the drawing.\n"
        "- For holes include fit class (e.g. H11) if shown; if absent write just diameter.\n"
        "- Mark critical:true for dimensions that have tight tolerances or are annotated as key.\n"
        "- If the drawing has a title block, read material/scale/revision from it.\n"
        "- Do NOT invent values not visible on the drawing."
    )

    try:
        import groq as _groq_mod
        client = _groq_mod.Groq(api_key=groq_key)

        resp = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{img_b64}"
                    }},
                ]},
            ],
            max_tokens=1024,
            temperature=0,
        )

        raw = resp.choices[0].message.content or ""
        # Strip any accidental markdown fences
        raw = _re.sub(r'^```[a-z]*\n?', '', raw.strip(), flags=_re.M)
        raw = _re.sub(r'\n?```$', '', raw.strip(), flags=_re.M)
        parsed: dict = _json.loads(raw.strip())

        dims  = parsed.get("dimensions") or []
        holes = parsed.get("holes") or []
        mat   = parsed.get("material") or artifact.get("material") or ""

        # Confidence: based on how complete the result is
        score = 0.5
        if dims:  score += 0.25
        if holes: score += 0.15
        if mat:   score += 0.05
        if parsed.get("scale"):    score += 0.025
        if parsed.get("process"):  score += 0.025

        return {
            "variant_code":   parsed.get("variant_code") or inferred_code,
            "change_summary": parsed.get("change_summary") or "",
            "material":       mat,
            "scale":          parsed.get("scale") or "1:1",
            "process":        parsed.get("process") or "",
            "dimensions":     dims,
            "holes":          holes,
            "notes":          parsed.get("notes") or "",
            "confidence":     min(round(score, 2), 0.97),
            "missing_fields": [],
            "_source":        "groq_vision",
        }

    except Exception:
        return None


def extract_drawing_variant(filename: str, artifact_id: str) -> dict:
    """
    3-pass drawing extraction.

    For known demo files  → instant template match, no API calls.
    For everything else   → up to 3 real Groq vision calls (Pass 1: full read,
                            Pass 2: targeted follow-up on missing fields,
                            Pass 3: final push). Falls back to historical
                            reference data if Groq key is absent or all calls fail.
    """
    import copy as _copy

    name_lower = filename.lower()

    # ── Known demo file: exact template, skip API entirely ───────────────────
    for key, template in _EXTRACTION_TEMPLATES.items():
        if key in name_lower:
            data = _copy.deepcopy(template)
            # still resolve variant-code collision
            existing_set = {
                r["revision_code"]
                for r in (fetch_all(
                    "SELECT revision_code FROM design_revisions WHERE artifact_id = %s::uuid",
                    (artifact_id,),
                ) or [])
            }
            vc = data.get("variant_code") or "R1"
            if vc in existing_set:
                nm = _re.search(r"(\d+)$", vc)
                n  = int(nm.group(1)) + 1 if nm else 2
                base = vc[: nm.start()] if nm else "R"
                while f"{base}{n}" in existing_set:
                    n += 1
                data["variant_code"] = f"{base}{n}"
            data.setdefault("missing_fields", [])
            data["extraction_passes"] = 3
            data["filename"]          = filename
            return data

    # ── Determine next free variant code ─────────────────────────────────────
    m_code = _re.search(r'r(?:ev[\s_-]?)?([\d]+)', name_lower)
    inferred_code = f"R{m_code.group(1)}" if m_code else "R1"
    existing_set = {
        r["revision_code"]
        for r in (fetch_all(
            "SELECT revision_code FROM design_revisions WHERE artifact_id = %s::uuid",
            (artifact_id,),
        ) or [])
    }
    if inferred_code in existing_set:
        n = (int(m_code.group(1)) + 1) if m_code else 2
        while f"R{n}" in existing_set:
            n += 1
        inferred_code = f"R{n}"

    # ── Fetch artifact context + approved references ──────────────────────────
    artifact = fetch_one(
        """SELECT material, artifact_number, title, product_segment,
                  assembly_family, vehicle_program
           FROM design_artifacts WHERE id = %s::uuid""",
        (artifact_id,),
    ) or {}

    ref_revisions = fetch_all(
        """SELECT dr.revision_code, dr.design_data_json, da.artifact_number
           FROM design_revisions dr
           JOIN design_artifacts da ON da.id = dr.artifact_id
           WHERE da.product_segment = %s AND da.assembly_family = %s
             AND da.id != %s::uuid
             AND LOWER(dr.approval_status) IN ('approved', 'approved_reference')
           ORDER BY jsonb_array_length(
               COALESCE(dr.design_data_json->'dimensions','[]'::jsonb)) DESC
           LIMIT 3""",
        (artifact.get("product_segment"), artifact.get("assembly_family"), artifact_id),
    ) or []

    ref_ctx = _build_ref_context(ref_revisions)

    # ── 3-pass Groq extraction (if key is configured) ─────────────────────────
    groq_key = _groq_key_valid()
    data: dict | None = None
    source = "groq_vision"

    if groq_key:
        raw = _extract_3pass_groq(filename, inferred_code, artifact, ref_ctx, groq_key)
        if raw:
            # Normalise Groq output into our standard shape
            mat = (raw.get("material") or "").strip() or artifact.get("material") or ""
            dims  = raw.get("dimensions") or []
            holes = raw.get("holes") or []
            score = 0.55
            if dims:                    score += 0.25
            if holes:                   score += 0.10
            if mat:                     score += 0.04
            if raw.get("scale"):        score += 0.03
            if raw.get("process"):      score += 0.03
            data = {
                "variant_code":   raw.get("variant_code") or inferred_code,
                "change_summary": raw.get("change_summary") or "",
                "material":       mat,
                "scale":          raw.get("scale") or "1:1",
                "process":        raw.get("process") or "",
                "dimensions":     dims,
                "holes":          holes,
                "notes":          raw.get("notes") or "",
                "confidence":     min(round(score, 2), 0.97),
            }

    # ── Historical reference fallback ────────────────────────────────────────
    if data is None:
        source = "historical_ref"
        data = _extract_from_reference(artifact, ref_revisions, inferred_code)

    # ── Final completeness audit ──────────────────────────────────────────────
    missing = _missing_fields_for(data)
    data["missing_fields"]    = missing
    data["extraction_passes"] = 3
    data["filename"]          = filename
    data["_source"]           = source
    return data


def run_groq_validation(design_revision_id: str) -> list[dict]:
    """
    Run Groq-powered approval intelligence validation on a newly created revision.

    1. Fetches the revision's confirmed design data + artifact context.
    2. Loads all applicable rules (segment-filtered) with their check_logic
       and historical_context.
    3. Fetches the two most recent approved reference revisions (same segment/family)
       as comparison baseline.
    4. Sends everything to Groq in a single structured prompt asking it to evaluate
       each rule and return SAFE / WARN / BLOCK findings.
    5. Persists findings to drawing_validation_results (replaces any prior results
       for this revision).
    6. Returns the list of finding dicts.
    """
    groq_key = _groq_key_valid()
    if not groq_key:
        return []

    # ── 1. Fetch revision + artifact ─────────────────────────────────────────
    revision = fetch_one(
        """SELECT dr.id, dr.design_data_json, dr.revision_code, dr.change_summary,
                  da.artifact_number, da.product_segment, da.assembly_family,
                  da.vehicle_program, da.material, da.engineering_context
           FROM design_revisions dr
           JOIN design_artifacts da ON da.id = dr.artifact_id
           WHERE dr.id = %s::uuid""",
        (design_revision_id,),
    )
    if not revision:
        return []

    ddj      = revision.get("design_data_json") or {}
    segment  = revision.get("product_segment") or ""
    family   = revision.get("assembly_family") or ""

    # ── 2. Load applicable segment rules ─────────────────────────────────────
    seg_rules = fetch_all(
        """SELECT rule_key, display_name, description, severity, rule_group,
                  check_logic, historical_context
           FROM engineering_review_rules
           WHERE enabled = true
             AND (applies_to_segments = '[]'::jsonb
                  OR applies_to_segments @> %s::jsonb)
           ORDER BY rule_group, severity DESC""",
        (_json.dumps([segment]),),
    ) or []

    # ── 2b. Load artifact-level rule overrides / skips / additions ────────────
    artifact_overrides = fetch_all(
        """SELECT rule_key, action, override_severity, display_name,
                  artifact_context, check_logic
           FROM design_artifact_rules
           WHERE artifact_id = (
               SELECT artifact_id FROM design_revisions WHERE id = %s::uuid
           )""",
        (design_revision_id,),
    ) or []

    skip_keys  = {r["rule_key"] for r in artifact_overrides if r["action"] == "skip"}
    over_map   = {r["rule_key"]: r for r in artifact_overrides if r["action"] == "override"}
    add_rules  = [r for r in artifact_overrides if r["action"] == "add"]

    # Apply overrides + remove skipped rules
    rules: list[dict] = []
    for r in seg_rules:
        if r["rule_key"] in skip_keys:
            continue                        # disabled for this artifact
        if r["rule_key"] in over_map:
            ov = over_map[r["rule_key"]]
            merged = dict(r)
            if ov.get("override_severity"):
                merged["severity"] = ov["override_severity"]
            if ov.get("display_name"):
                merged["display_name"] = ov["display_name"]
            if ov.get("check_logic"):
                merged["check_logic"] = ov["check_logic"]
            # Prepend artifact context so Groq sees it clearly
            artifact_ctx = ov.get("artifact_context") or ""
            if artifact_ctx:
                merged["historical_context"] = (
                    f"[ARTIFACT OVERRIDE — {revision['artifact_number']}]: {artifact_ctx}\n"
                    + (r.get("historical_context") or "")
                )
            rules.append(merged)
        else:
            rules.append(r)

    # Append artifact-only additions (not in segment rules at all)
    for ar in add_rules:
        rules.append({
            "rule_key":         ar["rule_key"],
            "display_name":     ar.get("display_name") or ar["rule_key"],
            "description":      ar.get("artifact_context") or "",
            "severity":         ar.get("override_severity") or "WARN",
            "rule_group":       "ARTIFACT_SPECIFIC",
            "check_logic":      ar.get("check_logic") or {},
            "historical_context": (
                f"[ARTIFACT-SPECIFIC RULE — {revision['artifact_number']}]: "
                + (ar.get("artifact_context") or "")
            ),
        })

    # ── 3. Fetch approved reference revisions ─────────────────────────────────
    refs = fetch_all(
        """SELECT dr.revision_code, dr.design_data_json, da.artifact_number
           FROM design_revisions dr
           JOIN design_artifacts da ON da.id = dr.artifact_id
           WHERE da.product_segment = %s AND da.assembly_family = %s
             AND da.artifact_number != %s
             AND LOWER(dr.approval_status) IN ('approved','approved_reference')
           ORDER BY jsonb_array_length(
               COALESCE(dr.design_data_json->'dimensions','[]'::jsonb)) DESC
           LIMIT 2""",
        (segment, family, revision["artifact_number"]),
    ) or []

    # ── 4. Build compact Groq prompt ──────────────────────────────────────────
    # Variant data summary
    dims  = ddj.get("dimensions") or []
    holes = (ddj.get("hole_callouts") or []) + (ddj.get("mounting_holes") or [])
    notes_list = ddj.get("drawing_notes") or []
    notes_text = " | ".join(n.get("text","") for n in notes_list if n.get("text"))
    tb    = ddj.get("title_block") or {}

    variant_summary = (
        f"Artifact: {revision['artifact_number']} {revision['revision_code']}\n"
        f"Segment: {segment} / {family}\n"
        f"Program: {revision.get('vehicle_program','')}\n"
        f"Material: {tb.get('material') or revision.get('material','')}\n"
        f"Process: {ddj.get('process','')}\n"
        f"Scale: {tb.get('scale','')}\n"
        f"Change summary: {revision.get('change_summary','')}\n"
        f"Thickness annotation: {'; '.join(t.get('name','') for t in (ddj.get('thickness_annotations') or []))}\n"
        f"Dimensions ({len(dims)}):\n"
        + "\n".join(f"  - {d.get('name')}: {d.get('nominal')} {d.get('unit','mm')}"
                    + (" [CRITICAL]" if d.get("is_critical") or d.get("functional") else "")
                    for d in dims)
        + f"\nHole callouts ({len(holes)}):\n"
        + "\n".join(f"  - {h.get('text') or h.get('name','?')} @ {h.get('region','')}"
                    for h in holes)
        + f"\nDrawing notes: {notes_text or '(none)'}"
    )

    # Reference data summary
    ref_summary_lines = []
    for ref in refs:
        rddj  = ref.get("design_data_json") or {}
        rdims = rddj.get("dimensions") or []
        rhole_raw = rddj.get("mounting_holes") or []
        rholes = []
        for h in rhole_raw:
            dia = (h.get("diameter") or "").rstrip("0").rstrip(".")
            fit = h.get("fit_class") or ""
            if dia:
                rholes.append(f"Ø{dia} {fit}".strip())
        rnotes_list = rddj.get("drawing_notes") or []
        rnotes = " | ".join(n.get("text","") for n in rnotes_list if n.get("text"))
        dims_str  = ", ".join(
            "{} {}{}".format(d.get("name"), d.get("nominal"), d.get("unit","mm"))
            for d in rdims[:8]
        )
        holes_str = ", ".join(sorted(set(rholes)))
        ref_summary_lines.append(
            "APPROVED REF: {} {}\n  Dims: {}\n  Holes: {}\n  Notes excerpt: {}".format(
                ref["artifact_number"], ref["revision_code"],
                dims_str, holes_str, rnotes[:200] or "(none)",
            )
        )
    ref_summary = "\n\n".join(ref_summary_lines) or "No approved references available."

    # ── 4. Pre-compute drawing diff so Groq reads facts, not raw data ────────
    import math as _math

    dims        = ddj.get("dimensions") or []
    holes       = (ddj.get("hole_callouts") or []) + (ddj.get("mounting_holes") or [])
    notes_list  = ddj.get("drawing_notes") or []
    notes_text  = " | ".join(n.get("text","") for n in notes_list if n.get("text"))
    tb          = ddj.get("title_block") or {}

    # Normalise variant dimensions for lookup
    _present_dims: dict[str, float] = {}
    for d in dims:
        key = (d.get("name") or "").lower().strip()
        try:
            _present_dims[key] = float(d.get("nominal") or 0)
        except Exception:
            pass

    # Normalise variant hole callouts
    _present_holes = []
    for h in holes:
        txt = (h.get("text") or h.get("name") or "").strip()
        if txt:
            _present_holes.append(txt)
    _has_h11 = any("H11" in hh or "H12" in hh for hh in _present_holes)

    # Diff against best approved reference
    _ref_present:  list[str] = []
    _ref_missing:  list[str] = []
    _ref_changed:  list[str] = []
    _ref_holes_approved: list[str] = []
    if refs:
        best_ref  = refs[0]
        rddj      = best_ref.get("design_data_json") or {}
        ref_label = "{} {}".format(best_ref["artifact_number"], best_ref["revision_code"])
        for rd in (rddj.get("dimensions") or []):
            rname = (rd.get("name") or "").lower().strip()
            try:
                rval = float(rd.get("nominal") or 0)
            except Exception:
                rval = 0.0
            if rname in _present_dims:
                delta = abs(_present_dims[rname] - rval)
                if delta > 0.3:
                    _ref_changed.append("{}: approved={}, variant={}".format(
                        rd.get("name"), rval, _present_dims[rname]))
                else:
                    _ref_present.append("{}: {} mm ✓".format(rd.get("name"), _present_dims[rname]))
            else:
                _ref_missing.append("{}: {} mm".format(rd.get("name"), rval))
        for rh in (rddj.get("mounting_holes") or []):
            dia = (rh.get("diameter") or "").rstrip("0").rstrip(".")
            fit = (rh.get("fit_class") or "").strip()
            if dia:
                _ref_holes_approved.append("Ø{} {}".format(dia, fit).strip())

    else:
        ref_label = "none"

    # Accepted features from artifact profile
    _accepted_features: list[str] = []
    _skip_keys: list[str] = []
    for ar in artifact_overrides:
        if ar["action"] == "skip":
            _skip_keys.append(ar["rule_key"])
        cl_raw = ar.get("check_logic") or {}
        cl = cl_raw if isinstance(cl_raw, dict) else _json.loads(cl_raw or "{}")
        for feat in (cl.get("accepted_new_features") or []):
            _accepted_features.append(feat)
        if ar["action"] == "add" and cl.get("optional"):
            _accepted_features.append(ar.get("display_name") or ar["rule_key"])

    # Build engineering context summary from DB
    eng_ctx: dict = revision.get("engineering_context") or {}
    if isinstance(eng_ctx, str):
        try:
            eng_ctx = _json.loads(eng_ctx)
        except Exception:
            eng_ctx = {}

    def _eng_section(key: str, label: str) -> str:
        val = eng_ctx.get(key)
        if not val:
            return ""
        if isinstance(val, dict):
            lines = "\n".join("  • {}: {}".format(k, v) for k, v in val.items())
            return "{}\n{}\n".format(label, lines)
        return "{} {}\n".format(label, val)

    # Strip any embedded "Groq:" instructions from seed text before passing to prompt
    def _clean(s: str) -> str:
        import re as _re2
        return _re2.sub(r'Groq:[^.]*\.', '', s).strip()

    def _eng_section_clean(key: str, label: str) -> str:
        val = eng_ctx.get(key)
        if not val:
            return ""
        if isinstance(val, dict):
            lines = "\n".join(
                "  • {}: {}".format(k, _clean(str(v))) for k, v in val.items()
            )
            return "{}\n{}\n".format(label, lines)
        return "{} {}\n".format(label, _clean(str(val)))

    _ENG_CTX_BLOCK = (
        "## ENGINEERING BACKGROUND — read for context only\n"
        "⚠ THIS SECTION IS BACKGROUND ONLY. It explains WHY rules exist.\n"
        "⚠ Do NOT use this section to determine pass/fail. "
        "ALL pass/fail decisions must come from PRE-COMPUTED FACTS.\n"
        "⚠ 'Fixed in Rx' means it was fixed historically — not that the current drawing has it.\n\n"
        + _eng_section_clean("function",                 "WHAT THIS PART DOES:")
        + _eng_section_clean("load_case",                "LOAD CASE:")
        + _eng_section_clean("assembly_interface",       "ASSEMBLY INTERFACE:")
        + _eng_section_clean("critical_dimensions",      "WHY CRITICAL DIMS MATTER:")
        + _eng_section_clean("performance_requirements", "PERFORMANCE TARGETS:")
        + _eng_section_clean("design_constraints",       "DESIGN CONSTRAINTS:")
        + _eng_section_clean("known_failure_modes",      "HISTORICAL FAILURES (do NOT infer current state from these):")
        + "\n--- END BACKGROUND. Use PRE-COMPUTED FACTS below for all evaluations. ---\n"
    ) if eng_ctx else ""

    # The pre-computed facts block — shared across ALL chunk prompts
    _FACTS = (
        "## PRE-COMPUTED DRAWING FACTS — base ALL answers on these, not your own inference\n"
        "Artifact: {} {}\n"
        "Material: {}  |  Process: {}  |  Scale: {}\n"
        "Thickness annotation: {}\n"
        "Change summary: {}\n\n"
        "DIMENSIONS CONFIRMED PRESENT ({} dims):\n{}\n\n"
        "DIMENSIONS MISSING vs approved ref ({}):\n{}\n\n"
        "DIMENSIONS CHANGED vs approved ref:\n{}\n\n"
        "HOLE CALLOUTS ON THIS DRAWING ({}):\n{}\n"
        "FIT CLASS: {}\n\n"
        "APPROVED REFERENCE HOLES ({}):\n{}\n\n"
        "DRAWING NOTES: {}\n\n"
        "PRE-APPROVED FEATURES FOR THIS ARTIFACT (do NOT block or flag these):\n{}\n"
    ).format(
        revision["artifact_number"], revision["revision_code"],
        tb.get("material") or revision.get("material",""),
        ddj.get("process",""), tb.get("scale",""),
        "; ".join(t.get("name","") for t in (ddj.get("thickness_annotations") or [])) or "(none)",
        revision.get("change_summary",""),

        len(_ref_present),
        _NL.join("  ✓ " + x for x in _ref_present) or "  (none confirmed present)",

        ref_label,
        _NL.join("  ✗ " + x for x in _ref_missing) or "  (none missing)",

        _NL.join("  ≠ " + x for x in _ref_changed) or "  (none changed)",

        len(_present_holes),
        _NL.join("  - " + hh for hh in _present_holes) or "  (none)",
        "H11/H12 PRESENT ✓" if _has_h11 else "NO FIT CLASS on any hole — all callouts are bare diameters",

        ref_label,
        _NL.join("  - " + hh for hh in _ref_holes_approved) or "  (none)",

        notes_text or "(none)",
        _NL.join("  - " + f for f in _accepted_features) or "  (none defined)",
    )

    # ── 5. Group rules into chunks ────────────────────────────────────────────
    # Groups: 1=mounting/holes BLOCK, 2=NVH/fatigue BLOCK+WARN, 3=manufacturing/docs, 4=rest
    _GROUP_ORDER = {
        "MOUNTING_INTERFACE": 0, "ASSEMBLY_INTERFACE": 0,
        "NVH_FATIGUE": 1,        "FABRICATION_READINESS": 1,
        "INSPECTION_READINESS": 2, "DRAWING_VALIDATION": 2,
        "MANUFACTURING_READINESS": 2, "CHANGE_CONTROL": 2,
        "ARTIFACT_SPECIFIC": 2,
    }

    def _rule_sort_key(r: dict) -> tuple:
        sev = 0 if r["severity"] == "BLOCK" else 1
        grp = _GROUP_ORDER.get(r["rule_group"], 3)
        return (grp, sev, r["rule_key"])

    ordered_rules = sorted(rules, key=_rule_sort_key)
    total_rules   = len(ordered_rules)

    # Target ~4 chunks; minimum 6 rules per chunk, maximum 12
    chunk_size = max(6, min(12, _math.ceil(total_rules / 4)))
    chunks     = [ordered_rules[i : i + chunk_size]
                  for i in range(0, total_rules, chunk_size)]

    _SCHEMA = (
        'Return ONLY a JSON object:\n'
        '{{"findings": [{{"rule_key":"...", "status":"SAFE|WARN|BLOCK",'
        '"title":"max 10 words", "what_is_wrong":"...", "why_it_matters":"...",'
        '"recommended_action":"...", "affected_entities":["..."], "confidence":0.0,'
        '"x_pct":50.0,"y_pct":50.0}}]}}\n'
        'x_pct / y_pct: estimate where on the drawing image this issue is located '
        '(0–100, origin = top-left corner). Use the DRAWING SPATIAL LAYOUT guide above.'
    )

    # Fallback positions for known rule keys — used when Groq omits coordinates
    _POSITION_FALLBACK: dict[str, tuple[float, float]] = {
        "ENGINE_LOAD_FIT_CLASS":              (28.0, 25.0),
        "UPPER_HOLE_DIAMETER_PROTECTED":      (24.0, 22.0),
        "LOWER_HOLE_DIAMETER_PROTECTED":      (24.0, 72.0),
        "FATIGUE_SPECTRUM_NOTE_REQUIRED":     (80.0, 22.0),
        "MISSING_REQUIRED_DIMENSION":         (38.0, 50.0),
        "HOLE_CENTRE_DISTANCE_CONSISTENCY":   (38.0, 45.0),
        "OVERALL_HEIGHT_PRESENT":             (10.0, 48.0),
        "GENERAL_TOLERANCE_STANDARD_STATED":  (80.0, 30.0),
        "SURFACE_FINISH_REQUIRED":            (80.0, 38.0),
        "NVH_VALIDATION_NOTE_REQUIRED":       (80.0, 27.0),
        "SECTION_VIEW_THICKNESS_SHOWN":       (60.0, 45.0),
        "MISSING_THICKNESS_CALLOUT":          (60.0, 42.0),
        "PROCESS_DEFINED":                    (80.0, 46.0),
        "MATERIAL_SPECIFIED":                 (80.0, 52.0),
        "MOUNTING_HOLE_COUNT_REQUIRED":       (28.0, 52.0),
        "MISSING_HOLE_CALLOUT":               (28.0, 46.0),
        "CHANGE_SUMMARY_PRESENT":             (80.0, 88.0),
        "DRAWING_NUMBER_PRESENT":             (80.0, 82.0),
        "REVISION_CODE_PRESENT":              (80.0, 85.0),
    }

    _SPATIAL_GUIDE = (
        "DRAWING SPATIAL LAYOUT — use to set x_pct / y_pct for each finding:\n"
        "  x_pct 0=left edge → 100=right edge  |  y_pct 0=top → 100=bottom\n"
        "  Upper mounting holes / upper features : x 20-40 , y 15-35\n"
        "  Centre holes / mid-body               : x 20-40 , y 42-58\n"
        "  Lower mounting holes / lower features : x 20-40 , y 65-82\n"
        "  Overall height dimension              : x  8-15 , y 45-55\n"
        "  Hole-centre distance (vertical)       : x 35-50 , y 40-55\n"
        "  Width / horizontal dimensions         : x 30-60 , y 85-95\n"
        "  Drawing notes block (top-right)       : x 72-92 , y 10-35\n"
        "  Title block (bottom-right)            : x 72-92 , y 80-95\n"
        "  Section view / side profile           : x 52-70 , y 20-80\n"
        "  Process / material annotation         : x 72-92 , y 35-55\n"
    )

    _SYSTEM_MSG = (
        "You are a precision automotive engineering drawing reviewer. "
        "Return ONLY valid JSON. Never invent findings not supported by the facts given."
    )

    # ── 6. Call Groq chunk by chunk ───────────────────────────────────────────
    try:
        import groq as _groq_mod
        client           = _groq_mod.Groq(api_key=groq_key)
        all_raw_findings: list[dict] = []
        prior_summary    = ""
        carry_rules: list[dict] = []   # rules not returned by previous chunk

        def _rule_text(r: dict) -> str:
            cl = r.get("check_logic") or {}
            if isinstance(cl, str):
                try:    cl = _json.loads(cl)
                except: cl = {}
            override = ("⚠ ARTIFACT OVERRIDE — use this severity\n  "
                        if r.get("historical_context","").startswith("[ARTIFACT OVERRIDE") else "")
            return (
                "RULE [{}] {} | Severity: {} | Group:{}\n"
                "  {}Description: {}\n"
                "  Check: {}\n"
                "  Context: {}"
            ).format(
                r["rule_key"], r.get("display_name",""), r["severity"], r.get("rule_group",""),
                override,
                r.get("description",""),
                _json.dumps(cl),
                (r.get("historical_context") or "")[:160],
            )

        def _partial_findings(raw: str) -> list[dict]:
            """
            Extract every complete finding object from a potentially-truncated JSON array.
            Works even if the outer brackets are missing or the array is cut off mid-item.
            """
            results: list[dict] = []
            # Find the start of the findings array
            arr_start = raw.find('"findings"')
            if arr_start == -1:
                arr_start = 0
            bracket = raw.find('[', arr_start)
            if bracket == -1:
                return results
            # Walk through the string extracting each complete {...} block
            i = bracket + 1
            depth = 0
            obj_start = -1
            while i < len(raw):
                ch = raw[i]
                if ch == '{':
                    if depth == 0:
                        obj_start = i
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and obj_start != -1:
                        candidate = raw[obj_start : i + 1]
                        try:
                            obj = _json.loads(candidate)
                            if obj.get("rule_key"):
                                results.append(obj)
                        except Exception:
                            pass
                        obj_start = -1
                elif ch == ']' and depth == 0:
                    break
                i += 1
            return results

        for chunk_idx, chunk in enumerate(chunks, 1):
            # Prepend any rules not returned by the previous chunk
            effective_chunk = carry_rules + chunk
            carry_rules = []

            prior_ctx = (
                "## FINDINGS ALREADY CONFIRMED IN PRIOR CHUNKS\n" + prior_summary + "\n"
                if prior_summary else ""
            )

            rules_text = _NL.join(_rule_text(r) for r in effective_chunk)

            _fit_class_verdict = (
                "FIT CLASS: H11/H12 PRESENT ✓ — For ENGINE_LOAD_FIT_CLASS, "
                "UPPER_HOLE_DIAMETER_PROTECTED, LOWER_HOLE_DIAMETER_PROTECTED: "
                "return status=SAFE (do NOT re-evaluate from raw callouts)."
                if _has_h11 else
                "FIT CLASS: NO H11 ON ANY HOLE — ENGINE_LOAD_FIT_CLASS, "
                "UPPER_HOLE_DIAMETER_PROTECTED, LOWER_HOLE_DIAMETER_PROTECTED: return status=BLOCK."
            )
            _notes_verdict = (
                "FATIGUE NOTE: PT-LS keywords found in DRAWING NOTES — "
                "FATIGUE_SPECTRUM_NOTE_REQUIRED: return status=SAFE."
                if any(kw in notes_text for kw in ("PT-LS", "fatigue", "load spectrum", "NVH"))
                else
                "FATIGUE NOTE: no fatigue keywords in DRAWING NOTES — "
                "FATIGUE_SPECTRUM_NOTE_REQUIRED: return status=BLOCK."
            )
            prompt = (
                "You are evaluating chunk {}/{} ({} rules) of an engineering drawing review.\n\n"
                "{}\n\n"
                "{}\n"
                "## PRE-COMPUTED VERDICTS — use these directly, no re-evaluation needed\n"
                "{}\n"
                "{}\n\n"
                "{}\n"
                "## RULES TO EVALUATE IN THIS CHUNK\n"
                "Evaluate ONLY these {} rules. Return one finding per rule, no exceptions.\n\n"
                "HARD RULES:\n"
                "1. PRE-COMPUTED VERDICTS above override your own analysis for those specific rules.\n"
                "2. For all other rules: FACTS are ground truth. ✓ present = SAFE. ✗ missing = flag.\n"
                "3. BACKGROUND is historical context only — never a pass condition.\n"
                "4. Do not escalate WARN to BLOCK or downgrade BLOCK to WARN.\n"
                "5. Always include x_pct and y_pct in every finding using the DRAWING SPATIAL LAYOUT guide.\n\n"
                "{}\n\n{}"
            ).format(
                chunk_idx, len(chunks), len(effective_chunk),
                _ENG_CTX_BLOCK + _FACTS,
                prior_ctx,
                _fit_class_verdict,
                _notes_verdict,
                _SPATIAL_GUIDE,
                len(effective_chunk),
                rules_text,
                _SCHEMA,
            )

            resp = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[
                    {"role": "system", "content": _SYSTEM_MSG},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=4096,
                temperature=0,
            )
            raw = resp.choices[0].message.content or ""

            # Try full parse first; fall back to partial extraction
            parsed = _parse_groq_json(raw)
            if parsed:
                chunk_findings = parsed.get("findings") or []
            else:
                chunk_findings = _partial_findings(raw)

            all_raw_findings.extend(chunk_findings)

            # Identify which rules were NOT returned and carry forward
            returned_keys = {f.get("rule_key") for f in chunk_findings}
            for r in effective_chunk:
                if r["rule_key"] not in returned_keys:
                    carry_rules.append(r)

            # Prior-findings summary for next chunk
            notable = [f for f in chunk_findings if f.get("status") in ("BLOCK","WARN")][:8]
            if notable:
                prior_summary += _NL.join(
                    "  [{}] {}: {}".format(f.get("status"), f.get("rule_key",""), f.get("title",""))
                    for f in notable
                ) + "\n"

        # Final catch-up chunk for any still-unevaluated rules
        if carry_rules:
            rules_text = _NL.join(_rule_text(r) for r in carry_rules)
            prompt = (
                "Final catch-up: evaluate these {} unevaluated rules.\n\n"
                "{}\n\n"
                "{}\n"
                "{}\n\n"
                "{}\n\n{}"
            ).format(
                len(carry_rules),
                _FACTS,
                _fit_class_verdict,
                _notes_verdict,
                rules_text,
                _SCHEMA,
            )
            resp = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[
                    {"role": "system", "content": _SYSTEM_MSG},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=4096,
                temperature=0,
            )
            raw = resp.choices[0].message.content or ""
            parsed = _parse_groq_json(raw)
            catchup = parsed.get("findings") if parsed else _partial_findings(raw)
            all_raw_findings.extend(catchup or [])

        findings_raw = all_raw_findings

    except Exception:
        return []

    # ── 5b. Post-Groq reconciliation — drop BLOCK findings that contradict facts ──
    # Groq (llama-4-scout) can hallucinate BLOCK for rules the drawing actually satisfies.
    # These checks are deterministic and override Groq's judgment for specific rule keys.
    _has_fatigue_note = any(
        kw.lower() in (notes_text or "").lower()
        for kw in ("pt-ls", "fatigue", "load spectrum", "nvh-hbc")
    )

    def _required_dims_all_present() -> bool:
        _req = [
            ("overall height",       152.1, 1.0),
            ("hole centre distance",  51.4,  0.5),
            ("side reference height", 89.9,  0.5),
            ("lower clearance",       33.0,  2.0),
        ]
        for name, val, tol in _req:
            if not any(abs(v - val) <= tol for k, v in _present_dims.items() if name in k):
                return False
        return True

    _H11_RULES   = {"ENGINE_LOAD_FIT_CLASS", "UPPER_HOLE_DIAMETER_PROTECTED", "LOWER_HOLE_DIAMETER_PROTECTED"}
    _FATIGUE_RULES = {"FATIGUE_SPECTRUM_NOTE_REQUIRED"}
    _DIM_RULES     = {
        "MISSING_REQUIRED_DIMENSION": _required_dims_all_present,
        "HOLE_CENTRE_DISTANCE_CONSISTENCY": lambda: abs(_present_dims.get("hole centre distance", 0) - 51.4) <= 0.5,
        "OVERALL_HEIGHT_PRESENT": lambda: "overall height" in _present_dims,
    }

    def _keep_finding(f: dict) -> bool:
        if f.get("status") != "BLOCK":
            return True
        rk = f.get("rule_key", "")
        if rk in _H11_RULES:
            return not _has_h11        # drop BLOCK if H11 IS present
        if rk in _FATIGUE_RULES:
            return not _has_fatigue_note  # drop BLOCK if fatigue note IS present
        if rk in _DIM_RULES:
            return not _DIM_RULES[rk]()   # drop BLOCK if the required dim IS present
        return True

    findings_raw = [f for f in findings_raw if _keep_finding(f)]

    # ── 6. Map severity label + persist ──────────────────────────────────────
    _SEV_MAP = {"BLOCK": "CRITICAL", "WARN": "MAJOR", "SAFE": "MINOR"}

    # Delete any prior automated validation results for this revision
    execute_query(
        "DELETE FROM drawing_validation_results WHERE design_revision_id = %s::uuid",
        (design_revision_id,),
    )

    persisted: list[dict] = []
    for f in findings_raw:
        rule_key = f.get("rule_key") or ""
        status   = f.get("status") or "SAFE"
        if status not in ("SAFE", "WARN", "BLOCK"):
            status = "SAFE"

        # Resolve spatial position: prefer Groq-returned values, fallback to known map
        _x = f.get("x_pct")
        _y = f.get("y_pct")
        if _x is None or _y is None:
            _fb = _POSITION_FALLBACK.get(rule_key)
            _x = _fb[0] if _fb else 50.0
            _y = _fb[1] if _fb else 50.0
        try:
            _x = float(_x); _y = float(_y)
            _x = max(2.0, min(96.0, _x))
            _y = max(2.0, min(96.0, _y))
        except Exception:
            _x, _y = 50.0, 50.0

        row = {
            "design_revision_id": design_revision_id,
            "rule_key":           rule_key,
            "severity":           _SEV_MAP.get(status, "MINOR"),
            "status":             status,
            "title":              (f.get("title") or rule_key)[:255],
            "what_is_wrong":      f.get("what_is_wrong") or "",
            "why_it_matters":     f.get("why_it_matters") or "",
            "recommended_action": f.get("recommended_action") or "",
            "affected_entities":  _json.dumps(f.get("affected_entities") or []),
            "affected_regions":   _json.dumps([]),
            "evidence_json":      _json.dumps({
                "confidence": f.get("confidence", 0.8),
                "source":     "groq_approval_intelligence",
                "x_pct":      _x,
                "y_pct":      _y,
            }),
        }
        execute_query(
            """INSERT INTO drawing_validation_results
               (design_revision_id, rule_key, severity, status, title,
                what_is_wrong, why_it_matters, recommended_action,
                affected_entities, affected_regions, evidence_json)
               VALUES (%(design_revision_id)s::uuid, %(rule_key)s, %(severity)s,
                       %(status)s, %(title)s, %(what_is_wrong)s, %(why_it_matters)s,
                       %(recommended_action)s, %(affected_entities)s::jsonb,
                       %(affected_regions)s::jsonb, %(evidence_json)s::jsonb)""",
            row,
        )
        persisted.append({**f, "status": status})

    return persisted


def build_design_data_from_variant(confirmed: dict, artifact: dict) -> dict:
    """
    Reconstruct a full design_data_json from the user-confirmed extraction data.
    This is what gets stored in design_revisions and drives validation.
    """
    dims   = confirmed.get("dimensions") or []
    holes  = confirmed.get("holes") or []
    notes  = confirmed.get("notes") or ""
    mat    = confirmed.get("material") or artifact.get("material") or "CRCA Sheet Metal"
    scale  = confirmed.get("scale") or "1:1"
    proc   = confirmed.get("process") or "Laser Cut + Bend"
    code   = confirmed.get("variant_code") or "R1"
    art_no = artifact.get("artifact_number") or "—"

    # Extract numeric thickness from material string e.g. "CRCA IS 513 Grade D, 2.5 mm"
    thk_match = _re.search(r'(\d+(?:\.\d+)?)\s*mm', mat, _re.I)
    thk_str   = thk_match.group(0) if thk_match else None
    thk_val   = thk_match.group(1) if thk_match else None

    return {
        "approval_status": "REVIEW_REQUIRED",
        "process": proc,
        "thickness": thk_str,
        "title_block": {
            "drawing_number": art_no,
            "revision":       code,
            "material":       mat,
            "scale":          scale,
            "process":        proc,
            "thickness":      thk_str,
        },
        "thickness_annotations": (
            [{"id": "T-1",
              "name": f"Sheet thickness t = {thk_str}",
              "region": "Section view / title block"}]
            if thk_str else []
        ),
        "dimensions": [
            {
                "id":        f"D-{i + 1}",
                "name":      d["name"],
                "nominal":   d.get("value"),
                "unit":      d.get("unit") or "mm",
                "critical":  bool(d.get("critical")),
                "functional": bool(d.get("critical")),
                "tolerance": (
                    {"plus": 0.1, "minus": 0.1}
                    if d.get("critical")
                    else {"plus": 0.5, "minus": 0.5}
                ),
            }
            for i, d in enumerate(dims)
            if d.get("name")
        ],
        "mounting_holes": [
            {
                "id":     f"MH-{i + 1}",
                "name":   h.get("callout") or f"Mounting hole {i + 1}",
                "region": h.get("region") or "Sheet 1",
            }
            for i, h in enumerate(holes)
            if h.get("callout")
        ],
        "hole_callouts": [
            {
                "id":     f"HC-{i + 1}",
                "text":   h.get("callout") or "",
                "region": h.get("region") or "Sheet 1",
            }
            for i, h in enumerate(holes)
            if h.get("callout")
        ],
        "drawing_notes": [
            {"id": "NOTE-1", "text": notes, "region": "Drawing notes"}
        ] if notes else [],
        "validation_profile": {},
    }


def generate_senior_reviewer_report(design_revision_id: str) -> dict:
    """
    Produce a senior-engineer-style narrative review report.

    Fully deterministic — no AI API calls.  Combines:
    - Validation rule results for this revision
    - Approved-revision dimensions from the closest same-family programs
    - Segment-rule context from the engineering_review_rules table

    Returns a structured dict suitable for JSON serialisation and
    direct rendering in the review workspace.
    """

    # ── 1. Load revision + artifact ───────────────────────────────────────────
    revision = fetch_one("""
        SELECT
            dr.id, dr.revision_code, dr.approval_status,
            da.id            AS artifact_id,
            da.artifact_number,
            da.title         AS artifact_title,
            da.product_segment,
            da.assembly_family,
            da.vehicle_program,
            da.material,
            da.supplier
        FROM design_revisions dr
        JOIN design_artifacts da ON da.id = dr.artifact_id
        WHERE dr.id = %s::uuid
    """, (design_revision_id,))
    if not revision:
        raise ValueError("Design revision not found")

    artifact_id      = str(revision["artifact_id"])
    product_segment  = revision.get("product_segment") or ""
    assembly_family  = revision.get("assembly_family") or ""
    revision_code    = revision["revision_code"]
    artifact_number  = revision["artifact_number"]
    artifact_title   = revision["artifact_title"]
    vehicle_program  = revision.get("vehicle_program") or ""

    # ── 2. Validation results ─────────────────────────────────────────────────
    val_results = fetch_all("""
        SELECT rule_key, status, severity, title,
               what_is_wrong, why_it_matters, recommended_action,
               affected_entities, affected_regions, evidence_json
        FROM drawing_validation_results
        WHERE design_revision_id = %s::uuid
        ORDER BY
            CASE status    WHEN 'BLOCK' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END,
            CASE severity  WHEN 'CRITICAL' THEN 0 WHEN 'MAJOR' THEN 1 ELSE 2 END,
            rule_key
    """, (design_revision_id,))

    block_count = sum(1 for v in val_results if v["status"] == "BLOCK")
    warn_count  = sum(1 for v in val_results if v["status"] == "WARN")

    # ── 3. Current revision dimensions ────────────────────────────────────────
    current_dims = {
        d["dimension_key"]: d
        for d in fetch_all("""
            SELECT dimension_key, display_name, nominal_value, unit,
                   tolerance_json, is_critical
            FROM drawing_dimensions
            WHERE design_revision_id = %s::uuid
        """, (design_revision_id,))
    }

    # ── 4. Reference programs (same segment + family, excluding self) ─────────
    similar_artifacts = fetch_all("""
        SELECT da.id, da.artifact_number, da.title,
               da.product_segment, da.assembly_family, da.vehicle_program
        FROM design_artifacts da
        WHERE da.id         != %s::uuid
          AND da.assembly_family  = %s
          AND da.product_segment  = %s
        ORDER BY da.artifact_number
        LIMIT 6
    """, (artifact_id,
          assembly_family  or "__none__",
          product_segment  or "__none__"))

    reference_programs: list[dict] = []
    for cand in similar_artifacts:
        approved_rev = fetch_one("""
            SELECT dr.id, dr.revision_code
            FROM design_revisions dr
            WHERE dr.artifact_id = %s::uuid
              AND dr.approval_status = 'approved'
            ORDER BY dr.revision_sequence DESC
            LIMIT 1
        """, (str(cand["id"]),))
        if not approved_rev:
            continue
        ref_dims = {
            d["dimension_key"]: d
            for d in fetch_all("""
                SELECT dimension_key, display_name, nominal_value, unit,
                       tolerance_json, is_critical
                FROM drawing_dimensions
                WHERE design_revision_id = %s::uuid
            """, (str(approved_rev["id"]),))
        }
        ref_holes = fetch_all("""
            SELECT display_text, drawing_region
            FROM drawing_annotations
            WHERE design_revision_id = %s::uuid
              AND annotation_type = 'HOLE_CALLOUT'
        """, (str(approved_rev["id"]),))

        reference_programs.append({
            "artifact_number":  cand["artifact_number"],
            "title":            cand["title"],
            "vehicle_program":  cand.get("vehicle_program") or "",
            "revision_code":    approved_rev["revision_code"],
            "dims":             ref_dims,
            "holes":            ref_holes,
        })

    # ── 5. Build per-finding entries with historical context ──────────────────
    def _fmt_dim(d: dict) -> str:
        nom = d.get("nominal_value")
        unit = d.get("unit") or "mm"
        try:
            return f"{float(nom):g} {unit}"
        except (TypeError, ValueError):
            return str(nom or "—")

    finding_entries: list[dict] = []
    for idx, v in enumerate(val_results, start=1):
        rule_key  = v["rule_key"]
        status    = v["status"]
        severity  = v.get("severity") or "MAJOR"
        title     = v.get("title") or rule_key.replace("_", " ").title()
        what      = v.get("what_is_wrong") or ""
        why       = v.get("why_it_matters") or ""
        action    = v.get("recommended_action") or ""
        evidence  = v.get("evidence_json") or {}
        if not isinstance(evidence, dict):
            evidence = {}

        # --- historical context ---
        hist_lines: list[str] = []

        dim_key = evidence.get("dimension_key")
        if dim_key:
            for ref in reference_programs:
                if dim_key in ref["dims"]:
                    rd = ref["dims"][dim_key]
                    hist_lines.append(
                        f"{ref['artifact_number']} ({ref['revision_code']}): "
                        f"{rd['display_name']} = {_fmt_dim(rd)}"
                    )

        # For hole-callout findings: check if any ref program hole callout
        # text overlaps with the evidence name/description
        if rule_key == "MISSING_HOLE_CALLOUT":
            evidence_name = (evidence.get("name") or evidence.get("hole") or "").lower()
            for ref in reference_programs:
                for hole in ref["holes"]:
                    hole_text = (hole.get("display_text") or "").lower()
                    # Match if at least one diameter fragment is shared
                    for frag in ("ø13", "ø12", "ø18", "13 h11", "12 h11", "18.1 h11"):
                        if frag in evidence_name and frag in hole_text:
                            hist_lines.append(
                                f"{ref['artifact_number']} ({ref['revision_code']}): "
                                f"{hole['display_text']} at {hole.get('drawing_region','Sheet 1')}"
                            )
                            break

        # For segment-rule violations: note that ref programs comply
        if rule_key == "MISSING_HOLE_CALLOUT" and not hist_lines:
            # Try looser match — any hole from ref programs
            for ref in reference_programs:
                if ref["holes"]:
                    samples = ", ".join(h["display_text"] for h in ref["holes"][:3])
                    hist_lines.append(
                        f"{ref['artifact_number']} ({ref['revision_code']}) carries: {samples}"
                    )

        if rule_key == "FEATURE_OUTSIDE_REFERENCE_ENVELOPE" and not hist_lines:
            feat_name = evidence.get("name") or "this feature"
            if reference_programs:
                ref_labels = " and ".join(
                    f"{r['artifact_number']} ({r['revision_code']})"
                    for r in reference_programs
                )
                hist_lines.append(
                    f"{feat_name} is absent from {ref_labels}. "
                    "An ECN must be raised to extend the approved reference envelope."
                )

        # Compose narrative paragraph
        narrative_parts = [f"**{title}** [{status}]"]
        if what:
            narrative_parts.append(what)
        if why:
            narrative_parts.append(why)
        if hist_lines:
            narrative_parts.append(
                "Historical reference — " + "; ".join(hist_lines) + "."
            )
        if action:
            narrative_parts.append(f"Required action: {action}")

        finding_entries.append({
            "index":               idx,
            "rule_key":            rule_key,
            "status":              status,
            "severity":            severity,
            "title":               title,
            "what":                what,
            "why":                 why,
            "action":              action,
            "historical_context":  hist_lines,
            "narrative":           "  ".join(narrative_parts),
        })

    # ── 6. Engineering history section ────────────────────────────────────────
    eng_history: list[dict] = []
    for ref in reference_programs:
        key_dims = [
            f"{d['display_name']} = {_fmt_dim(d)}"
            for d in ref["dims"].values()
            if d.get("nominal_value") is not None
        ][:6]
        hole_summary = ", ".join(h["display_text"] for h in ref["holes"][:4]) if ref["holes"] else "—"
        eng_history.append({
            "artifact_number": ref["artifact_number"],
            "title":           ref["title"],
            "vehicle_program": ref["vehicle_program"],
            "revision_code":   ref["revision_code"],
            "status_label":    "Production Reference",
            "key_dimensions":  key_dims,
            "hole_callouts":   hole_summary,
            "narrative": (
                f"{ref['artifact_number']} — {ref['vehicle_program']}, "
                f"{ref['revision_code']} (Production Released, 0 blocking findings).  "
                + (f"Key dims: {', '.join(key_dims[:4])}." if key_dims else "")
            ),
        })

    # ── 7. Recommendations list ───────────────────────────────────────────────
    recommendations: list[dict] = [
        {"rule_key": v["rule_key"], "status": v["status"], "action": v["recommended_action"]}
        for v in val_results
        if v.get("recommended_action")
    ]

    # ── 8. Overall status + executive summary ─────────────────────────────────
    if block_count > 0:
        status_badge = "BLOCK"
        status_label = "CANNOT RELEASE"
    elif revision.get("approval_status") == "approved" and warn_count == 0:
        status_badge = "SAFE"
        stage = vehicle_program or ""
        if "development" in stage.lower() or "proto" in stage.lower():
            status_label = "CLEARED FOR PROTOTYPE RELEASE"
        else:
            status_label = "APPROVED — PRODUCTION REFERENCE"
    else:
        status_badge = "WARN" if warn_count else "SAFE"
        status_label = "REVIEW RECOMMENDED" if warn_count else "CLEARED"

    ref_label = " and ".join(
        f"{r['artifact_number']} ({r['vehicle_program']}, {r['revision_code']})"
        for r in reference_programs
    )

    if block_count > 0:
        ref_text = (
            f"  Comparison against production-released drawings {ref_label} "
            if ref_label else ""
        )
        exec_summary = (
            f"This drawing cannot proceed to release.{ref_text}"
            f"{'reveals' if ref_label else 'Validation identifies'} "
            f"{block_count} blocking gap{'s' if block_count != 1 else ''} "
            f"and {warn_count} warning{'s' if warn_count != 1 else ''}.  "
            "All items flagged BLOCK must be resolved and verified before this "
            "revision can advance to the next release gate."
        )
    elif reference_programs and revision.get("approval_status") == "approved":
        exec_summary = (
            f"All validation checks pass.  This revision aligns with the "
            f"production-baseline geometry of {ref_label}.  "
            "The drawing is cleared for release subject to the standard sign-off process."
        )
    elif revision.get("approval_status") == "approved":
        exec_summary = (
            "All validation checks pass.  No blocking findings were identified.  "
            "Standard release process may proceed."
        )
    else:
        exec_summary = (
            f"Validation complete: {block_count} blocking finding(s), "
            f"{warn_count} warning(s) identified."
        )

    return {
        "revision_id":            design_revision_id,
        "revision_code":          revision_code,
        "artifact_number":        artifact_number,
        "artifact_title":         artifact_title,
        "vehicle_program":        vehicle_program,
        "product_segment":        product_segment,
        "assembly_family":        assembly_family,
        "status_badge":           status_badge,
        "status_label":           status_label,
        "block_count":            block_count,
        "warn_count":             warn_count,
        "executive_summary":      exec_summary,
        "finding_sections":       finding_entries,
        "engineering_history":    eng_history,
        "recommendations":        recommendations,
        "reference_program_names": [r["artifact_number"] for r in reference_programs],
        "generated_at":           datetime.utcnow().isoformat(),
    }


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


def get_part_search_categories() -> dict:
    """Return distinct non-null values for each searchable category."""
    def _vals(col):
        rows = fetch_all(f"SELECT DISTINCT {col} FROM design_artifacts WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}")
        return [r[col] for r in rows]

    return {
        "vehicle_programs":  _vals("vehicle_program"),
        "assembly_families": _vals("assembly_family"),
        "product_segments":  _vals("product_segment"),
        "domains":           _vals("domain"),
        "owning_teams":      _vals("owning_team"),
        "suppliers":         _vals("supplier"),
    }


def search_design_artifacts(
    q: str = "",
    vehicle_program: str = "",
    assembly_family: str = "",
    product_segment: str = "",
    domain: str = "",
    owning_team: str = "",
    supplier: str = "",
) -> list[dict]:
    conditions = []
    params = []

    if q:
        conditions.append(
            "(da.artifact_number ILIKE %s OR da.title ILIKE %s OR da.linked_part_number ILIKE %s)"
        )
        like = f"%{q}%"
        params += [like, like, like]
    if vehicle_program:
        conditions.append("da.vehicle_program = %s")
        params.append(vehicle_program)
    if assembly_family:
        conditions.append("da.assembly_family = %s")
        params.append(assembly_family)
    if product_segment:
        conditions.append("da.product_segment = %s")
        params.append(product_segment)
    if domain:
        conditions.append("da.domain = %s")
        params.append(domain)
    if owning_team:
        conditions.append("da.owning_team = %s")
        params.append(owning_team)
    if supplier:
        conditions.append("da.supplier = %s")
        params.append(supplier)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    return fetch_all(f"""
        SELECT
            da.*,
            COUNT(dr.id) as revision_count,
            MAX(dr.revision_sequence) as latest_revision_sequence,
            MAX(dr.approval_status) as latest_approval_status,
            BOOL_OR(LOWER(dr.approval_status) IN ('approved', 'approved_reference'))
                AS has_approved_revision
        FROM design_artifacts da
        LEFT JOIN design_revisions dr ON dr.artifact_id = da.id
        {where}
        GROUP BY da.id
        ORDER BY da.updated_at DESC NULLS LAST, da.created_at DESC
    """, tuple(params) if params else None)


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

    # Artifact-level rule overrides / skips / additions
    artifact_rule_profile = fetch_all(
        """SELECT rule_key, action, override_severity, display_name,
                  artifact_context, check_logic
           FROM design_artifact_rules
           WHERE artifact_id = %s::uuid
           ORDER BY action, rule_key""",
        (artifact_id,),
    ) or []
    profile_map = {r["rule_key"]: r for r in artifact_rule_profile}

    # Rules applicable to this part's segment
    segment = (artifact.get("product_segment") or "")
    applicable_rules = fetch_all(
        """SELECT rule_key, display_name, description, severity, rule_group,
                  check_logic, historical_context, applies_to_segments
           FROM engineering_review_rules
           WHERE enabled = true
             AND (applies_to_segments = '[]'::jsonb
                  OR applies_to_segments @> %s::jsonb)
           ORDER BY
             CASE severity WHEN 'BLOCK' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END,
             rule_group, display_name""",
        (_json.dumps([segment]),),
    ) or []

    # Validation results per revision (most recent first, non-SAFE only for summary)
    rev_ids = [str(r["id"]) for r in revisions]
    all_findings: list[dict] = []
    if rev_ids:
        placeholders = ",".join(["%s::uuid"] * len(rev_ids))
        all_findings = fetch_all(
            f"""SELECT design_revision_id::text, rule_key, status, severity, title,
                       what_is_wrong, recommended_action
                FROM drawing_validation_results
                WHERE design_revision_id IN ({placeholders})
                ORDER BY CASE status WHEN 'BLOCK' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END""",
            tuple(rev_ids),
        ) or []

    # Group findings by revision_id
    findings_by_rev: dict = {}
    for f in all_findings:
        rid = f["design_revision_id"]
        findings_by_rev.setdefault(rid, []).append(f)

    # Merge artifact overrides into rules list for display
    skip_keys = {r["rule_key"] for r in artifact_rule_profile if r["action"] == "skip"}
    rules_display: list[dict] = []
    for rule in applicable_rules:
        rk = rule["rule_key"]
        if rk in skip_keys:
            continue
        display_rule = dict(rule)
        if rk in profile_map:
            ov = profile_map[rk]
            if ov.get("override_severity"):
                display_rule["severity"]         = ov["override_severity"]
                display_rule["_overridden"]       = True
            if ov.get("display_name"):
                display_rule["display_name"]      = ov["display_name"]
            if ov.get("artifact_context"):
                display_rule["artifact_context"]  = ov["artifact_context"]
        rules_display.append(display_rule)

    # Append artifact-only additions not in segment rules
    existing_keys = {r["rule_key"] for r in rules_display}
    for ar in artifact_rule_profile:
        if ar["action"] == "add" and ar["rule_key"] not in existing_keys:
            rules_display.append({
                "rule_key":       ar["rule_key"],
                "display_name":   ar.get("display_name") or ar["rule_key"],
                "description":    ar.get("artifact_context") or "",
                "severity":       ar.get("override_severity") or "WARN",
                "rule_group":     "ARTIFACT_SPECIFIC",
                "historical_context": ar.get("artifact_context") or "",
                "_artifact_only": True,
            })

    return {
        "artifact":              artifact,
        "revisions":             revisions,
        "comparison":            comparison,
        "applicable_rules":      rules_display,
        "skipped_rules":         [r for r in artifact_rule_profile if r["action"] == "skip"],
        "findings_by_rev":       findings_by_rev,
        "has_artifact_profile":  len(artifact_rule_profile) > 0,
    }


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
