"""
ReviewGraph orchestration layer.

Creates engineering review sessions from part revisions, persists graph
relationships, runs deterministic review rules, and exposes review workspace data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from app.database import execute_query, fetch_all, fetch_one
from app.revision_analysis import diff_revision_specs, map_changes_to_functions


RISK_RANK = {"SAFE": 0, "WARN": 1, "BLOCK": 2}


def _max_risk(statuses: List[str]) -> str:
    if not statuses:
        return "SAFE"
    return max(statuses, key=lambda status: RISK_RANK.get(status, 0))


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _build_part_family_patterns(part_number: Optional[str]) -> list[str]:
    if not part_number:
        return []

    patterns = [part_number]
    for separator in ("-", "_", " "):
        if separator in part_number:
            root = part_number.split(separator)[0]
            if root and root != part_number:
                patterns.append(f"{root}%")
            break

    return patterns


def _get_rule_id(rule_key: str) -> Optional[int]:
    rule = fetch_one(
        "SELECT id FROM engineering_review_rules WHERE rule_key = %s",
        (rule_key,),
    )
    return rule["id"] if rule else None


def _ensure_graph_node(entity_type: str, entity_id: Any, label: str, metadata: dict | None = None) -> str:
    row = fetch_one("""
        INSERT INTO engineering_graph_nodes (entity_type, entity_id, label, metadata_json)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (entity_type, entity_id)
        DO UPDATE SET
            label = EXCLUDED.label,
            metadata_json = engineering_graph_nodes.metadata_json || EXCLUDED.metadata_json,
            updated_at = NOW()
        RETURNING id
    """, (
        entity_type,
        str(entity_id),
        label,
        Json(metadata or {}),
    ))
    return str(row["id"])


def _ensure_graph_edge(
    source_node_id: str,
    target_node_id: str,
    relationship_type: str,
    confidence: int = 90,
    evidence: dict | None = None,
) -> None:
    execute_query("""
        INSERT INTO engineering_graph_edges (
            source_node_id,
            target_node_id,
            relationship_type,
            confidence,
            evidence_json
        )
        VALUES (%s::uuid, %s::uuid, %s, %s, %s)
        ON CONFLICT (source_node_id, target_node_id, relationship_type)
        DO UPDATE SET
            confidence = GREATEST(engineering_graph_edges.confidence, EXCLUDED.confidence),
            evidence_json = engineering_graph_edges.evidence_json || EXCLUDED.evidence_json
    """, (
        source_node_id,
        target_node_id,
        relationship_type,
        confidence,
        Json(evidence or {}),
    ))


def _load_revision_context(revision_id: str) -> dict:
    revision = fetch_one("""
        SELECT
            pr.*,
            p.part_name,
            p.part_number,
            p.material,
            p.supplier,
            a.id as assembly_id,
            a.assembly_name,
            a.part_number as assembly_part_number,
            vs.id as system_id,
            vs.system_name,
            v.id as vehicle_id,
            v.name as vehicle_name,
            v.model_year as vehicle_model_year,
            v.category as vehicle_category
        FROM part_revisions pr
        JOIN parts p ON pr.part_id = p.id
        JOIN assemblies a ON p.assembly_id = a.id
        JOIN vehicle_systems vs ON a.system_id = vs.id
        JOIN vehicles v ON vs.vehicle_id = v.id
        WHERE pr.id = %s::uuid
    """, (revision_id,))

    if not revision:
        raise ValueError("Revision not found")

    previous_revision = fetch_one("""
        SELECT id, revision_number
        FROM part_revisions
        WHERE part_id = %s::uuid AND revision_number < %s
        ORDER BY revision_number DESC
        LIMIT 1
    """, (revision["part_id"], revision["revision_number"]))

    active_pfmea = fetch_one("""
        SELECT pf.*
        FROM pfmea_records pf
        LEFT JOIN part_revisions pr_link ON pf.part_revision_id = pr_link.id
        WHERE pr_link.part_id = %s::uuid OR pf.part_number = %s
        ORDER BY pf.updated_at DESC NULLS LAST, pf.created_at DESC
        LIMIT 1
    """, (revision["part_id"], revision.get("part_number")))

    process_steps = []
    prior_entries = []
    if active_pfmea:
        process_steps = fetch_all("""
            SELECT id, step_number, step_name, function_hierarchy, design_intent, critical_parameters
            FROM process_steps
            WHERE pfmea_record_id = %s
            ORDER BY step_number
        """, (active_pfmea["id"],))

        prior_entries = fetch_all("""
            SELECT
                pfe.id,
                pfe.process_step_id,
                pfe.process_step_number,
                ps.step_name as process_step_name,
                fm.canonical_name as failure_mode_name,
                pfe.potential_effect,
                pfe.severity_user_input,
                pfe.occurrence_user_input,
                pfe.detection_user_input,
                pfe.rpn_user_calculated,
                pfe.rpn_suggested,
                pfe.rpn_risk_class,
                pfe.canvas_notes
            FROM pfmea_failure_mode_entries pfe
            JOIN failure_mode_taxonomy fm ON pfe.failure_mode_id = fm.id
            LEFT JOIN process_steps ps ON pfe.process_step_id = ps.id
            WHERE pfe.pfmea_record_id = %s
            ORDER BY pfe.process_step_number, pfe.id
        """, (active_pfmea["id"],))

    incidents: list[dict] = []
    seen_incident_ids = set()
    for pattern in _build_part_family_patterns(revision.get("part_number"))[:2]:
        rows = fetch_all("""
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
            WHERE hi.part_number = %s OR hi.part_number LIKE %s
            ORDER BY hi.incident_date DESC
            LIMIT 10
        """, (revision.get("part_number"), pattern))
        for row in rows:
            if row["id"] in seen_incident_ids:
                continue
            seen_incident_ids.add(row["id"])
            incidents.append(row)

    changes = diff_revision_specs(
        revision.get("previous_specs_json") or {},
        revision.get("new_specs_json") or {},
    )
    mapped_functions = map_changes_to_functions(changes, process_steps)

    analysis_row = fetch_one("""
        SELECT analysis_json, confidence_score
        FROM revision_impact_analysis
        WHERE part_revision_id = %s::uuid
        ORDER BY analysis_timestamp DESC NULLS LAST, created_at DESC
        LIMIT 1
    """, (revision_id,))

    return {
        "revision": revision,
        "previous_revision": previous_revision,
        "active_pfmea": active_pfmea,
        "process_steps": process_steps,
        "prior_entries": prior_entries,
        "incidents": incidents,
        "changes": changes,
        "mapped_functions": mapped_functions,
        "analysis": analysis_row.get("analysis_json") if analysis_row else {},
        "analysis_confidence": analysis_row.get("confidence_score") if analysis_row else None,
    }


def _evaluate_review_rules(context: dict) -> list[dict]:
    changes = context["changes"]
    incidents = context["incidents"]
    mapped_functions = context["mapped_functions"]
    prior_entries = context["prior_entries"]

    high_changes = [change for change in changes if change.get("importance") == "HIGH"]
    material_changes = [change for change in changes if change.get("change_type") == "MATERIAL"]
    validation_changes = [
        change for change in changes
        if change.get("change_type") in ("GEOMETRY", "TOLERANCE", "DESIGN_INTERFACE", "ENVIRONMENTAL")
    ]
    high_rpn_entries = [
        entry for entry in prior_entries
        if (entry.get("rpn_user_calculated") or entry.get("rpn_suggested") or 0) > 70
    ]

    rules = []

    rules.append({
        "rule_key": "HIGH_IMPORTANCE_SPEC_CHANGE",
        "triggered": bool(high_changes),
        "status": "WARN" if high_changes else "SAFE",
        "confidence": 85 if high_changes else 70,
        "explanation": (
            f"{len(high_changes)} high-importance specification change(s) detected."
            if high_changes else
            "No high-importance specification deltas were detected."
        ),
        "evidence": high_changes,
        "recommended_actions": [
            "Review changed fields with the responsible design owner.",
            "Confirm downstream DFMEA and validation assumptions still hold.",
        ] if high_changes else [],
    })

    severe_incidents = [incident for incident in incidents if (incident.get("severity_actual") or 0) >= 8]
    material_status = "SAFE"
    if material_changes and severe_incidents:
        material_status = "BLOCK"
    elif material_changes and incidents:
        material_status = "WARN"

    rules.append({
        "rule_key": "MATERIAL_CHANGE_WITH_INCIDENTS",
        "triggered": material_status != "SAFE",
        "status": material_status,
        "confidence": 90 if material_status == "BLOCK" else 82 if material_status == "WARN" else 65,
        "explanation": (
            "Material change intersects with severe historical incidents in this part family."
            if material_status == "BLOCK" else
            "Material change intersects with historical incidents in this part family."
            if material_status == "WARN" else
            "No material change with relevant historical incidents was detected."
        ),
        "evidence": {
            "material_changes": material_changes,
            "incidents": incidents[:5],
        },
        "recommended_actions": [
            "Require material engineering signoff before approval.",
            "Review corrective actions from related historical incidents.",
        ] if material_status != "SAFE" else [],
    })

    rules.append({
        "rule_key": "TOLERANCE_OR_GEOMETRY_REQUIRES_VALIDATION",
        "triggered": bool(validation_changes),
        "status": "WARN" if validation_changes else "SAFE",
        "confidence": 80 if validation_changes else 65,
        "explanation": (
            f"{len(validation_changes)} geometry, tolerance, interface, or environmental change(s) may affect validation coverage."
            if validation_changes else
            "No geometry, tolerance, interface, or environmental changes requiring validation review were detected."
        ),
        "evidence": {
            "validation_changes": validation_changes,
            "mapped_functions": mapped_functions,
        },
        "recommended_actions": [
            "Review validation measures for affected functions.",
            "Confirm inspection and tolerance stack assumptions.",
        ] if validation_changes else [],
    })

    high_rpn_status = "SAFE"
    if high_rpn_entries and high_changes:
        high_rpn_status = "BLOCK"
    elif high_rpn_entries:
        high_rpn_status = "WARN"

    rules.append({
        "rule_key": "HIGH_RPN_CARRY_FORWARD",
        "triggered": high_rpn_status != "SAFE",
        "status": high_rpn_status,
        "confidence": 88 if high_rpn_status == "BLOCK" else 78 if high_rpn_status == "WARN" else 65,
        "explanation": (
            "Prior high-RPN DFMEA entries exist and this revision contains high-importance changes."
            if high_rpn_status == "BLOCK" else
            "Prior high-RPN DFMEA entries exist and should be reviewed for continuity."
            if high_rpn_status == "WARN" else
            "No prior high-RPN DFMEA entries were found for this review."
        ),
        "evidence": high_rpn_entries[:8],
        "recommended_actions": [
            "Block approval until high-RPN entries are reviewed or explicitly waived.",
            "Update severity, occurrence, detection, and validation measures where assumptions changed.",
        ] if high_rpn_status == "BLOCK" else [
            "Review carried-forward high-RPN entries before release.",
        ] if high_rpn_status == "WARN" else [],
    })

    rules.append({
        "rule_key": "NO_PRIOR_DFMEA",
        "triggered": not prior_entries,
        "status": "WARN" if not prior_entries else "SAFE",
        "confidence": 75 if not prior_entries else 70,
        "explanation": (
            "No prior DFMEA entries were found, so the review lacks continuity evidence."
            if not prior_entries else
            "Prior DFMEA entries are available for continuity review."
        ),
        "evidence": [],
        "recommended_actions": [
            "Create a starter DFMEA draft before approving the engineering review.",
        ] if not prior_entries else [],
    })

    return rules


def _persist_review_items(session_id: str, context: dict) -> None:
    for change in context["changes"]:
        status = "WARN" if change.get("importance") == "HIGH" else "SAFE"
        execute_query("""
            INSERT INTO engineering_review_items (
                session_id, item_type, title, description, source_type, source_id, payload_json, risk_status
            )
            VALUES (%s::uuid, 'SPEC_CHANGE', %s, %s, 'part_revisions', %s, %s, %s)
        """, (
            session_id,
            f"{change.get('field')} changed",
            f"{_as_text(change.get('old'))} -> {_as_text(change.get('new'))}",
            str(context["revision"]["id"]),
            Json(change),
            status,
        ))

    for mapped in context["mapped_functions"]:
        execute_query("""
            INSERT INTO engineering_review_items (
                session_id, item_type, title, description, source_type, source_id, payload_json, risk_status
            )
            VALUES (%s::uuid, 'AFFECTED_FUNCTION', %s, %s, 'process_steps', %s, %s, %s)
        """, (
            session_id,
            mapped.get("step_name") or "Affected function",
            ", ".join(mapped.get("matched_fields") or []),
            str(mapped.get("step_number") or ""),
            Json(mapped),
            "WARN" if mapped.get("impact") == "HIGH" else "SAFE",
        ))


def _persist_rule_results(session_id: str, rule_results: list[dict]) -> None:
    for result in rule_results:
        rule_id = _get_rule_id(result["rule_key"])
        row = fetch_one("""
            INSERT INTO engineering_review_rule_results (
                session_id,
                rule_id,
                rule_key,
                status,
                confidence,
                triggered,
                explanation,
                evidence_json,
                recommended_actions
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
            Json(result.get("evidence") or []),
            Json(result.get("recommended_actions") or []),
        ))

        if result["triggered"]:
            recommended_action = "; ".join(result.get("recommended_actions") or [])
            finding = fetch_one("""
                INSERT INTO engineering_review_findings (
                    session_id,
                    rule_result_id,
                    finding_type,
                    title,
                    status,
                    explanation,
                    affected_entity_type,
                    affected_entity_id,
                    recommended_action
                )
                VALUES (%s::uuid, %s::uuid, 'RULE_TRIGGER', %s, %s, %s, 'engineering_review_rules', %s, %s)
                RETURNING id
            """, (
                session_id,
                row["id"],
                result["rule_key"].replace("_", " ").title(),
                result["status"],
                result["explanation"],
                result["rule_key"],
                recommended_action,
            ))

            execute_query("""
                INSERT INTO engineering_review_evidence (
                    session_id,
                    finding_id,
                    evidence_type,
                    source_type,
                    source_id,
                    title,
                    excerpt,
                    relevance_score,
                    payload_json
                )
                VALUES (%s::uuid, %s::uuid, 'RULE_EVIDENCE', 'engineering_review_rule_results', %s, %s, %s, %s, %s)
            """, (
                session_id,
                finding["id"],
                str(row["id"]),
                f"Evidence for {result['rule_key']}",
                result["explanation"],
                1.0,
                Json(result.get("evidence") or []),
            ))


def _persist_graph(context: dict) -> dict:
    revision = context["revision"]
    previous_revision = context["previous_revision"]
    active_pfmea = context["active_pfmea"]

    vehicle_node = _ensure_graph_node(
        "Vehicle",
        revision["vehicle_id"],
        f"{revision['vehicle_name']} {revision.get('vehicle_model_year') or ''}".strip(),
        {"category": revision.get("vehicle_category")},
    )
    system_node = _ensure_graph_node("VehicleSystem", revision["system_id"], revision["system_name"])
    assembly_node = _ensure_graph_node("Assembly", revision["assembly_id"], revision["assembly_name"])
    part_node = _ensure_graph_node("Part", revision["part_id"], revision["part_name"], {
        "part_number": revision.get("part_number"),
        "supplier": revision.get("supplier"),
        "material": revision.get("material"),
    })
    revision_node = _ensure_graph_node(
        "PartRevision",
        revision["id"],
        f"{revision['part_name']} Rev {revision['revision_number']}",
        {
            "change_type": revision.get("change_type"),
            "approval_status": revision.get("approval_status"),
        },
    )

    _ensure_graph_edge(system_node, vehicle_node, "PART_OF")
    _ensure_graph_edge(assembly_node, system_node, "PART_OF")
    _ensure_graph_edge(part_node, assembly_node, "PART_OF")
    _ensure_graph_edge(revision_node, part_node, "AFFECTS")

    if previous_revision:
        previous_node = _ensure_graph_node(
            "PartRevision",
            previous_revision["id"],
            f"{revision['part_name']} Rev {previous_revision['revision_number']}",
        )
        _ensure_graph_edge(revision_node, previous_node, "REVISED_FROM")

    if active_pfmea:
        pfmea_node = _ensure_graph_node(
            "PFMEARecord",
            active_pfmea["id"],
            f"DFMEA #{active_pfmea['id']} - {active_pfmea['part_name']}",
            {"status": active_pfmea.get("status"), "overall_rpn": active_pfmea.get("overall_rpn")},
        )
        _ensure_graph_edge(pfmea_node, revision_node, "VALIDATES")

    for step in context["process_steps"]:
        step_node = _ensure_graph_node(
            "ProcessStep",
            step["id"],
            step["step_name"],
            {"step_number": step.get("step_number"), "critical_parameters": step.get("critical_parameters")},
        )
        _ensure_graph_edge(revision_node, step_node, "IMPACTS", confidence=70)

    for entry in context["prior_entries"]:
        entry_node = _ensure_graph_node(
            "PFMEAFailureModeEntry",
            entry["id"],
            entry.get("failure_mode_name") or f"Failure mode {entry['id']}",
            {"rpn": entry.get("rpn_user_calculated"), "risk_class": entry.get("rpn_risk_class")},
        )
        if entry.get("process_step_id"):
            step_node = _ensure_graph_node(
                "ProcessStep",
                entry["process_step_id"],
                entry.get("process_step_name") or f"Step {entry.get('process_step_number')}",
            )
            _ensure_graph_edge(step_node, entry_node, "HAS_FAILURE_MODE")

    return {
        "revision_node_id": revision_node,
        "part_node_id": part_node,
        "assembly_node_id": assembly_node,
        "system_node_id": system_node,
        "vehicle_node_id": vehicle_node,
    }


def create_review_session_from_revision(revision_id: str, created_by: str = "system") -> dict:
    context = _load_revision_context(revision_id)
    revision = context["revision"]

    existing = fetch_one("""
        SELECT id
        FROM engineering_review_sessions
        WHERE part_revision_id = %s::uuid
        ORDER BY created_at DESC
        LIMIT 1
    """, (revision_id,))
    if existing:
        return get_review_session(str(existing["id"]))

    graph_refs = _persist_graph(context)
    rule_results = _evaluate_review_rules(context)
    risk_status = _max_risk([result["status"] for result in rule_results if result["triggered"]])

    session_number = f"RG-{revision['part_number'] or str(revision['part_id'])[:8]}-R{revision['revision_number']}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    title = f"{revision['part_name']} Rev {revision['revision_number']} Engineering Review"
    summary = {
        "part_name": revision.get("part_name"),
        "part_number": revision.get("part_number"),
        "vehicle": revision.get("vehicle_name"),
        "system": revision.get("system_name"),
        "assembly": revision.get("assembly_name"),
        "change_count": len(context["changes"]),
        "affected_function_count": len(context["mapped_functions"]),
        "incident_count": len(context["incidents"]),
        "prior_dfmea_entry_count": len(context["prior_entries"]),
        "analysis_confidence": context.get("analysis_confidence"),
        "graph": graph_refs,
    }

    session = fetch_one("""
        INSERT INTO engineering_review_sessions (
            session_number,
            review_type,
            title,
            status,
            risk_status,
            part_revision_id,
            part_id,
            summary_json,
            created_by
        )
        VALUES (%s, 'REVISION_IMPACT', %s, 'DRAFT', %s, %s::uuid, %s::uuid, %s, %s)
        RETURNING id
    """, (
        session_number,
        title,
        risk_status,
        revision_id,
        str(revision["part_id"]),
        Json(summary),
        created_by,
    ))
    session_id = str(session["id"])

    _persist_review_items(session_id, context)
    _persist_rule_results(session_id, rule_results)

    execute_query("""
        INSERT INTO review_audit_log (session_id, action, actor, new_values, comments)
        VALUES (%s::uuid, 'CREATED', %s, %s, 'ReviewGraph session generated from part revision.')
    """, (session_id, created_by, Json(summary)))

    return get_review_session(session_id)


def get_review_session(session_id: str) -> dict:
    session = fetch_one("""
        SELECT
            ers.*,
            pr.revision_number,
            pr.change_type,
            pr.change_description,
            p.part_name,
            p.part_number,
            a.assembly_name,
            vs.system_name,
            v.name as vehicle_name,
            v.model_year as vehicle_model_year,
            dr.revision_code as design_revision_code,
            dr.revision_sequence as design_revision_sequence,
            dr.change_summary as design_change_summary,
            dr.source_filename as design_source_filename,
            dr.design_data_json as design_data_json,
            da.id as design_artifact_id,
            da.artifact_number,
            da.title as artifact_title,
            da.artifact_type,
            da.linked_part_number
        FROM engineering_review_sessions ers
        LEFT JOIN part_revisions pr ON ers.part_revision_id = pr.id
        LEFT JOIN parts p ON ers.part_id = p.id
        LEFT JOIN assemblies a ON p.assembly_id = a.id
        LEFT JOIN vehicle_systems vs ON a.system_id = vs.id
        LEFT JOIN vehicles v ON vs.vehicle_id = v.id
        LEFT JOIN design_revisions dr ON ers.design_revision_id = dr.id
        LEFT JOIN design_artifacts da ON dr.artifact_id = da.id
        WHERE ers.id = %s::uuid
    """, (session_id,))

    if not session:
        raise ValueError("Review session not found")

    items = fetch_all("""
        SELECT *
        FROM engineering_review_items
        WHERE session_id = %s::uuid
        ORDER BY created_at, item_type, title
    """, (session_id,))

    rule_results = fetch_all("""
        SELECT r.*, rules.display_name, rules.rule_group
        FROM engineering_review_rule_results r
        LEFT JOIN engineering_review_rules rules ON r.rule_id = rules.id
        WHERE r.session_id = %s::uuid
        ORDER BY
            CASE r.status WHEN 'BLOCK' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END,
            r.triggered DESC,
            r.created_at
    """, (session_id,))

    findings = fetch_all("""
        SELECT *
        FROM engineering_review_findings
        WHERE session_id = %s::uuid
        ORDER BY CASE status WHEN 'BLOCK' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END, created_at
    """, (session_id,))

    evidence = fetch_all("""
        SELECT *
        FROM engineering_review_evidence
        WHERE session_id = %s::uuid
        ORDER BY relevance_score DESC NULLS LAST, created_at
    """, (session_id,))

    edges = fetch_all("""
        SELECT
            e.id,
            e.relationship_type,
            e.confidence,
            source.entity_type as source_type,
            source.entity_id as source_entity_id,
            source.label as source_label,
            target.entity_type as target_type,
            target.entity_id as target_entity_id,
            target.label as target_label
        FROM engineering_graph_edges e
        JOIN engineering_graph_nodes source ON e.source_node_id = source.id
        JOIN engineering_graph_nodes target ON e.target_node_id = target.id
        WHERE source.entity_id IN (
            SELECT part_revision_id::text FROM engineering_review_sessions WHERE id = %s::uuid
            UNION
            SELECT part_id::text FROM engineering_review_sessions WHERE id = %s::uuid
            UNION
            SELECT design_revision_id::text FROM engineering_review_sessions WHERE id = %s::uuid
        )
        OR target.entity_id IN (
            SELECT part_revision_id::text FROM engineering_review_sessions WHERE id = %s::uuid
            UNION
            SELECT part_id::text FROM engineering_review_sessions WHERE id = %s::uuid
            UNION
            SELECT design_revision_id::text FROM engineering_review_sessions WHERE id = %s::uuid
        )
        ORDER BY e.relationship_type, source.label
    """, (session_id, session_id, session_id, session_id, session_id, session_id))

    approvals = fetch_all("""
        SELECT *
        FROM review_approvals
        WHERE session_id = %s::uuid
        ORDER BY created_at
    """, (session_id,))

    return {
        "session": session,
        "items": items,
        "rule_results": rule_results,
        "findings": findings,
        "evidence": evidence,
        "edges": edges,
        "approvals": approvals,
    }


def update_review_session_notes(session_id: str, reviewer_notes: str, status: Optional[str] = None) -> dict:
    current = fetch_one(
        "SELECT reviewer_notes, status FROM engineering_review_sessions WHERE id = %s::uuid",
        (session_id,),
    )
    if not current:
        raise ValueError("Review session not found")

    next_status = status or current["status"]
    execute_query("""
        UPDATE engineering_review_sessions
        SET reviewer_notes = %s,
            status = %s,
            updated_at = NOW()
        WHERE id = %s::uuid
    """, (reviewer_notes, next_status, session_id))

    execute_query("""
        INSERT INTO review_audit_log (session_id, action, actor, old_values, new_values, comments)
        VALUES (%s::uuid, 'NOTES_UPDATED', 'reviewer', %s, %s, 'Reviewer notes updated in workspace.')
    """, (
        session_id,
        Json({"reviewer_notes": current.get("reviewer_notes"), "status": current.get("status")}),
        Json({"reviewer_notes": reviewer_notes, "status": next_status}),
    ))

    return get_review_session(session_id)
