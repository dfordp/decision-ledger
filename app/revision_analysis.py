"""
Revision analysis helpers for hierarchy-driven DFMEA workflows.
Combines deterministic spec diffing with optional Groq-based impact analysis.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from groq import Groq


def _flatten_specs(data: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten nested spec dictionaries to dot-path keys for diffing."""
    flattened: Dict[str, Any] = {}
    for key, value in (data or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten_specs(value, path))
        else:
            flattened[path] = value
    return flattened


def _classify_change(field_name: str) -> str:
    field = field_name.lower()
    if any(token in field for token in ["material", "alloy", "resin", "paste", "coating"]):
        return "MATERIAL"
    if any(token in field for token in ["thickness", "diameter", "length", "width", "gap", "hole", "geometry"]):
        return "GEOMETRY"
    if any(token in field for token in ["tolerance", "clearance", "stack", "fit"]):
        return "TOLERANCE"
    if any(token in field for token in ["interface", "coupling", "mount", "contact", "connector"]):
        return "DESIGN_INTERFACE"
    if any(token in field for token in ["temp", "thermal", "humidity", "vibration", "voltage", "environment"]):
        return "ENVIRONMENTAL"
    return "SPECIFICATION"


def _importance_for_change(field_name: str, old_value: Any, new_value: Any) -> str:
    field = field_name.lower()
    if any(token in field for token in ["safety", "thermal", "voltage", "material", "wire", "insulation"]):
        return "HIGH"
    if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
        baseline = abs(old_value) if old_value else 1
        delta_ratio = abs(new_value - old_value) / baseline
        if delta_ratio >= 0.2:
            return "HIGH"
        if delta_ratio >= 0.05:
            return "MEDIUM"
    return "MEDIUM"


def diff_revision_specs(old_specs: Dict[str, Any], new_specs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return normalized changes between two spec snapshots."""
    old_flat = _flatten_specs(old_specs or {})
    new_flat = _flatten_specs(new_specs or {})
    all_fields = sorted(set(old_flat) | set(new_flat))
    changes: List[Dict[str, Any]] = []

    for field in all_fields:
        old_value = old_flat.get(field)
        new_value = new_flat.get(field)
        if old_value == new_value:
            continue
        changes.append({
            "field": field,
            "old": old_value,
            "new": new_value,
            "change_type": _classify_change(field),
            "importance": _importance_for_change(field, old_value, new_value),
        })

    return changes


def map_changes_to_functions(changes: List[Dict[str, Any]], process_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Heuristically map spec changes to design functions/process steps."""
    mapped: List[Dict[str, Any]] = []

    for step in process_steps or []:
        step_name = step.get("step_name", "")
        search_blob = " ".join([
            step_name,
            step.get("function_hierarchy", "") or "",
            step.get("design_intent", "") or "",
            " ".join(step.get("critical_parameters", []) or []),
        ]).lower()
        matched_fields: List[str] = []

        for change in changes:
            field_tokens = [token for token in change["field"].lower().replace(".", "_").split("_") if token]
            if any(token in search_blob for token in field_tokens):
                matched_fields.append(change["field"])

        if matched_fields:
            mapped.append({
                "step_number": step.get("step_number"),
                "step_name": step_name,
                "matched_fields": sorted(set(matched_fields)),
                "impact": "HIGH" if len(matched_fields) > 1 else "MEDIUM",
            })

    return mapped


def _strip_json_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _build_fallback_analysis(
    changes: List[Dict[str, Any]],
    mapped_functions: List[Dict[str, Any]],
    prior_entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    entry_actions: List[Dict[str, Any]] = []
    for entry in prior_entries[:10]:
        entry_actions.append({
            "source_entry_id": entry.get("id"),
            "failure_mode": entry.get("failure_mode_name"),
            "action": "REVIEW_REQUIRED" if changes else "UNCHANGED",
            "fields_to_review": ["occurrence", "detection", "validation_measures"] if changes else [],
            "reason": "Spec changes detected for this revision." if changes else "No material spec delta detected.",
        })

    return {
        "change_summary": changes,
        "affected_functions": mapped_functions,
        "entry_actions": entry_actions,
        "new_failure_candidates": [],
        "validation_updates": [],
        "confidence_score": 55 if changes else 80,
    }


def analyze_revision_with_groq(
    *,
    part_context: Dict[str, Any],
    old_specs: Dict[str, Any],
    new_specs: Dict[str, Any],
    changes: List[Dict[str, Any]],
    mapped_functions: List[Dict[str, Any]],
    prior_entries: List[Dict[str, Any]],
    incidents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Analyze revision impact with Groq, falling back to deterministic output."""
    if not os.getenv("GROQ_API_KEY"):
        return _build_fallback_analysis(changes, mapped_functions, prior_entries)

    prompt = f"""You are a senior DFMEA engineer reviewing a part revision.

Return ONLY valid JSON with this exact structure:
{{
  "change_summary": [
    {{
      "field": "string",
      "old": "any",
      "new": "any",
      "change_type": "SPECIFICATION|MATERIAL|GEOMETRY|TOLERANCE|DESIGN_INTERFACE|ENVIRONMENTAL",
      "importance": "HIGH|MEDIUM|LOW",
      "reason": "string"
    }}
  ],
  "affected_functions": [
    {{
      "step_name": "string",
      "impact": "HIGH|MEDIUM|LOW",
      "reason": "string"
    }}
  ],
  "entry_actions": [
    {{
      "source_entry_id": 0,
      "failure_mode": "string",
      "action": "UNCHANGED|REVIEW_REQUIRED|OBSOLETE|NEW_CANDIDATE",
      "fields_to_review": ["severity", "occurrence", "detection", "validation_measures"],
      "reason": "string"
    }}
  ],
  "new_failure_candidates": [
    {{
      "failure_mode_name": "string",
      "linked_function": "string",
      "suggested_severity": 1,
      "reason": "string"
    }}
  ],
  "validation_updates": [
    {{
      "linked_function": "string",
      "recommendation": "string",
      "reason": "string"
    }}
  ],
  "confidence_score": 0
}}

PART CONTEXT:
{json.dumps(part_context, default=str, indent=2)}

OLD SPECS:
{json.dumps(old_specs or {}, default=str, indent=2)}

NEW SPECS:
{json.dumps(new_specs or {}, default=str, indent=2)}

DETERMINISTIC CHANGES:
{json.dumps(changes, default=str, indent=2)}

PRE-MAPPED AFFECTED FUNCTIONS:
{json.dumps(mapped_functions, default=str, indent=2)}

PRIOR DFMEA ENTRIES:
{json.dumps(prior_entries[:15], default=str, indent=2)}

RELEVANT HISTORICAL INCIDENTS:
{json.dumps(incidents[:12], default=str, indent=2)}

Keep recommendations grounded in the provided evidence. Do not invent part functions that are not plausible from the data."""

    try:
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise engineering analysis assistant. Return only valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1400,
        )
        content = _strip_json_fences(response.choices[0].message.content)
        json_start = content.find("{")
        json_end = content.rfind("}")
        if json_start == -1 or json_end == -1:
            raise ValueError("Groq response did not contain JSON")
        return json.loads(content[json_start:json_end + 1])
    except Exception:
        return _build_fallback_analysis(changes, mapped_functions, prior_entries)
