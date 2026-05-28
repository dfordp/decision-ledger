"""
Deterministic engineering drawing validation for ReviewGraph.

This layer treats extracted drawing entities as the primary review source.
AI-assisted extraction can populate the structured shape, but validation stays
rule based and explainable.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from psycopg2.extras import Json

from app.database import execute_query, fetch_all, fetch_one


CRITICAL_RULES = {
    "MISSING_REQUIRED_DIMENSION",
    "MISSING_TOLERANCE_SPECIFICATION",
    "MISSING_HOLE_CALLOUT",
    "MISSING_SECTION_REFERENCE",
    "FEATURE_OUTSIDE_REFERENCE_ENVELOPE",
    "BEND_RADIUS_BELOW_MINIMUM",
}


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("/", "_")


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [{"name": key, **item} if isinstance(item, dict) else {"name": key, "value": item} for key, item in value.items()]
    return [{"value": value}]


def _entity_key(entity_type: str, item: dict, index: int) -> str:
    raw = item.get("id") or item.get("key") or item.get("name") or item.get("feature") or index
    return f"{entity_type}:{_normalize_key(raw)}"


def _region(item: dict, fallback: str = "Sheet 1") -> str:
    return item.get("region") or item.get("drawing_region") or item.get("source") or item.get("zone") or fallback


def _severity_to_status(severity: str) -> str:
    return "BLOCK" if severity == "CRITICAL" else "WARN" if severity in {"MAJOR", "MINOR"} else "SAFE"


def _result(
    *,
    rule_key: str,
    severity: str,
    title: str,
    what: str,
    why: str,
    affected_entities: list,
    affected_regions: list,
    action: str,
    evidence: dict | list | None = None,
) -> dict:
    return {
        "rule_key": rule_key,
        "severity": severity,
        "status": _severity_to_status(severity),
        "title": title,
        "what_is_wrong": what,
        "why_it_matters": why,
        "affected_entities": affected_entities,
        "affected_regions": affected_regions,
        "recommended_action": action,
        "evidence_json": evidence or {},
    }


def iter_drawing_entities(design_data: dict) -> Iterable[dict]:
    buckets = {
        "geometric_entities": "GEOMETRY",
        "feature_positions": "FEATURE_POSITION",
        "mounting_holes": "MOUNTING_HOLE",
        "cutouts": "CUTOUT",
        "flanges": "FLANGE",
        "bend_features": "BEND",
        "weld_locations": "WELD_LOCATION",
        "section_geometry": "SECTION_GEOMETRY",
    }
    for bucket, entity_type in buckets.items():
        for index, item in enumerate(_as_list(design_data.get(bucket)), start=1):
            if not isinstance(item, dict):
                item = {"value": item}
            yield {
                "entity_type": entity_type,
                "entity_key": _entity_key(entity_type, item, index),
                "display_name": item.get("name") or item.get("feature") or item.get("callout") or f"{entity_type} {index}",
                "drawing_region": _region(item),
                "sheet_reference": item.get("sheet") or item.get("source"),
                "geometry_json": item,
                "relationships_json": item.get("relationships") or {},
                "extraction_confidence": item.get("confidence", 90),
            }


def iter_drawing_dimensions(design_data: dict, entity_lookup: dict[str, str]) -> Iterable[dict]:
    for index, item in enumerate(_as_list(design_data.get("dimensions")), start=1):
        if not isinstance(item, dict):
            item = {"value": item}
        key = _entity_key("DIMENSION", item, index)
        linked_key = item.get("entity_key") or item.get("feature_key")
        yield {
            "entity_id": entity_lookup.get(linked_key),
            "dimension_key": key,
            "display_name": item.get("name") or f"Dimension {index}",
            "nominal_value": item.get("nominal") or item.get("value"),
            "unit": item.get("unit"),
            "tolerance_json": item.get("tolerance") or item.get("tolerance_json") or {},
            "chain_key": item.get("chain") or item.get("chain_key"),
            "is_critical": bool(item.get("critical") or item.get("safety_critical") or item.get("functional")),
            "drawing_region": _region(item),
            "source_reference": item.get("source"),
        }

    for index, chain in enumerate(_as_list(design_data.get("dimension_chains")), start=1):
        if not isinstance(chain, dict):
            chain = {"value": chain}
        for dim in _as_list(chain.get("dimensions")):
            if not isinstance(dim, dict):
                dim = {"value": dim}
            key = _entity_key("DIMENSION", dim, index)
            yield {
                "entity_id": None,
                "dimension_key": key,
                "display_name": dim.get("name") or chain.get("name") or f"Dimension chain {index}",
                "nominal_value": dim.get("nominal") or dim.get("value"),
                "unit": dim.get("unit") or chain.get("unit"),
                "tolerance_json": dim.get("tolerance") or {},
                "chain_key": chain.get("id") or chain.get("name") or f"CHAIN-{index}",
                "is_critical": bool(chain.get("critical") or dim.get("critical")),
                "drawing_region": _region(dim, _region(chain)),
                "source_reference": dim.get("source") or chain.get("source"),
            }


def iter_drawing_annotations(design_data: dict, entity_lookup: dict[str, str]) -> Iterable[dict]:
    buckets = {
        "hole_callouts": "HOLE_CALLOUT",
        "section_labels": "SECTION_LABEL",
        "weld_notes": "WELD_NOTE",
        "material_notes": "MATERIAL_NOTE",
        "thickness_annotations": "THICKNESS_CALLOUT",
        "revision_metadata": "REVISION_METADATA",
        "title_block": "TITLE_BLOCK",
        "drawing_notes": "DRAWING_NOTE",
        "annotation_relationships": "ANNOTATION_RELATIONSHIP",
    }
    for bucket, annotation_type in buckets.items():
        values = design_data.get(bucket)
        if isinstance(values, dict) and bucket in {"title_block", "revision_metadata"}:
            values = [{"name": bucket, **values}]
        for index, item in enumerate(_as_list(values), start=1):
            if not isinstance(item, dict):
                item = {"value": item}
            key = _entity_key(annotation_type, item, index)
            display = item.get("text") or item.get("name") or item.get("note") or str(item.get("value") or annotation_type)
            linked_key = item.get("entity_key") or item.get("feature_key")
            yield {
                "entity_id": entity_lookup.get(linked_key),
                "annotation_type": annotation_type,
                "annotation_key": key,
                "display_text": display,
                "drawing_region": _region(item),
                "source_reference": item.get("source"),
                "metadata_json": item,
            }


def persist_drawing_extraction(design_revision_id: str, design_data: dict) -> dict:
    execute_query("DELETE FROM drawing_validation_results WHERE design_revision_id = %s::uuid", (design_revision_id,))
    execute_query("DELETE FROM drawing_annotations WHERE design_revision_id = %s::uuid", (design_revision_id,))
    execute_query("DELETE FROM drawing_dimensions WHERE design_revision_id = %s::uuid", (design_revision_id,))
    execute_query("DELETE FROM drawing_feature_entities WHERE design_revision_id = %s::uuid", (design_revision_id,))

    entity_lookup: dict[str, str] = {}
    entity_count = 0
    for entity in iter_drawing_entities(design_data):
        row = fetch_one("""
            INSERT INTO drawing_feature_entities (
                design_revision_id, entity_type, entity_key, display_name, drawing_region,
                sheet_reference, geometry_json, relationships_json, extraction_confidence
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            design_revision_id,
            entity["entity_type"],
            entity["entity_key"],
            entity["display_name"],
            entity["drawing_region"],
            entity["sheet_reference"],
            Json(entity["geometry_json"]),
            Json(entity["relationships_json"]),
            entity["extraction_confidence"],
        ))
        entity_lookup[entity["entity_key"]] = str(row["id"])
        entity_count += 1

    dimension_count = 0
    for dimension in iter_drawing_dimensions(design_data, entity_lookup):
        fetch_one("""
            INSERT INTO drawing_dimensions (
                design_revision_id, entity_id, dimension_key, display_name, nominal_value,
                unit, tolerance_json, chain_key, is_critical, drawing_region, source_reference
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            design_revision_id,
            dimension["entity_id"],
            dimension["dimension_key"],
            dimension["display_name"],
            dimension["nominal_value"],
            dimension["unit"],
            Json(dimension["tolerance_json"]),
            dimension["chain_key"],
            dimension["is_critical"],
            dimension["drawing_region"],
            dimension["source_reference"],
        ))
        dimension_count += 1

    annotation_count = 0
    for annotation in iter_drawing_annotations(design_data, entity_lookup):
        fetch_one("""
            INSERT INTO drawing_annotations (
                design_revision_id, entity_id, annotation_type, annotation_key, display_text,
                drawing_region, source_reference, metadata_json
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            design_revision_id,
            annotation["entity_id"],
            annotation["annotation_type"],
            annotation["annotation_key"],
            annotation["display_text"],
            annotation["drawing_region"],
            annotation["source_reference"],
            Json(annotation["metadata_json"]),
        ))
        annotation_count += 1

    return {
        "drawing_entity_count": entity_count,
        "drawing_dimension_count": dimension_count,
        "drawing_annotation_count": annotation_count,
    }


def _profile_items(design_data: dict, key: str) -> list[dict]:
    profile = design_data.get("validation_profile") or {}
    return _as_list(profile.get(key))


def _has_annotation(design_data: dict, bucket: str) -> bool:
    return bool(_as_list(design_data.get(bucket)))


def validate_drawing_revision(design_revision_id: str, design_data: dict) -> list[dict]:
    results: list[dict] = []

    for item in _profile_items(design_data, "missing_required_dimensions"):
        name = item.get("name") or item.get("feature") or "Critical feature"
        results.append(_result(
            rule_key="MISSING_REQUIRED_DIMENSION",
            severity="CRITICAL",
            title="Critical feature lacks dimensional reference",
            what=f"{name} is not fully dimensionally constrained.",
            why="Manufacturing cannot unambiguously locate or inspect a functional feature without a dimensional reference.",
            affected_entities=[name],
            affected_regions=[_region(item, "Mounting-hole layout")],
            action="Add the missing dimensional reference before release.",
            evidence=item,
        ))

    for item in _profile_items(design_data, "missing_tolerances"):
        name = item.get("name") or item.get("dimension") or "Critical dimension"
        results.append(_result(
            rule_key="MISSING_TOLERANCE_SPECIFICATION",
            severity="CRITICAL",
            title="Critical dimension lacks tolerance guidance",
            what=f"{name} has no production tolerance guidance.",
            why="Manufacturing and inspection cannot determine acceptable variation for a production-critical dimension.",
            affected_entities=[name],
            affected_regions=[_region(item, "Mounting-hole layout")],
            action="Add tolerance specification before manufacturing approval.",
            evidence=item,
        ))

    for item in _profile_items(design_data, "missing_hole_callouts"):
        name = item.get("name") or item.get("hole") or "Mounting hole"
        results.append(_result(
            rule_key="MISSING_HOLE_CALLOUT",
            severity="CRITICAL",
            title="Mounting hole definition is incomplete",
            what=f"{name} lacks complete diameter, thread, or callout definition.",
            why="The assembly interface may be fabricated incorrectly if the mounting feature is not fully specified.",
            affected_entities=[name],
            affected_regions=[_region(item, "Mounting-hole layout")],
            action="Complete the hole callout with diameter/thread and quantity before approval.",
            evidence=item,
        ))

    section_geometry = _as_list(design_data.get("section_geometry"))
    for item in _profile_items(design_data, "missing_section_references"):
        name = item.get("name") or "Section geometry"
        results.append(_result(
            rule_key="MISSING_SECTION_REFERENCE",
            severity="CRITICAL",
            title="Section geometry lacks section reference",
            what=f"{name} is present without a clear section label or reference.",
            why="Fabrication details such as profile and thickness must remain explicit for manufacturing interpretation.",
            affected_entities=[name],
            affected_regions=[_region(item, "Section view")],
            action="Add or correct the section reference before release.",
            evidence=item,
        ))
    if section_geometry and not _has_annotation(design_data, "section_labels") and not _profile_items(design_data, "missing_section_references"):
        results.append(_result(
            rule_key="MISSING_SECTION_REFERENCE",
            severity="CRITICAL",
            title="Section view annotation is missing",
            what="Section-view geometry exists without a corresponding section label.",
            why="The drawing does not clearly connect section geometry to the parent view.",
            affected_entities=["Section geometry"],
            affected_regions=["Section view"],
            action="Add the section callout and section-view label.",
            evidence={"section_geometry_count": len(section_geometry)},
        ))

    for item in _profile_items(design_data, "incomplete_dimension_chains"):
        name = item.get("name") or item.get("chain") or "Dimension chain"
        results.append(_result(
            rule_key="INCOMPLETE_DIMENSION_CHAIN",
            severity="MAJOR",
            title="Dimension chain is incomplete",
            what=f"{name} cannot be fully traced from available datum or inspection references.",
            why="Inspection teams may not be able to validate feature position repeatably.",
            affected_entities=[name],
            affected_regions=[_region(item, "Feature position layout")],
            action="Complete the dimensional chain or define datum-based inspection references.",
            evidence=item,
        ))

    for item in _profile_items(design_data, "incomplete_weld_notes"):
        name = item.get("name") or "Weld location"
        results.append(_result(
            rule_key="INCOMPLETE_WELD_NOTE",
            severity="MAJOR",
            title="Weld note is incomplete",
            what=f"{name} lacks fabrication guidance.",
            why="Weld location or process ambiguity can produce inconsistent bracket strength and access constraints.",
            affected_entities=[name],
            affected_regions=[_region(item, "Weld access area")],
            action="Add weld size, location, process, or symbol guidance.",
            evidence=item,
        ))

    title_block = (design_data.get("title_block") or {}) if isinstance(design_data.get("title_block"), dict) else {}
    missing_title_fields = _profile_items(design_data, "title_block_missing")
    if not missing_title_fields:
        for field in ("drawing_number", "revision", "material", "scale"):
            if title_block and not title_block.get(field):
                missing_title_fields.append({"name": field, "region": "Title block"})
    if missing_title_fields:
        names = [item.get("name") or item.get("field") or str(item) for item in missing_title_fields]
        results.append(_result(
            rule_key="TITLE_BLOCK_INCOMPLETE",
            severity="MAJOR",
            title="Title block metadata is incomplete",
            what=f"Missing title block field(s): {', '.join(names)}.",
            why="Revision, material, scale, and drawing metadata are required for document traceability.",
            affected_entities=names,
            affected_regions=["Title block"],
            action="Complete title block metadata before review signoff.",
            evidence={"missing_fields": names},
        ))

    if _profile_items(design_data, "missing_thickness_callouts") or (
        design_data.get("process") and "bend" in str(design_data.get("process")).lower() and not _has_annotation(design_data, "thickness_annotations")
    ):
        items = _profile_items(design_data, "missing_thickness_callouts") or [{"name": "Sheet thickness", "region": "Section view"}]
        results.append(_result(
            rule_key="MISSING_THICKNESS_CALLOUT",
            severity="MAJOR",
            title="Sheet thickness callout is missing",
            what="Sheet-metal thickness is not explicitly specified for fabrication confirmation.",
            why="Material thickness controls bend allowance, stiffness, and inspection readiness.",
            affected_entities=[item.get("name", "Sheet thickness") for item in items],
            affected_regions=[_region(item, "Section view") for item in items],
            action="Add the sheet thickness callout and link it to material/process notes.",
            evidence=items,
        ))

    minor_profiles = [
        ("annotation_alignment_inconsistencies", "ANNOTATION_ALIGNMENT_INCONSISTENCY", "Annotation alignment inconsistency", "Annotation placement or leader alignment is inconsistent.", "Drawing clarity is reduced and shop-floor interpretation can slow down.", "Align annotations and leaders consistently."),
        ("duplicate_dimension_references", "DUPLICATE_DIMENSION_REFERENCE", "Duplicate dimension reference", "A dimension appears to be repeated or ambiguously referenced.", "Duplicate dimensions can create conflicting inspection interpretation after revision changes.", "Remove duplicate references or mark one as reference-only."),
        ("inconsistent_note_formatting", "INCONSISTENT_NOTE_FORMATTING", "Inconsistent note formatting", "Drawing notes use inconsistent wording or formatting.", "Reviewers and fabricators rely on consistent note formats to distinguish requirements from comments.", "Normalize note formatting."),
        ("view_label_inconsistencies", "VIEW_LABEL_INCONSISTENCY", "View label inconsistency", "View labels are missing or inconsistent.", "Drawing navigation and cross-reference clarity are reduced.", "Correct view labels and cross-references."),
    ]
    for profile_key, rule_key, title, what, why, action in minor_profiles:
        for item in _profile_items(design_data, profile_key):
            name = item.get("name") or item.get("feature") or title
            results.append(_result(
                rule_key=rule_key,
                severity="MINOR",
                title=title,
                what=f"{what} Affected item: {name}.",
                why=why,
                affected_entities=[name],
                affected_regions=[_region(item, "Drawing notes")],
                action=action,
                evidence=item,
            ))

    for item in _profile_items(design_data, "feature_outside_reference_envelope"):
        name = item.get("name") or "Unknown feature"
        results.append(_result(
            rule_key="FEATURE_OUTSIDE_REFERENCE_ENVELOPE",
            severity="CRITICAL",
            title="Feature absent from approved reference baseline",
            what=f"{name} is present in this revision but absent from the approved reference drawing.",
            why="Manufacturing cannot release a part with geometry not validated in the approved reference. An Engineering Change Notice (ECN) is required before this feature can be produced.",
            affected_entities=[name],
            affected_regions=[_region(item, "Main view")],
            action="Raise an ECN and obtain design authority sign-off before release.",
            evidence=item,
        ))

    for item in _profile_items(design_data, "mixed_fastener_sizes"):
        name = item.get("name") or "Mounting holes"
        results.append(_result(
            rule_key="MIXED_FASTENER_SIZES",
            severity="MAJOR",
            title="Mixed fastener/hole sizes flagged",
            what=f"{name}: different hole diameters imply different fastener standards.",
            why="Asymmetric mounting interfaces increase assembly error risk. Assembly BOM must confirm each fastener size is intentional and correctly specified.",
            affected_entities=[name],
            affected_regions=[_region(item, "Mounting-hole layout")],
            action="Confirm against assembly BOM that different fastener sizes are intentional and fully specified.",
            evidence=item,
        ))

    # Bend radius adequacy: inside radius < 1×t is a BLOCK for CRCA IS 513
    _thickness_mm: Optional[float] = None
    _tb = design_data.get("title_block")
    if isinstance(_tb, dict):
        _thk_str = _tb.get("thickness") or design_data.get("thickness")
    else:
        _thk_str = design_data.get("thickness")
    if _thk_str:
        try:
            _thickness_mm = float(str(_thk_str).replace("mm", "").replace("MM", "").strip())
        except (ValueError, TypeError):
            pass
    for _bend in _as_list(design_data.get("bend_features")):
        if not isinstance(_bend, dict):
            continue
        _radius = _bend.get("bend_radius")
        if _radius is not None and _thickness_mm is not None:
            try:
                if float(_radius) < float(_thickness_mm):
                    results.append(_result(
                        rule_key="BEND_RADIUS_BELOW_MINIMUM",
                        severity="CRITICAL",
                        title="Bend radius below 1×t minimum for CRCA",
                        what=(
                            f"{_bend.get('name', 'Bend feature')}: inside radius {_radius} mm is below "
                            f"the 1×t minimum of {_thickness_mm} mm for CRCA IS 513 Grade D."
                        ),
                        why="Inside bend radius below 1×t causes cracking and delamination in CRCA sheet metal. Incoming QC will reject the part.",
                        affected_entities=[_bend.get("name", "Bend feature")],
                        affected_regions=[_region(_bend, "Section A-A")],
                        action=f"Increase inside bend radius to ≥{_thickness_mm} mm per CRCA IS 513 Grade D specification.",
                        evidence={"bend_radius": _radius, "material_thickness": _thickness_mm, "minimum_radius": _thickness_mm},
                    ))
            except (TypeError, ValueError):
                pass

    execute_query("DELETE FROM drawing_validation_results WHERE design_revision_id = %s::uuid", (design_revision_id,))
    for result in results:
        execute_query("""
            INSERT INTO drawing_validation_results (
                design_revision_id, rule_key, severity, status, title, what_is_wrong,
                why_it_matters, affected_entities, affected_regions, recommended_action, evidence_json
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            design_revision_id,
            result["rule_key"],
            result["severity"],
            result["status"],
            result["title"],
            result["what_is_wrong"],
            result["why_it_matters"],
            Json(result["affected_entities"]),
            Json(result["affected_regions"]),
            result["recommended_action"],
            Json(result["evidence_json"]),
        ))

    return results


def update_reference_baseline_and_pairs(design_revision_id: str, artifact_id: str, design_data: dict) -> None:
    title_block = design_data.get("title_block") or {}
    is_reference = (
        design_data.get("approval_status") == "APPROVED_REFERENCE"
        or design_data.get("reference_baseline") is True
        or title_block.get("approval_status") in {"RELEASED", "APPROVED_REFERENCE"}
    )

    if is_reference:
        fetch_one("""
            INSERT INTO drawing_reference_baselines (
                artifact_id, design_revision_id, baseline_name, approval_status, baseline_metadata_json
            )
            VALUES (%s::uuid, %s::uuid, %s, 'APPROVED_REFERENCE', %s)
            ON CONFLICT (artifact_id, design_revision_id)
            DO UPDATE SET baseline_metadata_json = EXCLUDED.baseline_metadata_json
            RETURNING id
        """, (
            artifact_id,
            design_revision_id,
            title_block.get("drawing_number") or "Golden Reference Drawing",
            Json({
                "drawing_number": title_block.get("drawing_number"),
                "revision": title_block.get("revision"),
                "material": title_block.get("material") or design_data.get("material"),
                "thickness": title_block.get("thickness") or design_data.get("thickness"),
                "process": title_block.get("process") or design_data.get("process"),
            }),
        ))
        return

    baseline = fetch_one("""
        SELECT design_revision_id
        FROM drawing_reference_baselines
        WHERE artifact_id = %s::uuid
        ORDER BY created_at DESC
        LIMIT 1
    """, (artifact_id,))
    if not baseline:
        return

    baseline_data = fetch_one("SELECT design_data_json FROM design_revisions WHERE id = %s::uuid", (baseline["design_revision_id"],))
    comparison = compare_to_baseline(baseline_data.get("design_data_json") if baseline_data else {}, design_data)
    fetch_one("""
        INSERT INTO drawing_revision_pairs (
            artifact_id, baseline_revision_id, compared_revision_id, comparison_type, comparison_summary_json
        )
        VALUES (%s::uuid, %s::uuid, %s::uuid, 'REFERENCE_COMPARISON', %s)
        ON CONFLICT (baseline_revision_id, compared_revision_id)
        DO UPDATE SET comparison_summary_json = EXCLUDED.comparison_summary_json
        RETURNING id
    """, (
        artifact_id,
        baseline["design_revision_id"],
        design_revision_id,
        Json(comparison),
    ))


def compare_to_baseline(baseline_data: dict, compared_data: dict) -> dict:
    baseline_entities = {item["entity_key"]: item for item in iter_drawing_entities(baseline_data or {})}
    compared_entities = {item["entity_key"]: item for item in iter_drawing_entities(compared_data or {})}
    missing = sorted(set(baseline_entities) - set(compared_entities))
    added = sorted(set(compared_entities) - set(baseline_entities))
    common = sorted(set(baseline_entities) & set(compared_entities))
    changed = [
        key for key in common
        if baseline_entities[key].get("geometry_json") != compared_entities[key].get("geometry_json")
    ]
    return {
        "baseline_entity_count": len(baseline_entities),
        "compared_entity_count": len(compared_entities),
        "missing_reference_entities": missing,
        "added_entities": added,
        "changed_entities": changed,
        "summary": f"{len(changed)} changed, {len(missing)} missing from approved reference, {len(added)} added.",
    }


def build_drawing_review_summary(design_revision_id: str) -> dict:
    counts = fetch_one("""
        SELECT
            (SELECT COUNT(*) FROM drawing_feature_entities WHERE design_revision_id = %s::uuid) as entity_count,
            (SELECT COUNT(*) FROM drawing_dimensions WHERE design_revision_id = %s::uuid) as dimension_count,
            (SELECT COUNT(*) FROM drawing_annotations WHERE design_revision_id = %s::uuid) as annotation_count,
            (SELECT COUNT(*) FROM drawing_validation_results WHERE design_revision_id = %s::uuid AND status = 'BLOCK') as critical_count,
            (SELECT COUNT(*) FROM drawing_validation_results WHERE design_revision_id = %s::uuid AND status = 'WARN') as warning_count
    """, (design_revision_id, design_revision_id, design_revision_id, design_revision_id, design_revision_id))
    pair = fetch_one("""
        SELECT comparison_summary_json
        FROM drawing_revision_pairs
        WHERE compared_revision_id = %s::uuid
        ORDER BY created_at DESC
        LIMIT 1
    """, (design_revision_id,))
    return {
        **(counts or {}),
        "reference_comparison": pair.get("comparison_summary_json") if pair else None,
    }


def get_mock_bracket_variants() -> list[dict]:
    common = {
        "artifact_number": "HORN-HSG-2705",
        "title": "Sheet Metal Mounting Bracket Family",
        "artifact_type": "ENGINEERING_DRAWING",
        "domain": "MECHANICAL",
        "linked_part_number": "HORN-HSG-2705",
        "material": "CRCA Sheet Metal 1.5 mm",
        "supplier": "Demo Fabrication Supplier",
    }
    return [
        {
            "artifact": common,
            "revision": {
                "revision_code": "R3",
                "revision_sequence": 3,
                "change_summary": "Approved manufacturing release — slot feature added, hole positions corrected to datum, flange offset revised to 42.1 mm.",
                "source_filename": "Part 3 design.pdf",
                "design_data_json": _variant_three_data(),
                "changed_by": "drawing-checker",
            },
        },
        {
            "artifact": common,
            "revision": {
                "revision_code": "R1",
                "revision_sequence": 1,
                "change_summary": "Initial draft — lower feature position underconstrained, datum chain incomplete, thickness callout missing from section view.",
                "source_filename": "Part 1 design.pdf",
                "design_data_json": _variant_one_data(),
                "changed_by": "drawing-checker",
            },
        },
        {
            "artifact": common,
            "revision": {
                "revision_code": "R2",
                "revision_sequence": 2,
                "change_summary": "Centre cutout Ø18.1 added, lower ref 31.5 added — but hole callouts, section reference, and critical tolerances dropped.",
                "source_filename": "Part 2 design.pdf",
                "design_data_json": _variant_two_data(),
                "changed_by": "drawing-checker",
            },
        },
    ]


# ── Common bracket geometry shared across revisions ──────────────────────────

def _base_bracket_entities() -> dict:
    """Features and annotations common to all three bracket revisions."""
    return {
        "process": "Laser Cut + Bend",
        "material_spec": "CRCA IS 513 Grade D",
        "geometric_entities": [
            {"id": "OUTER_PROFILE", "name": "Bracket outer profile", "region": "Main view", "entity": "sheet_metal_profile"},
            {"id": "SIDE_CUT",      "name": "Side cut feature",       "region": "Right side profile", "entity": "cutout"},
        ],
        # Holes differ per revision — populated in variant functions
        "mounting_holes": [],
        "flanges": [
            {"id": "FLANGE-A", "name": "Primary bend flange", "region": "Section A-A"},
        ],
        "bend_features": [
            # 1.5 mm CRCA: min inside bend radius ≥ 1.5 mm (1×t rule)
            # 2.5 mm radius specified here satisfies ISO/standard tooling
            {"id": "BEND-1", "name": "90 degree bend", "region": "Section A-A",
             "bend_angle": 90, "bend_radius": 2.5, "k_factor": 0.33},
        ],
        "section_geometry": [
            {"id": "SEC-AA-GEOM", "name": "Section A-A profile", "region": "Section A-A"},
        ],
        "section_labels": [
            {"id": "SEC-AA", "text": "SECTION A-A", "region": "Section A-A"},
        ],
        "material_notes": [
            {"id": "MAT-CRCA", "text": "MATERIAL: CRCA IS 513 GR.D  THK 1.5 mm", "region": "Title block"},
        ],
        "drawing_notes": [
            {"id": "NOTE-GEN",  "text": "GENERAL TOLERANCE: ISO 2768-m UNLESS OTHERWISE STATED.", "region": "Notes"},
            {"id": "NOTE-BEND", "text": "BREAK SHARP EDGES AND DEBURR AFTER LASER CUTTING.", "region": "Notes"},
            {"id": "NOTE-SURF", "text": "SURFACE FINISH: Ra 3.2 μm UNLESS SPECIFIED.", "region": "Notes"},
        ],
    }


# ── R3 — Approved Reference (Part 3 extracted values) ────────────────────────
# Extracted dimensions: 77.5, 38.3, 31.5, 152.1, 101.9, 78.9, 42.1, 22.1, Ø13, Ø12

def _variant_three_data() -> dict:
    data = _base_bracket_entities()
    data.update({
        "approval_status": "APPROVED_REFERENCE",
        "reference_baseline": True,
        "prt_filename": "Part 3 design.prt",
        "title_block": {
            "drawing_number": "HORN-HSG-2705",
            "revision": "R3",
            "material": "CRCA IS 513 GR.D",
            "thickness": "1.5 mm",
            "process": "Laser Cut + Bend",
            "scale": "1:1",
            "tolerance_standard": "ISO 2768-m",
            "approval_status": "RELEASED",
            "surface_finish": "Ra 3.2",
        },
        "revision_metadata": {"revision": "R3", "released_by": "Senior Reviewer", "status": "RELEASED"},
        "mounting_holes": [
            {"id": "MH-L", "name": "Left mounting hole",  "region": "Mounting-hole layout",
             "diameter": 13.0, "callout": "Ø13 THRU", "fit_class": "H11", "quantity": 1},
            {"id": "MH-R", "name": "Right mounting hole", "region": "Mounting-hole layout",
             "diameter": 12.0, "callout": "Ø12 THRU", "fit_class": "H11", "quantity": 1},
        ],
        "cutouts": [
            {"id": "SLOT-1", "name": "Slot feature", "region": "Lower feature layout",
             "feature_type": "slot", "width": 22.1, "length": 31.5},
        ],
        "hole_callouts": [
            {"id": "HC-L13",  "text": "Ø13 THRU",  "region": "Mounting-hole layout", "entity_key": "MOUNTING_HOLE:mh-l"},
            {"id": "HC-R12",  "text": "Ø12 THRU",  "region": "Mounting-hole layout", "entity_key": "MOUNTING_HOLE:mh-r"},
            {"id": "HC-SLOT", "text": "SLOT 22.1 × 31.5", "region": "Lower feature layout"},
        ],
        "thickness_annotations": [
            {"id": "THK-15", "text": "THK 1.5 mm", "region": "Section A-A"},
        ],
        "dimensions": [
            # Overall envelope — ISO 2768-m general tolerance applies (±0.3 for 30–120 mm, ±0.5 for 120–400 mm)
            {"id": "D-OVERALL-H",   "name": "Overall height",              "nominal": 152.1, "unit": "mm",
             "tolerance": {"plus": 0.50, "minus": 0.50}, "region": "Main view"},
            {"id": "D-OVERALL-W",   "name": "Overall width",               "nominal": 77.5,  "unit": "mm",
             "tolerance": {"plus": 0.30, "minus": 0.30}, "region": "Main view"},
            {"id": "D-BODY-H",      "name": "Body height",                 "nominal": 101.9, "unit": "mm",
             "tolerance": {"plus": 0.30, "minus": 0.30}, "region": "Main view"},
            # Critical hole positions — tighter tolerance for assembly fitment
            {"id": "D-HOLE-HPOS",   "name": "Hole horizontal position",    "nominal": 38.3,  "unit": "mm",
             "critical": True, "tolerance": {"plus": 0.10, "minus": 0.10}, "region": "Mounting-hole layout"},
            {"id": "D-LOWER-REF",   "name": "Lower feature reference",     "nominal": 31.5,  "unit": "mm",
             "critical": True, "tolerance": {"plus": 0.10, "minus": 0.10}, "region": "Lower feature layout"},
            {"id": "D-UPPER-REF",   "name": "Upper horizontal reference",  "nominal": 78.9,  "unit": "mm",
             "tolerance": {"plus": 0.20, "minus": 0.20}, "region": "Upper feature layout"},
            {"id": "D-FLANGE-OFF",  "name": "Flange vertical offset",      "nominal": 42.1,  "unit": "mm",
             "tolerance": {"plus": 0.20, "minus": 0.20}, "region": "Section A-A"},
            {"id": "D-SLOT-W",      "name": "Slot width",                  "nominal": 22.1,  "unit": "mm",
             "critical": True, "tolerance": {"plus": 0.05, "minus": 0.00}, "region": "Lower feature layout"},
            # Critical hole diameters — unilateral H11 fit (+0.11/0.00 for Ø13, +0.11/0.00 for Ø12)
            {"id": "D-MHL-DIA",     "name": "Left hole diameter (Ø13)",    "nominal": 13.0,  "unit": "mm",
             "critical": True, "tolerance": {"plus": 0.11, "minus": 0.00}, "region": "Mounting-hole layout"},
            {"id": "D-MHR-DIA",     "name": "Right hole diameter (Ø12)",   "nominal": 12.0,  "unit": "mm",
             "critical": True, "tolerance": {"plus": 0.11, "minus": 0.00}, "region": "Mounting-hole layout"},
        ],
        "validation_profile": {},
    })
    return data


# ── R1 — Initial Draft (Part 1 extracted values) ─────────────────────────────
# Extracted dimensions: 77.5, 51.4, 152.1, 101.9, 56.6, 86.9, 33, Ø13, Ø12, THK 1.5
# Missing vs reference: lower ref (31.5), slot (22.1), hole pos (51.4 vs 38.3 ref), flange (86.9 vs 42.1 ref)

def _variant_one_data() -> dict:
    data = _base_bracket_entities()
    data["prt_filename"] = "Part 1 design.prt"
    data["title_block"] = {
        "drawing_number": "HORN-HSG-2705",
        "revision": "R1",
        "material": "CRCA IS 513 GR.D",
        "thickness": "1.5 mm",
        "process": "Laser Cut + Bend",
        "scale": "1:1",
        "approval_status": "REVIEW_REQUIRED",
    }
    data["mounting_holes"] = [
        {"id": "MH-L", "name": "Left mounting hole",  "region": "Mounting-hole layout",
         "diameter": 13.0, "callout": "Ø13 THRU", "quantity": 1},
        {"id": "MH-R", "name": "Right mounting hole", "region": "Mounting-hole layout",
         "diameter": 12.0, "callout": "Ø12 THRU", "quantity": 1},
    ]
    data["hole_callouts"] = [
        {"id": "HC-L13", "text": "Ø13 THRU", "region": "Mounting-hole layout"},
        {"id": "HC-R12", "text": "Ø12 THRU", "region": "Mounting-hole layout"},
    ]
    data["thickness_annotations"] = [
        {"id": "THK-15", "text": "THK 1.5 mm", "region": "Section A-A"},
    ]
    data["dimensions"] = [
        {"id": "D-OVERALL-H",  "name": "Overall height",             "nominal": 152.1, "unit": "mm",
         "tolerance": {"plus": 0.50, "minus": 0.50}, "region": "Main view"},
        {"id": "D-OVERALL-W",  "name": "Overall width",              "nominal": 77.5,  "unit": "mm",
         "tolerance": {"plus": 0.30, "minus": 0.30}, "region": "Main view"},
        {"id": "D-BODY-H",     "name": "Body height",                "nominal": 101.9, "unit": "mm",
         "tolerance": {"plus": 0.30, "minus": 0.30}, "region": "Main view"},
        # Hole position: 51.4 (deviates from 38.3 in reference — undetected in R1)
        {"id": "D-HOLE-HPOS",  "name": "Hole horizontal position",   "nominal": 51.4,  "unit": "mm",
         "critical": True, "tolerance": {"plus": 0.10, "minus": 0.10}, "region": "Mounting-hole layout"},
        # Upper ref: 56.6 in R1 (changed to 78.9 in R2/R3 — transition dimension)
        {"id": "D-UPPER-REF",  "name": "Upper horizontal reference", "nominal": 56.6,  "unit": "mm",
         "tolerance": {"plus": 0.20, "minus": 0.20}, "region": "Upper feature layout"},
        # Flange offset: 86.9 in R1 (changed significantly to 42.1 in R3 reference)
        {"id": "D-FLANGE-OFF", "name": "Flange vertical offset",     "nominal": 86.9,  "unit": "mm",
         "tolerance": {"plus": 0.20, "minus": 0.20}, "region": "Section A-A"},
        {"id": "D-BOTTOM-OFF", "name": "Bottom offset",              "nominal": 33.0,  "unit": "mm",
         "tolerance": {"plus": 0.20, "minus": 0.20}, "region": "Main view"},
        {"id": "D-MHL-DIA",    "name": "Left hole diameter (Ø13)",   "nominal": 13.0,  "unit": "mm",
         "critical": True, "tolerance": {"plus": 0.11, "minus": 0.00}, "region": "Mounting-hole layout"},
        {"id": "D-MHR-DIA",    "name": "Right hole diameter (Ø12)",  "nominal": 12.0,  "unit": "mm",
         "critical": True, "tolerance": {"plus": 0.11, "minus": 0.00}, "region": "Mounting-hole layout"},
    ]
    data["validation_profile"] = {
        # Lower feature position (31.5 ref) is absent — dimension chain cannot be closed
        "incomplete_dimension_chains": [
            {"name": "Lower mounting feature position",
             "region": "Lower feature layout",
             "note": "Datum-B reference to lower feature edge absent. 31.5 mm offset needed to constrain lower feature for CMM inspection.",
             "missing_value": 31.5, "unit": "mm"},
        ],
        # Thickness exists in title block but not called out in Section A-A view body
        "missing_thickness_callouts": [
            {"name": "Section A-A thickness callout",
             "region": "Section A-A",
             "note": "1.5 mm sheet thickness confirmed in title block but not annotated on section view body; required for bend-allowance verification."},
        ],
        "annotation_alignment_inconsistencies": [
            {"name": "Lower feature leader note",
             "region": "Lower feature layout",
             "note": "Dimension leader for Ø12 hole crosses Ø13 leader line; ISO 128-22 alignment violated."},
        ],
        # Asymmetric hole diameters — needs BOM confirmation
        "mixed_fastener_sizes": [
            {"name": "Left Ø13 / Right Ø12 mounting holes",
             "region": "Mounting-hole layout",
             "note": "Two different hole diameters imply different fastener standards; confirm against assembly BOM."},
        ],
    }
    return data


# ── R2 — Blocked Draft (Part 2 extracted values) ─────────────────────────────
# Extracted dimensions: 77.5, 51.4, 31.5, 152.1, 101.9, 78.9, 86.9, 33, Ø13, Ø12, Ø18.1, THK 1.5
# Added vs R1: lower ref 31.5, upper ref updated to 78.9, centre cutout Ø18.1
# Dropped vs R1: hole callouts, section labels, critical tolerances

def _variant_two_data() -> dict:
    data = _base_bracket_entities()
    data["prt_filename"] = "Part 2 design.prt"
    data["title_block"] = {
        "drawing_number": "HORN-HSG-2705",
        "revision": "R2",
        "material": "CRCA IS 513 GR.D",
        "thickness": "1.5 mm",
        "approval_status": "BLOCKED",
        # scale field deliberately omitted — triggers TITLE_BLOCK_INCOMPLETE
    }
    data["mounting_holes"] = [
        {"id": "MH-L", "name": "Left mounting hole",  "region": "Mounting-hole layout", "diameter": 13.0},
        {"id": "MH-R", "name": "Right mounting hole", "region": "Mounting-hole layout", "diameter": 12.0},
    ]
    data["cutouts"] = [
        {"id": "CUTOUT-C", "name": "Centre cutout", "region": "Main view",
         "feature_type": "circular_cutout", "diameter": 18.1,
         "note": "Not present in R3 reference — requires design authority approval."},
    ]
    # Hole callouts intentionally absent → MISSING_HOLE_CALLOUT (BLOCK)
    data["hole_callouts"] = []
    # Section labels intentionally absent → MISSING_SECTION_REFERENCE (BLOCK)
    data["section_labels"] = []
    data["thickness_annotations"] = [
        {"id": "THK-15", "text": "THK 1.5 mm", "region": "Section A-A"},
    ]
    # Critical dimensions have nominal values but tolerance blocks stripped → MISSING_TOLERANCE_SPECIFICATION
    data["dimensions"] = [
        {"id": "D-OVERALL-H",  "name": "Overall height",             "nominal": 152.1, "unit": "mm",
         "tolerance": {"plus": 0.50, "minus": 0.50}, "region": "Main view"},
        {"id": "D-OVERALL-W",  "name": "Overall width",              "nominal": 77.5,  "unit": "mm",
         "tolerance": {"plus": 0.30, "minus": 0.30}, "region": "Main view"},
        {"id": "D-BODY-H",     "name": "Body height",                "nominal": 101.9, "unit": "mm",
         "tolerance": {"plus": 0.30, "minus": 0.30}, "region": "Main view"},
        # Hole position: still 51.4 (not yet corrected to 38.3 reference value)
        {"id": "D-HOLE-HPOS",  "name": "Hole horizontal position",   "nominal": 51.4,  "unit": "mm",
         "critical": True,   # tolerance block stripped — BLOCK finding
         "region": "Mounting-hole layout"},
        {"id": "D-LOWER-REF",  "name": "Lower feature reference",    "nominal": 31.5,  "unit": "mm",
         "critical": True,   # tolerance block stripped
         "region": "Lower feature layout"},
        {"id": "D-UPPER-REF",  "name": "Upper horizontal reference", "nominal": 78.9,  "unit": "mm",
         "tolerance": {"plus": 0.20, "minus": 0.20}, "region": "Upper feature layout"},
        {"id": "D-FLANGE-OFF", "name": "Flange vertical offset",     "nominal": 86.9,  "unit": "mm",
         "tolerance": {"plus": 0.20, "minus": 0.20}, "region": "Section A-A"},
        {"id": "D-BOTTOM-OFF", "name": "Bottom offset",              "nominal": 33.0,  "unit": "mm",
         "tolerance": {"plus": 0.20, "minus": 0.20}, "region": "Main view"},
        {"id": "D-CUTOUT-DIA", "name": "Centre cutout diameter",     "nominal": 18.1,  "unit": "mm",
         "critical": True,   # tolerance block stripped
         "region": "Main view"},
        {"id": "D-MHL-DIA",    "name": "Left hole diameter (Ø13)",   "nominal": 13.0,  "unit": "mm",
         "critical": True,   # tolerance block stripped
         "region": "Mounting-hole layout"},
        {"id": "D-MHR-DIA",    "name": "Right hole diameter (Ø12)",  "nominal": 12.0,  "unit": "mm",
         "critical": True,   # tolerance block stripped
         "region": "Mounting-hole layout"},
    ]
    data["validation_profile"] = {
        # Critical dimensions present but tolerances stripped
        "missing_tolerances": [
            {"name": "Hole horizontal position (Ø13/Ø12 mounting holes)",
             "region": "Mounting-hole layout",
             "nominal": 51.4, "unit": "mm",
             "note": "ISO 2768-m general tolerance (±0.10) required; positional callout absent."},
            {"name": "Lower feature reference",
             "region": "Lower feature layout",
             "nominal": 31.5, "unit": "mm",
             "note": "Bilateral tolerance band required for CMM datum B inspection."},
            {"name": "Centre cutout diameter (Ø18.1)",
             "region": "Main view",
             "nominal": 18.1, "unit": "mm",
             "note": "Diameter tolerance and positional callout both absent."},
        ],
        # Hole callouts dropped — fastener spec cannot be confirmed
        "missing_hole_callouts": [
            {"name": "Left mounting hole Ø13",
             "region": "Mounting-hole layout",
             "note": "Callout text 'Ø13 THRU' and fit class annotation absent."},
            {"name": "Right mounting hole Ø12",
             "region": "Mounting-hole layout",
             "note": "Callout text 'Ø12 THRU' and fit class annotation absent."},
        ],
        # Section labels dropped — Section A-A cannot be interpreted
        "missing_section_references": [
            {"name": "Section A-A profile",
             "region": "Section A-A",
             "note": "Section cut line and 'SECTION A-A' label absent; bend profile and thickness uninterpretable."},
        ],
        # Feature-to-datum chain broken (lower ref has no tolerance, upper ref 78.9 not linked to datum)
        "incomplete_dimension_chains": [
            {"name": "Feature-to-datum traceability (Main view)",
             "region": "Main view",
             "note": "Datum A (bottom edge), B (left edge) chain cannot be closed without positional tolerances on Ø13/Ø12 holes."},
        ],
        "view_label_inconsistencies": [
            {"name": "Section view label (Section A-A)",
             "region": "Section A-A",
             "note": "Section cut line annotation absent — view cannot be cross-referenced from main view."},
        ],
        # Centre cutout not in reference baseline — needs ECN
        "feature_outside_reference_envelope": [
            {"name": "Centre cutout Ø18.1",
             "region": "Main view",
             "note": "This feature is absent from the approved R3 reference. Requires Engineering Change Notice before release."},
        ],
        "mixed_fastener_sizes": [
            {"name": "Left Ø13 / Right Ø12 mounting holes",
             "region": "Mounting-hole layout",
             "note": "Asymmetric hole diameters; assembly BOM must confirm different fastener standards for each location."},
        ],
    }
    return data
