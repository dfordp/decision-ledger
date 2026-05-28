"""
Deterministic revision analysis engine.

Core validation pipeline:
1. Extract dimensions/tolerances from revision drawing data
2. Compare against approved baseline
3. Apply deterministic validation rules
4. Analyze engineering impact
5. Generate release recommendation

NO AI-generated confidence values.
NO fabricated findings.
Only deterministic rule evaluation and explicit extraction status.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from app.database import fetch_all, fetch_one, execute_query
from app.models import (
    ValidationContextState,
    RevisionValidationContext,
    EngineeringImpactAnalysis,
    DimensionEvaluation,
    RevisionAnalysisSummary,
)


# ============================================================================
# CRITICALITY & ENGINEERING IMPACT RULES
# ============================================================================

CRITICAL_DIMENSIONS = {
    "hole_horizontal_position", "hole_vertical_position", "hole_diameter",
    "mounting_hole_position", "mounting_hole_diameter",
    "slot_width", "slot_depth", "slot_position",
    "flange_width", "flange_height", "flange_thickness",
    "assembly_interface_dimension", "mating_surface_position",
    "cutout_dimension", "pocket_depth",
}

ASSEMBLY_INTERFACE_KEYWORDS = {
    "hole", "mount", "mounting", "interface", "mating", "connector", 
    "alignment", "position", "coupling"
}

MANUFACTURING_CRITICAL_KEYWORDS = {
    "thickness", "width", "depth", "diameter", "radius", "length",
    "tolerance", "manufacturing", "process", "envelope"
}

INSPECTION_CRITICAL_KEYWORDS = {
    "position", "alignment", "perpendicular", "parallel", "tolerance",
    "datum", "reference", "fixture", "setup"
}


def _normalize_dimension_key(name: str) -> str:
    """Normalize dimension name for comparison"""
    return name.lower().replace(" ", "_").replace("-", "_")


def _classify_criticality(dimension_name: str, dimension_type: str = "DIMENSION") -> str:
    """Classify dimension as CRITICAL, HIGH, MEDIUM, or LOW"""
    norm_name = _normalize_dimension_key(dimension_name)
    name_lower = dimension_name.lower()
    
    # CRITICAL: mounting holes, assembly interfaces, key dimensions
    if any(keyword in norm_name for keyword in CRITICAL_DIMENSIONS):
        return "CRITICAL"
    if any(keyword in name_lower for keyword in ASSEMBLY_INTERFACE_KEYWORDS):
        if "hole" in norm_name or "position" in norm_name or "diameter" in norm_name:
            return "CRITICAL"
    
    # HIGH: tolerances, key manufacturing/inspection dimensions
    if "tolerance" in norm_name or dimension_type == "TOLERANCE":
        return "HIGH"
    if any(keyword in norm_name for keyword in MANUFACTURING_CRITICAL_KEYWORDS):
        return "HIGH"
    if any(keyword in norm_name for keyword in INSPECTION_CRITICAL_KEYWORDS):
        return "HIGH"
    
    # MEDIUM: features, materials, general specifications
    if dimension_type in {"MATERIAL", "COATING", "FEATURE", "FASTENER"}:
        return "MEDIUM"
    
    # LOW: annotations, informational content
    return "LOW"


def _analyze_engineering_impact(
    dimension_name: str,
    criticality: str,
    change_type: str,
    baseline_exists: bool,
    current_exists: bool,
) -> EngineeringImpactAnalysis:
    """
    Determine engineering impact classification for a dimension.
    
    Flags indicate whether this change affects that specific domain.
    """
    norm_name = _normalize_dimension_key(dimension_name)
    name_lower = dimension_name.lower()
    
    # Assembly alignment affected if: hole positions, mounting dims, interface dims change/remove
    assembly_alignment = any(keyword in norm_name for keyword in {
        "hole", "mount", "interface", "alignment", "position"
    }) and change_type in {"REMOVED", "MODIFIED", "ADDED"}
    
    # Inspection fixture dependency if: datum refs, position dims, alignment dims
    inspection_fixture_dependency = any(keyword in norm_name for keyword in {
        "position", "alignment", "datum", "reference"
    }) and (not current_exists or change_type in {"REMOVED", "MODIFIED"})
    
    # Mating geometry dependency if: hole dims, slot dims, interface dims
    mating_geometry_dependency = any(keyword in norm_name for keyword in {
        "hole", "slot", "cutout", "flange", "mating", "connector"
    }) and change_type in {"REMOVED", "MODIFIED"}
    
    # Tolerance stack if: tolerance removed or loosened
    tolerance_stack_dependency = (
        "tolerance" in norm_name and change_type in {"REMOVED", "TOLERANCE_LOOSENED"}
    )
    
    # Manufacturing process if: key manufacturing dims changed
    manufacturing_process_dependency = any(keyword in norm_name for keyword in {
        "thickness", "width", "depth", "radius", "diameter", "envelope"
    }) and change_type in {"REMOVED", "MODIFIED", "TOLERANCE_LOOSENED"}
    
    # Safety critical if marked or contains safety keywords
    safety_critical = criticality == "CRITICAL" and any(keyword in name_lower for keyword in {
        "safety", "brake", "critical", "airbag", "load-bearing"
    })
    
    # Build impact summary
    impacts = []
    if assembly_alignment:
        impacts.append("assembly alignment")
    if inspection_fixture_dependency:
        impacts.append("inspection fixture setup")
    if mating_geometry_dependency:
        impacts.append("mating geometry")
    if tolerance_stack_dependency:
        impacts.append("tolerance stack")
    if manufacturing_process_dependency:
        impacts.append("manufacturing process")
    if safety_critical:
        impacts.append("SAFETY CRITICAL")
    
    impact_summary = ", ".join(impacts) if impacts else "no significant engineering impact"
    
    return EngineeringImpactAnalysis(
        assembly_alignment=assembly_alignment,
        inspection_fixture_dependency=inspection_fixture_dependency,
        mating_geometry_dependency=mating_geometry_dependency,
        tolerance_stack_dependency=tolerance_stack_dependency,
        manufacturing_process_dependency=manufacturing_process_dependency,
        safety_critical=safety_critical,
        impact_summary=impact_summary,
    )


# ============================================================================
# DELTA CLASSIFICATION
# ============================================================================

def _classify_delta(
    baseline_value: Optional[Any],
    current_value: Optional[Any],
    tolerance_baseline: Optional[Any],
    tolerance_current: Optional[Any],
) -> Tuple[str, Optional[float]]:
    """
    Classify how a dimension changed between revisions.
    
    Returns: (change_type, delta_percent)
    
    change_type: IDENTICAL | ADDED | REMOVED | MODIFIED | TOLERANCE_LOOSENED | TOLERANCE_TIGHTENED
    delta_percent: percentage change if numeric, None otherwise
    """
    # Both missing -> IDENTICAL
    if baseline_value is None and current_value is None:
        return "IDENTICAL", None
    
    # Baseline exists, current missing -> REMOVED
    if baseline_value is not None and current_value is None:
        return "REMOVED", None
    
    # Baseline missing, current exists -> ADDED
    if baseline_value is None and current_value is not None:
        return "ADDED", None
    
    # Both exist, compare values
    if baseline_value == current_value:
        # Values identical, check tolerances
        if tolerance_baseline is None and tolerance_current is None:
            return "IDENTICAL", None
        if tolerance_baseline is not None and tolerance_current is None:
            return "TOLERANCE_REMOVED", None
        if tolerance_baseline is None and tolerance_current is not None:
            return "TOLERANCE_ADDED", None
        if tolerance_baseline != tolerance_current:
            # Try to determine if loosened or tightened
            try:
                base_range = _extract_tolerance_range(tolerance_baseline)
                curr_range = _extract_tolerance_range(tolerance_current)
                if base_range and curr_range:
                    if curr_range > base_range:
                        return "TOLERANCE_LOOSENED", 0.0
                    elif curr_range < base_range:
                        return "TOLERANCE_TIGHTENED", 0.0
            except:
                pass
            return "TOLERANCE_MODIFIED", None
        return "IDENTICAL", None
    
    # Values differ -> MODIFIED
    # Try to compute delta percentage
    delta_pct = None
    try:
        base_num = float(str(baseline_value).strip())
        curr_num = float(str(current_value).strip())
        if base_num != 0:
            delta_pct = ((curr_num - base_num) / abs(base_num)) * 100
    except (ValueError, TypeError):
        pass
    
    return "MODIFIED", delta_pct


def _extract_tolerance_range(tolerance_str: Optional[str]) -> Optional[float]:
    """
    Extract numeric range from tolerance string.
    
    Examples:
    "±0.1" -> 0.2
    "0.1 to 0.2" -> 0.1
    "+0.05/-0.05" -> 0.1
    """
    if not tolerance_str:
        return None
    
    tol_str = str(tolerance_str).strip()
    
    # Handle "±X" format
    if "±" in tol_str:
        try:
            parts = tol_str.replace("±", "").strip().split()
            if parts:
                val = float(parts[0])
                return val * 2  # ±X means range of 2X
        except:
            pass
    
    # Handle "+X/-Y" format
    if "+" in tol_str and "-" in tol_str:
        try:
            plus_part = tol_str.split("+")[1].split("/")[0].strip()
            minus_part = tol_str.split("-")[1].strip()
            plus_val = float(plus_part)
            minus_val = float(minus_part)
            return plus_val + minus_val
        except:
            pass
    
    # Try generic numeric extraction
    try:
        # Extract first number found
        import re
        matches = re.findall(r"[-+]?\d*\.?\d+", tol_str)
        if matches:
            if len(matches) >= 2:
                return abs(float(matches[0]) - float(matches[1]))
            return abs(float(matches[0]))
    except:
        pass
    
    return None


# ============================================================================
# DIMENSION EXTRACTION & BASELINE RETRIEVAL
# ============================================================================

def extract_dimensions_from_revision(revision_id: str) -> Dict[str, Dict[str, Any]]:
    """
    Extract all dimensions/tolerances from a revision's drawing data.
    
    Returns: {dimension_id: {name, value, tolerance, type, extracted_region, ...}}
    """
    revision = fetch_one("""
        SELECT new_specs_json FROM part_revisions WHERE id = %s::uuid
    """, (revision_id,))
    
    if not revision or not revision.get("new_specs_json"):
        return {}
    
    specs = revision.get("new_specs_json") or {}
    dimensions: Dict[str, Dict[str, Any]] = {}
    
    # Extract from dimensions section
    if "dimensions" in specs:
        dims = specs["dimensions"]
        if isinstance(dims, list):
            for idx, dim in enumerate(dims):
                if isinstance(dim, dict):
                    dim_id = dim.get("id") or dim.get("name") or f"dim_{idx}"
                    dimensions[dim_id] = {
                        "name": dim.get("name") or f"Dimension {idx}",
                        "value": dim.get("value"),
                        "tolerance": dim.get("tolerance"),
                        "unit": dim.get("unit"),
                        "type": "DIMENSION",
                        "extracted_region": dim.get("region") or dim.get("sheet") or "Sheet 1",
                    }
    
    # Extract from tolerances section
    if "tolerances" in specs:
        tols = specs["tolerances"]
        if isinstance(tols, list):
            for idx, tol in enumerate(tols):
                if isinstance(tol, dict):
                    tol_id = tol.get("id") or tol.get("name") or f"tol_{idx}"
                    if tol_id not in dimensions:
                        dimensions[tol_id] = {
                            "name": tol.get("name") or f"Tolerance {idx}",
                            "value": None,
                            "tolerance": tol.get("tolerance"),
                            "type": "TOLERANCE",
                            "extracted_region": tol.get("region") or "Sheet 1",
                        }
    
    # Extract from GD&T section
    if "gdt" in specs:
        gdts = specs["gdt"]
        if isinstance(gdts, list):
            for idx, gdt in enumerate(gdts):
                if isinstance(gdt, dict):
                    gdt_id = gdt.get("id") or gdt.get("name") or f"gdt_{idx}"
                    dimensions[gdt_id] = {
                        "name": gdt.get("name") or f"GD&T {idx}",
                        "value": gdt.get("value"),
                        "tolerance": gdt.get("tolerance"),
                        "type": "GD_T",
                        "extracted_region": gdt.get("region") or "Sheet 1",
                    }
    
    # Extract from materials section
    if "materials" in specs:
        mats = specs["materials"]
        if isinstance(mats, list):
            for idx, mat in enumerate(mats):
                if isinstance(mat, dict):
                    mat_id = mat.get("id") or mat.get("name") or f"material_{idx}"
                    dimensions[mat_id] = {
                        "name": mat.get("name") or f"Material {idx}",
                        "value": mat.get("specification") or mat.get("name"),
                        "tolerance": None,
                        "type": "MATERIAL",
                        "extracted_region": mat.get("region") or "Sheet 1",
                    }
    
    return dimensions


def get_baseline_dimensions(part_id: str, baseline_revision_num: int) -> Dict[str, Dict[str, Any]]:
    """
    Get approved baseline dimensions for comparison.
    """
    revision = fetch_one("""
        SELECT id FROM part_revisions 
        WHERE part_id = %s::uuid AND revision_number = %s
        LIMIT 1
    """, (part_id, baseline_revision_num))
    
    if not revision:
        return {}
    
    return extract_dimensions_from_revision(str(revision["id"]))


# ============================================================================
# DIMENSION EVALUATION
# ============================================================================

DETERMINISTIC_RULES = {
    "CRITICAL_DIMENSION_REMOVED": {
        "triggers": lambda d: (
            d["baseline_exists"]
            and not d["current_exists"]
            and d["criticality"] == "CRITICAL"
        ),
        "severity": "BLOCK",
        "message": "Critical {name} removed from approved reference drawing.",
    },
    
    "CRITICAL_TOLERANCE_REMOVED": {
        "triggers": lambda d: (
            d["baseline_exists"]
            and d["tolerance_present_baseline"]
            and not d["tolerance_present_current"]
            and d["criticality"] in ["CRITICAL", "HIGH"]
        ),
        "severity": "BLOCK",
        "message": "Critical tolerance specification removed for {name}.",
    },
    
    "HIGH_IMPORTANCE_DIMENSION_REMOVED": {
        "triggers": lambda d: (
            d["baseline_exists"]
            and not d["current_exists"]
            and d["criticality"] in ["HIGH", "MEDIUM"]
        ),
        "severity": "WARN",
        "message": "Important dimension {name} removed from revision.",
    },
    
    "TOLERANCE_LOOSENED_CRITICAL": {
        "triggers": lambda d: (
            d["change_type"] == "TOLERANCE_LOOSENED"
            and d["criticality"] == "CRITICAL"
        ),
        "severity": "WARN",
        "message": "Tolerance for critical dimension {name} loosened.",
    },
    
    "MAJOR_DIMENSION_SHIFT": {
        "triggers": lambda d: (
            d["delta_percent"] is not None
            and abs(d["delta_percent"]) > 15
            and d["criticality"] in ["CRITICAL", "HIGH"]
        ),
        "severity": "WARN",
        "message": "Critical dimension {name} changed by {delta_pct:.1f}%.",
    },
    
    "ASSEMBLY_INTERFACE_INCOMPLETE": {
        "triggers": lambda d: (
            d["engineering_impact"]["assembly_alignment"]
            and d["change_type"] in ["REMOVED", "MODIFIED"]
        ),
        "severity": "WARN",
        "message": "Assembly interface dimension {name} modified — alignment validation needed.",
    },
    
    "INSPECTION_DATUM_REMOVED": {
        "triggers": lambda d: (
            d["engineering_impact"]["inspection_fixture_dependency"]
            and d["change_type"] == "REMOVED"
        ),
        "severity": "WARN",
        "message": "Inspection datum dimension {name} removed — fixture setup affected.",
    },
    
    "MATERIAL_SPECIFICATION_MISSING": {
        "triggers": lambda d: (
            "material" in _normalize_dimension_key(d["name"])
            and not d["current_exists"]
            and d["baseline_exists"]
        ),
        "severity": "WARN",
        "message": "Material specification {name} missing from revision.",
    },
    
    "FEATURE_REMOVED": {
        "triggers": lambda d: (
            d["change_type"] == "REMOVED"
            and d["criticality"] in ["HIGH", "MEDIUM"]
            and any(keyword in _normalize_dimension_key(d["name"]) for keyword in {
                "flange", "cutout", "slot", "pocket", "boss"
            })
        ),
        "severity": "WARN",
        "message": "Feature {name} removed from approved design.",
    },
}


def evaluate_dimension(
    dimension_id: str,
    dimension_name: str,
    baseline_exists: bool,
    current_exists: bool,
    baseline_value: Optional[Any],
    current_value: Optional[Any],
    baseline_tolerance: Optional[Any],
    current_tolerance: Optional[Any],
    criticality: str,
    dimension_type: str = "DIMENSION",
) -> DimensionEvaluation:
    """
    Run full deterministic evaluation for a single dimension.
    
    Evaluation pipeline:
    1. Classify delta (IDENTICAL, REMOVED, ADDED, MODIFIED, etc.)
    2. Classify engineering impact
    3. Apply deterministic rules
    4. Determine severity (SAFE, WARN, BLOCK)
    """
    # Step 1: Classify delta
    change_type, delta_percent = _classify_delta(
        baseline_value,
        current_value,
        baseline_tolerance,
        current_tolerance,
    )
    
    # Step 2: Analyze engineering impact
    engineering_impact = _analyze_engineering_impact(
        dimension_name,
        criticality,
        change_type,
        baseline_exists,
        current_exists,
    )
    
    # Step 3: Apply deterministic rules
    triggered_rules = []
    severity = "SAFE"
    finding = "No issues detected"
    reason = "Dimension unchanged and valid"
    
    rule_context = {
        "baseline_exists": baseline_exists,
        "current_exists": current_exists,
        "tolerance_present_baseline": baseline_tolerance is not None,
        "tolerance_present_current": current_tolerance is not None,
        "change_type": change_type,
        "criticality": criticality,
        "delta_percent": delta_percent,
        "engineering_impact": engineering_impact,
        "name": dimension_name,
    }
    
    # Evaluate all rules
    for rule_key, rule_def in DETERMINISTIC_RULES.items():
        if rule_def["triggers"](rule_context):
            triggered_rules.append(rule_key)
            
            # Use the highest severity found
            rule_severity = rule_def["severity"]
            if rule_severity == "BLOCK":
                severity = "BLOCK"
                finding = rule_key
                message = rule_def["message"]
                reason = message.format(
                    name=dimension_name,
                    delta_pct=delta_percent or 0
                )
            elif rule_severity == "WARN" and severity != "BLOCK":
                severity = "WARN"
                finding = rule_key
                message = rule_def["message"]
                reason = message.format(
                    name=dimension_name,
                    delta_pct=delta_percent or 0
                )
    
    # If no rules triggered but dimension removed, escalate
    if not triggered_rules and change_type == "REMOVED":
        severity = "WARN" if criticality in ["MEDIUM", "LOW"] else "BLOCK"
        triggered_rules.append("DIMENSION_REMOVED")
        finding = "DIMENSION_REMOVED"
        reason = f"Dimension {dimension_name} ({criticality}) removed from revision."
    
    recommended_action = None
    if severity == "BLOCK":
        recommended_action = "Restore dimension definition or provide engineering justification with approved ECN."
    elif severity == "WARN":
        recommended_action = "Review change with design owner and validate engineering assumptions."
    
    return DimensionEvaluation(
        dimension_id=dimension_id,
        name=dimension_name,
        baseline_revision="R3",  # TODO: derive from revision_number
        revision_under_review=f"R{1}",  # TODO: derive from revision_number
        baseline_exists=baseline_exists,
        current_exists=current_exists,
        tolerance_present_baseline=baseline_tolerance is not None,
        tolerance_present_current=current_tolerance is not None,
        baseline_value=str(baseline_value) if baseline_value else None,
        baseline_tolerance=str(baseline_tolerance) if baseline_tolerance else None,
        current_value=str(current_value) if current_value else None,
        current_tolerance=str(current_tolerance) if current_tolerance else None,
        change_type=change_type,
        delta_percent=delta_percent,
        criticality=criticality,
        engineering_impact=engineering_impact,
        severity=severity,
        finding=finding,
        reason=reason,
        triggered_rules=triggered_rules,
        recommended_action=recommended_action,
    )


# ============================================================================
# REVISION ANALYSIS ORCHESTRATION
# ============================================================================

def generate_dimension_analyses(
    revision_id: str,
    baseline_revision_id: Optional[str] = None,
) -> Tuple[List[DimensionEvaluation], Dict[str, Dict[str, Any]]]:
    """
    Generate complete analysis for all dimensions in revision.
    
    Returns: (dimension_analyses, baseline_dims)
    """
    # Extract current revision dimensions
    current_dims = extract_dimensions_from_revision(revision_id)
    
    # Get baseline dimensions
    baseline_dims: Dict[str, Dict[str, Any]] = {}
    if baseline_revision_id:
        baseline_dims = extract_dimensions_from_revision(baseline_revision_id)
    
    dimension_analyses = []
    all_dim_ids = set(current_dims.keys()) | set(baseline_dims.keys())
    
    for dim_id in sorted(all_dim_ids):
        current_dim = current_dims.get(dim_id)
        baseline_dim = baseline_dims.get(dim_id)
        
        # Determine what exists
        baseline_exists = baseline_dim is not None
        current_exists = current_dim is not None
        
        # Extract values
        baseline_value = baseline_dim.get("value") if baseline_dim else None
        current_value = current_dim.get("value") if current_dim else None
        baseline_tolerance = baseline_dim.get("tolerance") if baseline_dim else None
        current_tolerance = current_dim.get("tolerance") if current_dim else None
        
        # Get dimension name
        dimension_name = (
            current_dim.get("name") if current_dim
            else baseline_dim.get("name") if baseline_dim
            else dim_id
        )
        
        # Classify criticality
        criticality = _classify_criticality(dimension_name)
        
        # Evaluate dimension
        evaluation = evaluate_dimension(
            dimension_id=dim_id,
            dimension_name=dimension_name,
            baseline_exists=baseline_exists,
            current_exists=current_exists,
            baseline_value=baseline_value,
            current_value=current_value,
            baseline_tolerance=baseline_tolerance,
            current_tolerance=current_tolerance,
            criticality=criticality,
            dimension_type=current_dim.get("type") if current_dim else "DIMENSION",
        )
        
        dimension_analyses.append(evaluation)
    
    return dimension_analyses, baseline_dims


def generate_validation_context(
    revision_id: str,
    dimension_analyses: List[DimensionEvaluation],
    baseline_revision_id: Optional[str] = None,
) -> RevisionValidationContext:
    """
    Build validation context state.
    
    Determines: VALIDATED, PARTIAL_EXTRACTION, COMPARISON_INCOMPLETE, NO_BASELINE, REVIEW_PENDING
    """
    # Get revision info
    revision = fetch_one("""
        SELECT revision_number, new_specs_json FROM part_revisions WHERE id = %s::uuid
    """, (revision_id,))
    
    if not revision:
        return RevisionValidationContext(
            state=ValidationContextState.REVIEW_PENDING,
            summary_text="Revision not found",
        )
    
    specs = revision.get("new_specs_json") or {}
    
    # Count extracted entities
    dimensions_extracted = len([d for d in dimension_analyses if d.current_exists])
    tolerances_extracted = len([d for d in dimension_analyses if d.tolerance_present_current])
    entities_extracted = len(dimension_analyses)
    
    # Check if baseline available
    baseline_available = baseline_revision_id is not None
    
    # Check critical findings
    critical_findings = len([d for d in dimension_analyses if d.severity == "BLOCK"])
    warning_findings = len([d for d in dimension_analyses if d.severity == "WARN"])
    
    # Rules executed = number of dimension analyses performed
    rules_executed = len(dimension_analyses)
    
    # Determine state
    state = ValidationContextState.REVIEW_PENDING
    summary_text = ""
    
    if entities_extracted == 0:
        state = ValidationContextState.NO_BASELINE
        summary_text = "No dimensions extracted from revision — insufficient data for validation"
    elif not baseline_available:
        state = ValidationContextState.NO_BASELINE
        summary_text = "No baseline revision available for comparison — validation incomplete"
    elif critical_findings > 0:
        state = ValidationContextState.PARTIAL_EXTRACTION
        summary_text = f"Critical findings detected — {critical_findings} blocking issues require resolution"
    elif dimensions_extracted < entities_extracted * 0.8:
        state = ValidationContextState.PARTIAL_EXTRACTION
        summary_text = f"Partial extraction — {dimensions_extracted}/{entities_extracted} dimensions extracted"
    elif warning_findings > 0:
        state = ValidationContextState.VALIDATED
        summary_text = f"Validation complete — {warning_findings} warning(s) found"
    else:
        state = ValidationContextState.VALIDATED
        summary_text = "Validation complete — all dimensions validated successfully"
    
    return RevisionValidationContext(
        state=state,
        entities_extracted=entities_extracted,
        dimensions_extracted=dimensions_extracted,
        tolerances_extracted=tolerances_extracted,
        baseline_available=baseline_available,
        baseline_revision=f"R{revision.get('revision_number', 0)}" if baseline_available else None,
        comparison_executed=baseline_available,
        comparison_completed=baseline_available and entities_extracted > 0,
        rules_executed=rules_executed,
        critical_findings=critical_findings,
        warning_findings=warning_findings,
        summary_text=summary_text,
    )


def generate_revision_analysis(
    revision_id: str,
    baseline_revision_id: Optional[str] = None,
) -> RevisionAnalysisSummary:
    """
    Generate complete structured analysis for revision.
    
    Orchestrates:
    1. extract_dimensions()
    2. generate_dimension_analyses()
    3. generate_validation_context()
    4. Determine overall status
    5. Generate human-readable summaries
    """
    # Get revision metadata
    revision = fetch_one("""
        SELECT pr.id, pr.revision_number, pr.part_id,
               p.part_name, p.part_number
        FROM part_revisions pr
        JOIN parts p ON pr.part_id = p.id
        WHERE pr.id = %s::uuid
    """, (revision_id,))
    
    if not revision:
        raise ValueError(f"Revision {revision_id} not found")
    
    # Generate dimension analyses
    dimension_analyses, baseline_dims = generate_dimension_analyses(
        revision_id,
        baseline_revision_id,
    )
    
    # Generate validation context
    validation_context = generate_validation_context(
        revision_id,
        dimension_analyses,
        baseline_revision_id,
    )
    
    # Determine overall status
    critical_findings = [d.finding for d in dimension_analyses if d.severity == "BLOCK"]
    warning_findings = [d.finding for d in dimension_analyses if d.severity == "WARN"]
    
    if critical_findings:
        overall_status = "BLOCK"
    elif warning_findings:
        overall_status = "WARN"
    elif validation_context.state == ValidationContextState.VALIDATED:
        overall_status = "SAFE"
    else:
        overall_status = "REVIEW_PENDING"
    
    # Generate summaries
    extraction_summary = f"{validation_context.entities_extracted} entities extracted ({validation_context.dimensions_extracted} dimensions, {validation_context.tolerances_extracted} tolerances)"
    
    comparison_summary = (
        f"Compared against baseline: {validation_context.baseline_findings if hasattr(validation_context, 'baseline_findings') else 'baseline available'}"
        if validation_context.baseline_available
        else "No baseline available for comparison"
    )
    
    validation_findings_text = ""
    if critical_findings:
        validation_findings_text += f"\nCritical findings ({len(critical_findings)}): {', '.join(critical_findings)}"
    if warning_findings:
        validation_findings_text += f"\nWarnings ({len(warning_findings)}): {', '.join(warning_findings)}"
    if not critical_findings and not warning_findings:
        validation_findings_text = "No critical findings or warnings detected"
    
    validation_reasoning = validation_context.summary_text + validation_findings_text
    
    release_recommendation = {
        "SAFE": "Revision approved for release — all validation criteria met",
        "WARN": "Release pending review — address warnings before approval",
        "BLOCK": "Release blocked — resolve critical findings before proceeding",
        "REVIEW_PENDING": "Manual review required — insufficient data for deterministic validation",
    }.get(overall_status, "Review required")
    
    # Get baseline revision number if available
    baseline_revision_number = None
    if baseline_revision_id:
        baseline_rev = fetch_one(
            "SELECT revision_number FROM part_revisions WHERE id = %s::uuid",
            (baseline_revision_id,)
        )
        if baseline_rev:
            baseline_revision_number = baseline_rev["revision_number"]
    
    return RevisionAnalysisSummary(
        revision_id=str(revision["id"]),
        revision_number=revision["revision_number"],
        part_id=str(revision["part_id"]),
        part_name=revision["part_name"],
        baseline_revision_id=baseline_revision_id,
        baseline_revision_number=baseline_revision_number,
        validation_context=validation_context,
        dimension_analyses=dimension_analyses,
        status=overall_status,
        release_recommendation=release_recommendation,
        critical_findings=critical_findings,
        warning_findings=warning_findings,
        extraction_summary=extraction_summary,
        comparison_summary=comparison_summary,
        validation_reasoning=validation_reasoning,
        analysis_timestamp=datetime.now(),
        confidence_score=95,  # High confidence on deterministic rules
    )


def persist_revision_analysis(
    revision_id: str,
    analysis: RevisionAnalysisSummary,
) -> None:
    """
    Persist complete revision analysis to database.
    """
    from psycopg2.extras import Json
    
    execute_query("""
        INSERT INTO revision_impact_analysis (part_revision_id, analysis_json, confidence_score, analysis_timestamp)
        VALUES (%s::uuid, %s, %s, %s)
        ON CONFLICT (part_revision_id) DO UPDATE SET
            analysis_json = EXCLUDED.analysis_json,
            confidence_score = EXCLUDED.confidence_score,
            analysis_timestamp = EXCLUDED.analysis_timestamp
    """, (
        revision_id,
        Json(analysis.dict()),
        analysis.confidence_score,
        analysis.analysis_timestamp,
    ))
