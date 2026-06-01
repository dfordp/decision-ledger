"""
Seed script — Historical Vehicle Programs
==========================================
Creates five completed engineering programs with full revision histories.
Each program shows a realistic improvement arc: early revisions have real
validation failures that are resolved by the approved release revision.

Programs seeded:
  ENG-LB-2401   Hatchback Engine Load Bracket       POWERTRAIN        R0→R1→R2 ✓
  BATT-MNT-3102 SUV Battery Mounting Tray            BATTERY_SYSTEM    R0→R1→R2 ✓
  CHAS-SUP-1803 Commercial Chassis Support Bracket   CHASSIS_STRUCTURE R0→R1→R2 ✓
  HVAC-PLT-2201 HVAC Evaporator Mounting Plate       HVAC_SYSTEMS      R0→R1 ✓
  SUSP-RNF-4405 Suspension Reinforcement Bracket     CHASSIS_STRUCTURE R0→R1→R2→R3 ✓

Run from project root:
  python -m scripts.seed_historical_programs
  docker exec decisionledger_backend python -m scripts.seed_historical_programs
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/decisionledger",
)

from app.database import execute_query, fetch_all, fetch_one
from app.design_review import (
    create_design_artifact,
    create_design_revision,
    create_review_session_from_design_revision,
)
from app.drawing_validation import (
    persist_drawing_extraction,
    update_reference_baseline_and_pairs,
    validate_drawing_revision,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")


def _step(n: int, text: str) -> None:
    print(f"\n[{n}] {text}")


def wipe_program(artifact_number: str) -> str | None:
    """Delete revisions (and their cascade) for artifact_number. Return artifact id or None."""
    artifact = fetch_one(
        "SELECT id FROM design_artifacts WHERE artifact_number = %s",
        (artifact_number,),
    )
    if not artifact:
        print(f"      {artifact_number}: not found — will be created fresh.")
        return None

    artifact_id = str(artifact["id"])
    revision_ids = fetch_all(
        "SELECT id FROM design_revisions WHERE artifact_id = %s::uuid",
        (artifact_id,),
    )
    if revision_ids:
        id_list = ", ".join(f"'{str(r['id'])}'" for r in revision_ids)
        execute_query(
            f"DELETE FROM engineering_review_sessions "
            f"WHERE design_revision_id IN ({id_list})"
        )
        execute_query(
            "DELETE FROM engineering_review_sessions WHERE design_revision_id IS NULL"
        )
        execute_query(
            "DELETE FROM design_revisions WHERE artifact_id = %s::uuid",
            (artifact_id,),
        )
        print(f"      {artifact_number}: cleared {len(revision_ids)} revision(s).")
    else:
        print(f"      {artifact_number}: no revisions to clear.")
    return artifact_id


def seed_revision(artifact_id: str, revision_data: dict) -> str:
    """Create a revision, run extraction + validation, and return the revision id."""
    revision = create_design_revision(artifact_id, revision_data)
    revision_id = str(revision["id"])
    design_data = revision_data["design_data_json"]

    persist_drawing_extraction(revision_id, design_data)
    validate_drawing_revision(revision_id, design_data)
    update_reference_baseline_and_pairs(revision_id, artifact_id, design_data)

    # Mark revision-level approval_status from design_data flag
    if design_data.get("approval_status") == "APPROVED_REFERENCE":
        execute_query(
            "UPDATE design_revisions SET approval_status = 'approved' WHERE id = %s::uuid",
            (revision_id,),
        )
    return revision_id


def create_sessions(artifact_id: str) -> list[dict]:
    """Create review sessions for every revision of the artifact."""
    revisions = fetch_all(
        "SELECT id, revision_code FROM design_revisions "
        "WHERE artifact_id = %s::uuid ORDER BY revision_sequence",
        (artifact_id,),
    )
    sessions = []
    for rev in revisions:
        session = create_review_session_from_design_revision(
            str(rev["id"]), created_by="seed-historical"
        )
        sessions.append({
            "revision_code": rev["revision_code"],
            "session_id": (session.get("session") or session).get("id"),
            "risk_status": (session.get("session") or session).get("risk_status"),
        })
    return sessions


def print_program_summary(artifact_number: str, artifact_id: str, sessions: list[dict]) -> None:
    rows = fetch_all(
        """
        SELECT
            dr.revision_code,
            dr.approval_status,
            (SELECT COUNT(*) FROM drawing_validation_results v WHERE v.design_revision_id = dr.id AND v.status = 'BLOCK') AS blocks,
            (SELECT COUNT(*) FROM drawing_validation_results v WHERE v.design_revision_id = dr.id AND v.status = 'WARN')  AS warns
        FROM design_revisions dr
        WHERE dr.artifact_id = %s::uuid
        ORDER BY dr.revision_sequence
        """,
        (artifact_id,),
    )
    session_map = {s["revision_code"]: s for s in sessions}
    print(f"\n  {'Rev':<4} {'Status':<12} {'BLOCK':>5} {'WARN':>5}  Risk")
    print(f"  {'─'*4} {'─'*12} {'─'*5} {'─'*5}  {'─'*8}")
    for r in rows:
        s = session_map.get(r["revision_code"], {})
        print(
            f"  {r['revision_code']:<4} {r['approval_status']:<12} "
            f"{r['blocks']:>5} {r['warns']:>5}  {s.get('risk_status','—')}"
        )


# ---------------------------------------------------------------------------
# Program definitions
# ---------------------------------------------------------------------------

# ── ENG-LB-2401: Hatchback Engine Load Bracket (POWERTRAIN) ─────────────────

def _eng_lb_artifact() -> dict:
    return {
        "artifact_number": "ENG-LB-2401",
        "title": "Hatchback Engine Load Bracket",
        "artifact_type": "ENGINEERING_DRAWING",
        "domain": "MECHANICAL",
        "product_segment": "POWERTRAIN",
        "assembly_family": "ENGINE_MOUNTS",
        "vehicle_program": "NOVA-HB-24 Hatchback",
        "material": "CRCA IS 513 Grade D, 2.0 mm",
        "supplier": "Precision Parts India Pvt Ltd",
        "owning_team": "Powertrain Structures",
        "linked_part_number": "ENG-LB-2401",
    }


def _eng_lb_r0() -> dict:
    """R0 — BLOCK: Missing hole callout, thermal clearance issue, no fatigue note."""
    return {
        "revision_code": "R0",

        "change_summary": "Initial draft release for review. Hole callout missing on upper mount, "
                          "thermal clearance to exhaust manifold not annotated.",
        "source_filename": "ENG-LB-2401-R0.pdf",
        "changed_by": "J. Patel",
        "design_data_json": {
            "process": "Laser Cut + Bend",
            "material_spec": "CRCA IS 513 Grade D",
            "thickness": "2.0",
            "title_block": {
                "drawing_number": "ENG-LB-2401",
                "revision": "R0",
                "material": "CRCA IS 513 Grade D",
                "scale": "1:2",
            },
            "geometric_entities": [
                {"id": "OUTER_PROFILE",  "name": "Bracket outer profile",  "region": "Main view"},
                {"id": "ENGINE_BOSS",    "name": "Engine block boss",       "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "UPR_MOUNT", "name": "Upper mount hole",  "diameter": None,    "region": "Mounting layout"},
                {"id": "LWR_MOUNT", "name": "Lower mount hole",  "diameter": "10.2",  "region": "Mounting layout"},
            ],
            "flanges": [
                {"id": "ENGINE_FLANGE", "name": "Engine attach flange", "region": "Right view"},
            ],
            "dimensions": [
                {"key": "W_OVERALL", "name": "Bracket width",  "nominal": 85.0,  "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Main view"},
                {"key": "H_OVERALL", "name": "Bracket height", "nominal": 120.0, "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Main view"},
                {"key": "T_FLANGE",  "name": "Flange thickness","nominal": 2.0,   "unit": "mm", "region": "Section A-A"},
            ],
            "validation_profile": {
                "missing_hole_callouts": [
                    {"name": "Upper mount hole", "region": "Mounting layout",
                     "reason": "Diameter and fit class not specified on upper mount position."},
                ],
                "segment_rule_violations": [
                    {
                        "rule_key": "ENGINE_BAY_THERMAL_CLEARANCE",
                        "severity": "MAJOR",
                        "title": "Engine bay thermal clearance not annotated",
                        "what": "No minimum clearance dimension is shown between the bracket and the exhaust manifold centreline.",
                        "why": "HTEG-2.1 requires ≥15 mm annotated clearance to prevent heat-induced bracket fatigue.",
                        "action": "Add a clearance dimension note: 'MIN 15 mm FROM EXHAUST MANIFOLD CL' on Sheet 1.",
                        "entity": "Engine attach flange",
                        "region": "Main view",
                    },
                    {
                        "rule_key": "VIBRATION_FATIGUE_NOTE",
                        "severity": "MAJOR",
                        "title": "Vibration / fatigue note missing",
                        "what": "No NVH load spectrum reference note is present on this drawing.",
                        "why": "All engine-mounted brackets must cite the applicable NVH load case per powertrain design standard PT-STD-007.",
                        "action": "Add note: 'SEE NVH LOAD SPECTRUM DOC PT-LS-2401 FOR FATIGUE LIFE REQUIREMENTS'.",
                        "entity": "Drawing notes",
                        "region": "Title block notes",
                    },
                ],
            },
        },
    }


def _eng_lb_r1() -> dict:
    """R1 — WARN: Hole callout fixed, thermal clearance added. Fatigue note still missing."""
    return {
        "revision_code": "R1",

        "change_summary": "Upper mount hole Ø10.2 H11 callout added. Thermal clearance 18 mm annotated on Sheet 1.",
        "source_filename": "ENG-LB-2401-R1.pdf",
        "changed_by": "J. Patel",
        "design_data_json": {
            "process": "Laser Cut + Bend",
            "material_spec": "CRCA IS 513 Grade D",
            "thickness": "2.0",
            "title_block": {
                "drawing_number": "ENG-LB-2401",
                "revision": "R1",
                "material": "CRCA IS 513 Grade D",
                "scale": "1:2",
            },
            "geometric_entities": [
                {"id": "OUTER_PROFILE",  "name": "Bracket outer profile",  "region": "Main view"},
                {"id": "ENGINE_BOSS",    "name": "Engine block boss",       "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "UPR_MOUNT", "name": "Upper mount hole",  "diameter": "10.2", "fit_class": "H11", "region": "Mounting layout"},
                {"id": "LWR_MOUNT", "name": "Lower mount hole",  "diameter": "10.2", "fit_class": "H11", "region": "Mounting layout"},
            ],
            "flanges": [
                {"id": "ENGINE_FLANGE", "name": "Engine attach flange", "region": "Right view"},
            ],
            "dimensions": [
                {"key": "W_OVERALL",    "name": "Bracket width",        "nominal": 85.0,  "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Main view"},
                {"key": "H_OVERALL",    "name": "Bracket height",       "nominal": 120.0, "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Main view"},
                {"key": "T_FLANGE",     "name": "Flange thickness",     "nominal": 2.0,   "unit": "mm", "region": "Section A-A"},
                {"key": "THERM_CLEAR",  "name": "Thermal clearance",    "nominal": 18.0,  "unit": "mm", "region": "Main view"},
            ],
            "validation_profile": {
                "segment_rule_violations": [
                    {
                        "rule_key": "VIBRATION_FATIGUE_NOTE",
                        "severity": "MAJOR",
                        "title": "Vibration / fatigue note missing",
                        "what": "NVH load spectrum reference note is still absent from drawing notes.",
                        "why": "All engine-mounted brackets must cite the applicable NVH load case per PT-STD-007.",
                        "action": "Add note: 'SEE NVH LOAD SPECTRUM DOC PT-LS-2401 FOR FATIGUE LIFE REQUIREMENTS'.",
                        "entity": "Drawing notes",
                        "region": "Title block notes",
                    },
                ],
            },
        },
    }


def _eng_lb_r2() -> dict:
    """R2 — SAFE: Approved release. All issues resolved."""
    return {
        "revision_code": "R2",

        "change_summary": "NVH load spectrum note PT-LS-2401 added to title block. All review items resolved. "
                          "Approved for manufacture.",
        "source_filename": "ENG-LB-2401-R2.pdf",
        "changed_by": "A. Kumar (Design Authority)",
        "design_data_json": {
            "approval_status": "APPROVED_REFERENCE",
            "reference_baseline": True,
            "process": "Laser Cut + Bend",
            "material_spec": "CRCA IS 513 Grade D",
            "thickness": "2.0",
            "title_block": {
                "drawing_number": "ENG-LB-2401",
                "revision": "R2",
                "material": "CRCA IS 513 Grade D",
                "scale": "1:2",
                "approval_status": "RELEASED",
            },
            "geometric_entities": [
                {"id": "OUTER_PROFILE",  "name": "Bracket outer profile",  "region": "Main view"},
                {"id": "ENGINE_BOSS",    "name": "Engine block boss",       "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "UPR_MOUNT", "name": "Upper mount hole",  "diameter": "10.2", "fit_class": "H11", "region": "Mounting layout"},
                {"id": "LWR_MOUNT", "name": "Lower mount hole",  "diameter": "10.2", "fit_class": "H11", "region": "Mounting layout"},
            ],
            "flanges": [
                {"id": "ENGINE_FLANGE", "name": "Engine attach flange", "region": "Right view"},
            ],
            "thickness_annotations": [
                {"id": "T_CALLOUT", "name": "Sheet thickness t=2.0 mm", "region": "Section A-A"},
            ],
            "dimensions": [
                {"key": "W_OVERALL",    "name": "Bracket width",        "nominal": 85.0,  "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Main view"},
                {"key": "H_OVERALL",    "name": "Bracket height",       "nominal": 120.0, "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Main view"},
                {"key": "T_FLANGE",     "name": "Flange thickness",     "nominal": 2.0,   "unit": "mm", "tolerance": {"plus": 0.1, "minus": 0.1}, "region": "Section A-A"},
                {"key": "THERM_CLEAR",  "name": "Thermal clearance",    "nominal": 18.0,  "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Main view"},
                {"key": "HOLE_PCD",     "name": "Mount hole PCD",       "nominal": 62.0,  "unit": "mm", "tolerance": {"plus": 0.1, "minus": 0.1}, "region": "Mounting layout"},
            ],
            "validation_profile": {},
        },
    }


# ── BATT-MNT-3102: SUV Battery Mounting Tray (BATTERY_SYSTEM) ───────────────

def _batt_mnt_artifact() -> dict:
    return {
        "artifact_number": "BATT-MNT-3102",
        "title": "SUV Battery Mounting Tray",
        "artifact_type": "ENGINEERING_DRAWING",
        "domain": "MECHANICAL",
        "product_segment": "BATTERY_SYSTEM",
        "assembly_family": "BATTERY_ENCLOSURE",
        "vehicle_program": "TITAN-SUV-31 Electric SUV",
        "material": "Aluminium 5052-H32, 3.0 mm",
        "supplier": "Aluminium Fabricators Ltd",
        "owning_team": "Battery System Integration",
        "linked_part_number": "BATT-MNT-3102",
    }


def _batt_mnt_r0() -> dict:
    """R0 — BLOCK: Missing HV cable clearance, no thermal expansion spec, tolerance missing."""
    return {
        "revision_code": "R0",

        "change_summary": "Initial battery tray drawing. HV cable clearance not annotated. "
                          "Thermal expansion allowance missing. Retention load not specified.",
        "source_filename": "BATT-MNT-3102-R0.pdf",
        "changed_by": "R. Singh",
        "design_data_json": {
            "process": "Stamping + Riveting",
            "material_spec": "Aluminium 5052-H32",
            "thickness": "3.0",
            "title_block": {
                "drawing_number": "BATT-MNT-3102",
                "revision": "R0",
                "material": "Al 5052-H32",
                "scale": "1:4",
            },
            "geometric_entities": [
                {"id": "TRAY_BODY",    "name": "Battery tray body",        "region": "Top view"},
                {"id": "SIDE_RAIL_L", "name": "Left retention rail",       "region": "Front view"},
                {"id": "SIDE_RAIL_R", "name": "Right retention rail",      "region": "Front view"},
                {"id": "HV_CONN_CLR", "name": "HV connector clearance zone","region": "Top view"},
            ],
            "mounting_holes": [
                {"id": "CHN_MNT_FL", "name": "Front-left chassis mount",  "diameter": "12.0", "region": "Mounting layout"},
                {"id": "CHN_MNT_FR", "name": "Front-right chassis mount", "diameter": "12.0", "region": "Mounting layout"},
                {"id": "CHN_MNT_RL", "name": "Rear-left chassis mount",   "diameter": "12.0", "region": "Mounting layout"},
                {"id": "CHN_MNT_RR", "name": "Rear-right chassis mount",  "diameter": "12.0", "region": "Mounting layout"},
            ],
            "dimensions": [
                {"key": "TRAY_L",  "name": "Tray length",  "nominal": 680.0, "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Top view"},
                {"key": "TRAY_W",  "name": "Tray width",   "nominal": 420.0, "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Top view"},
                {"key": "TRAY_D",  "name": "Tray depth",   "nominal": 80.0,  "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Front view"},
            ],
            "validation_profile": {
                "missing_tolerances": [
                    {"name": "Retention rail height", "region": "Front view",
                     "reason": "Retention rail height dimension lacks tolerance guidance."},
                ],
                "segment_rule_violations": [
                    {
                        "rule_key": "HV_CABLE_CLEARANCE",
                        "severity": "CRITICAL",
                        "title": "HV cable clearance insufficient — annotation missing",
                        "what": "No minimum 25 mm segregation distance annotation is present between HV connector zone and structural tray wall.",
                        "why": "ISO 6469-3 and BMS-ELEC-002 require annotated HV cable segregation distances. Missing annotation blocks electrical safety sign-off.",
                        "action": "Add dimension: 'HV CABLE SEG. MIN 25 mm FROM STRUCTURAL MEMBER' on Sheet 1, Top View.",
                        "entity": "HV connector clearance zone",
                        "region": "Top view",
                    },
                    {
                        "rule_key": "THERMAL_EXPANSION_SPEC",
                        "severity": "MAJOR",
                        "title": "Thermal expansion specification missing",
                        "what": "Drawing does not specify dimensional allowance for thermal expansion between −40 °C and +60 °C.",
                        "why": "Al 5052-H32 thermal coefficient is 23.8 µm/m·°C; over 680 mm length this gives 2.3 mm expansion. Without annotation, assembly clearances cannot be validated.",
                        "action": "Add note: 'THERMAL EXPANSION ALLOWANCE: +2.5/−0 mm AT FULL TEMPERATURE RANGE (−40 to +60 °C). REF BMS-THM-003.'",
                        "entity": "Tray body",
                        "region": "Title block notes",
                    },
                    {
                        "rule_key": "BATTERY_RETENTION_SPEC",
                        "severity": "MAJOR",
                        "title": "Battery retention load specification incomplete",
                        "what": "Retention rails are dimensioned but carry no retention-load specification (3g lateral, 5g vertical).",
                        "why": "Vehicle crash and durability sign-off requires annotated retention loads. Missing spec blocks safety-critical validation.",
                        "action": "Add load note: 'RETENTION RAILS DESIGNED FOR MIN 3g LATERAL, 5g VERTICAL SHOCK LOAD. REF BATT-STR-031.'",
                        "entity": "Left retention rail",
                        "region": "Front view",
                    },
                ],
            },
        },
    }


def _batt_mnt_r1() -> dict:
    """R1 — WARN: HV clearance and tolerance fixed. Thermal expansion and retention still missing."""
    return {
        "revision_code": "R1",

        "change_summary": "HV cable clearance 28 mm annotated. Retention rail tolerance added. "
                          "Thermal expansion and retention load spec still outstanding.",
        "source_filename": "BATT-MNT-3102-R1.pdf",
        "changed_by": "R. Singh",
        "design_data_json": {
            "process": "Stamping + Riveting",
            "material_spec": "Aluminium 5052-H32",
            "thickness": "3.0",
            "title_block": {
                "drawing_number": "BATT-MNT-3102",
                "revision": "R1",
                "material": "Al 5052-H32",
                "scale": "1:4",
            },
            "geometric_entities": [
                {"id": "TRAY_BODY",    "name": "Battery tray body",         "region": "Top view"},
                {"id": "SIDE_RAIL_L", "name": "Left retention rail",        "region": "Front view"},
                {"id": "SIDE_RAIL_R", "name": "Right retention rail",       "region": "Front view"},
                {"id": "HV_CONN_CLR", "name": "HV connector clearance zone","region": "Top view"},
            ],
            "mounting_holes": [
                {"id": "CHN_MNT_FL", "name": "Front-left chassis mount",  "diameter": "12.0", "region": "Mounting layout"},
                {"id": "CHN_MNT_FR", "name": "Front-right chassis mount", "diameter": "12.0", "region": "Mounting layout"},
                {"id": "CHN_MNT_RL", "name": "Rear-left chassis mount",   "diameter": "12.0", "region": "Mounting layout"},
                {"id": "CHN_MNT_RR", "name": "Rear-right chassis mount",  "diameter": "12.0", "region": "Mounting layout"},
            ],
            "dimensions": [
                {"key": "TRAY_L",    "name": "Tray length",            "nominal": 680.0, "unit": "mm", "tolerance": {"plus": 1.0,  "minus": 1.0},  "region": "Top view"},
                {"key": "TRAY_W",    "name": "Tray width",             "nominal": 420.0, "unit": "mm", "tolerance": {"plus": 1.0,  "minus": 1.0},  "region": "Top view"},
                {"key": "TRAY_D",    "name": "Tray depth",             "nominal": 80.0,  "unit": "mm", "tolerance": {"plus": 0.5,  "minus": 0.5},  "region": "Front view"},
                {"key": "RAIL_H",    "name": "Retention rail height",  "nominal": 45.0,  "unit": "mm", "tolerance": {"plus": 0.3,  "minus": 0.3},  "region": "Front view"},
                {"key": "HV_CLR",    "name": "HV cable clearance",     "nominal": 28.0,  "unit": "mm", "tolerance": {"plus": 0.0,  "minus": 3.0},  "region": "Top view"},
            ],
            "validation_profile": {
                "segment_rule_violations": [
                    {
                        "rule_key": "THERMAL_EXPANSION_SPEC",
                        "severity": "MAJOR",
                        "title": "Thermal expansion specification still missing",
                        "what": "Thermal expansion allowance note not yet added to drawing.",
                        "why": "Assembly clearance validation requires documented thermal expansion range per BMS-THM-003.",
                        "action": "Add thermal expansion note referencing BMS-THM-003 before next review cycle.",
                        "entity": "Tray body",
                        "region": "Title block notes",
                    },
                    {
                        "rule_key": "BATTERY_RETENTION_SPEC",
                        "severity": "MAJOR",
                        "title": "Battery retention load specification still incomplete",
                        "what": "Retention load annotation (3g/5g) not yet added to drawing.",
                        "why": "Safety-critical validation requires annotated retention loads for crash sign-off.",
                        "action": "Add retention load note referencing BATT-STR-031.",
                        "entity": "Left retention rail",
                        "region": "Front view",
                    },
                ],
            },
        },
    }


def _batt_mnt_r2() -> dict:
    """R2 — SAFE: Approved. All issues resolved."""
    return {
        "revision_code": "R2",

        "change_summary": "Thermal expansion note added (+2.5/−0 mm, ref BMS-THM-003). "
                          "Retention load spec added (3g/5g, ref BATT-STR-031). Approved for manufacture.",
        "source_filename": "BATT-MNT-3102-R2.pdf",
        "changed_by": "V. Nair (Design Authority)",
        "design_data_json": {
            "approval_status": "APPROVED_REFERENCE",
            "reference_baseline": True,
            "process": "Stamping + Riveting",
            "material_spec": "Aluminium 5052-H32",
            "thickness": "3.0",
            "title_block": {
                "drawing_number": "BATT-MNT-3102",
                "revision": "R2",
                "material": "Al 5052-H32",
                "scale": "1:4",
                "approval_status": "RELEASED",
            },
            "geometric_entities": [
                {"id": "TRAY_BODY",    "name": "Battery tray body",         "region": "Top view"},
                {"id": "SIDE_RAIL_L", "name": "Left retention rail",        "region": "Front view"},
                {"id": "SIDE_RAIL_R", "name": "Right retention rail",       "region": "Front view"},
                {"id": "HV_CONN_CLR", "name": "HV connector clearance zone","region": "Top view"},
            ],
            "mounting_holes": [
                {"id": "CHN_MNT_FL", "name": "Front-left chassis mount",  "diameter": "12.0", "region": "Mounting layout"},
                {"id": "CHN_MNT_FR", "name": "Front-right chassis mount", "diameter": "12.0", "region": "Mounting layout"},
                {"id": "CHN_MNT_RL", "name": "Rear-left chassis mount",   "diameter": "12.0", "region": "Mounting layout"},
                {"id": "CHN_MNT_RR", "name": "Rear-right chassis mount",  "diameter": "12.0", "region": "Mounting layout"},
            ],
            "dimensions": [
                {"key": "TRAY_L",     "name": "Tray length",             "nominal": 680.0, "unit": "mm", "tolerance": {"plus": 1.0,  "minus": 1.0},  "region": "Top view"},
                {"key": "TRAY_W",     "name": "Tray width",              "nominal": 420.0, "unit": "mm", "tolerance": {"plus": 1.0,  "minus": 1.0},  "region": "Top view"},
                {"key": "TRAY_D",     "name": "Tray depth",              "nominal": 80.0,  "unit": "mm", "tolerance": {"plus": 0.5,  "minus": 0.5},  "region": "Front view"},
                {"key": "RAIL_H",     "name": "Retention rail height",   "nominal": 45.0,  "unit": "mm", "tolerance": {"plus": 0.3,  "minus": 0.3},  "region": "Front view"},
                {"key": "HV_CLR",     "name": "HV cable clearance",      "nominal": 28.0,  "unit": "mm", "tolerance": {"plus": 0.0,  "minus": 3.0},  "region": "Top view"},
                {"key": "THERM_EXP",  "name": "Thermal expansion allow", "nominal": 2.5,   "unit": "mm", "region": "Title block notes"},
            ],
            "validation_profile": {},
        },
    }


# ── CHAS-SUP-1803: Commercial Chassis Support Bracket (CHASSIS_STRUCTURE) ────

def _chas_sup_artifact() -> dict:
    return {
        "artifact_number": "CHAS-SUP-1803",
        "title": "Commercial Chassis Support Bracket",
        "artifact_type": "ENGINEERING_DRAWING",
        "domain": "MECHANICAL",
        "product_segment": "CHASSIS_STRUCTURE",
        "assembly_family": "FRAME_BRACKETS",
        "vehicle_program": "ATLAS-CV-18 Commercial Vehicle",
        "material": "S235 Structural Steel, 4.0 mm",
        "supplier": "Heavy Fabrication Works",
        "owning_team": "Chassis Engineering",
        "linked_part_number": "CHAS-SUP-1803",
    }


def _chas_sup_r0() -> dict:
    """R0 — BLOCK: Weld penetration, frame datum, and load path all missing."""
    return {
        "revision_code": "R0",

        "change_summary": "Initial chassis bracket design issued for review. "
                          "Weld symbols present but penetration depth not specified.",
        "source_filename": "CHAS-SUP-1803-R0.pdf",
        "changed_by": "M. Desai",
        "design_data_json": {
            "process": "Laser Cut + MIG Weld",
            "material_spec": "S235 Structural Steel",
            "thickness": "4.0",
            "title_block": {
                "drawing_number": "CHAS-SUP-1803",
                "revision": "R0",
                "material": "S235 JR",
                "scale": "1:3",
            },
            "geometric_entities": [
                {"id": "MAIN_BODY",    "name": "Bracket main body",         "region": "Main view"},
                {"id": "GUSSET_L",     "name": "Left gusset plate",         "region": "Main view"},
                {"id": "GUSSET_R",     "name": "Right gusset plate",        "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "FRAME_FL", "name": "Frame front-left mount",  "diameter": "16.0", "region": "Mounting layout"},
                {"id": "FRAME_FR", "name": "Frame front-right mount", "diameter": "16.0", "region": "Mounting layout"},
                {"id": "FRAME_RL", "name": "Frame rear-left mount",   "diameter": "16.0", "region": "Mounting layout"},
                {"id": "FRAME_RR", "name": "Frame rear-right mount",  "diameter": "16.0", "region": "Mounting layout"},
            ],
            "weld_locations": [
                {"id": "GUSSET_WELD_L", "name": "Left gusset weld",  "region": "Main view"},
                {"id": "GUSSET_WELD_R", "name": "Right gusset weld", "region": "Main view"},
            ],
            "dimensions": [
                {"key": "W_BODY",  "name": "Body width",   "nominal": 180.0, "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "H_BODY",  "name": "Body height",  "nominal": 95.0,  "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "T_BODY",  "name": "Body thickness","nominal": 4.0,   "unit": "mm", "region": "Section B-B"},
            ],
            "validation_profile": {
                "segment_rule_violations": [
                    {
                        "rule_key": "WELD_PENETRATION_DEPTH",
                        "severity": "CRITICAL",
                        "title": "Weld penetration depth not specified",
                        "what": "Full-penetration weld symbols shown on gusset-to-body joints but minimum throat/penetration depth callout is absent.",
                        "why": "AWS D1.1 and CHAS-WLD-018 require penetration depth specified on structural weld callouts. Without it, fabricator cannot confirm joint adequacy.",
                        "action": "Add throat depth annotation: 'FULL PENETRATION — MIN THROAT 4 mm' to each gusset weld symbol.",
                        "entity": "Left gusset weld",
                        "region": "Main view",
                    },
                    {
                        "rule_key": "CHASSIS_LOAD_PATH",
                        "severity": "MAJOR",
                        "title": "Chassis load path not documented",
                        "what": "No load-path diagram or reference to load-case analysis document appears in title block notes.",
                        "why": "Structural sign-off requires a documented load path to confirm bracket adequacy under vehicle operational loads.",
                        "action": "Add note: 'LOAD CASE REFERENCE: ATLAS-LOAD-1803. SEE STRUCTURAL ANALYSIS REPORT SA-1803-REV0.'",
                        "entity": "Bracket main body",
                        "region": "Title block notes",
                    },
                    {
                        "rule_key": "FRAME_ALIGNMENT_DATUM",
                        "severity": "MAJOR",
                        "title": "Frame alignment datum missing",
                        "what": "No vehicle coordinate datum (X0/Y0/Z0) referenced on any primary view.",
                        "why": "Chassis components must reference the vehicle datum system for assembly alignment and jig setup.",
                        "action": "Add datum triangle to main view: 'DATUM X0=FRAME CL, Y0=FRONT AXLE CL, Z0=GROUND PLANE'.",
                        "entity": "Bracket main body",
                        "region": "Main view",
                    },
                ],
            },
        },
    }


def _chas_sup_r1() -> dict:
    """R1 — WARN: Weld depth and datum added. Load path doc reference still missing."""
    return {
        "revision_code": "R1",

        "change_summary": "Weld penetration depth 4 mm added to gusset symbols. "
                          "Frame datum X0/Y0/Z0 added to main view. Load path doc reference outstanding.",
        "source_filename": "CHAS-SUP-1803-R1.pdf",
        "changed_by": "M. Desai",
        "design_data_json": {
            "process": "Laser Cut + MIG Weld",
            "material_spec": "S235 Structural Steel",
            "thickness": "4.0",
            "title_block": {
                "drawing_number": "CHAS-SUP-1803",
                "revision": "R1",
                "material": "S235 JR",
                "scale": "1:3",
            },
            "geometric_entities": [
                {"id": "MAIN_BODY",    "name": "Bracket main body",    "region": "Main view"},
                {"id": "GUSSET_L",     "name": "Left gusset plate",    "region": "Main view"},
                {"id": "GUSSET_R",     "name": "Right gusset plate",   "region": "Main view"},
                {"id": "DATUM_SYM",    "name": "Vehicle datum X0Y0Z0", "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "FRAME_FL", "name": "Frame front-left mount",  "diameter": "16.0", "region": "Mounting layout"},
                {"id": "FRAME_FR", "name": "Frame front-right mount", "diameter": "16.0", "region": "Mounting layout"},
                {"id": "FRAME_RL", "name": "Frame rear-left mount",   "diameter": "16.0", "region": "Mounting layout"},
                {"id": "FRAME_RR", "name": "Frame rear-right mount",  "diameter": "16.0", "region": "Mounting layout"},
            ],
            "weld_locations": [
                {"id": "GUSSET_WELD_L", "name": "Left gusset weld",  "throat_depth": "4.0", "region": "Main view"},
                {"id": "GUSSET_WELD_R", "name": "Right gusset weld", "throat_depth": "4.0", "region": "Main view"},
            ],
            "dimensions": [
                {"key": "W_BODY",  "name": "Body width",    "nominal": 180.0, "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "H_BODY",  "name": "Body height",   "nominal": 95.0,  "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "T_BODY",  "name": "Body thickness","nominal": 4.0,   "unit": "mm", "tolerance": {"plus": 0.2, "minus": 0.2}, "region": "Section B-B"},
                {"key": "WLD_THR", "name": "Weld throat",   "nominal": 4.0,   "unit": "mm", "region": "Weld callout"},
            ],
            "validation_profile": {
                "segment_rule_violations": [
                    {
                        "rule_key": "CHASSIS_LOAD_PATH",
                        "severity": "MAJOR",
                        "title": "Chassis load path document reference still missing",
                        "what": "Load case analysis document reference not yet added to title block notes.",
                        "why": "Structural sign-off requires the load path reference to confirm bracket adequacy.",
                        "action": "Add note: 'LOAD CASE REF: ATLAS-LOAD-1803. SEE SA-1803-REV0.'",
                        "entity": "Bracket main body",
                        "region": "Title block notes",
                    },
                ],
            },
        },
    }


def _chas_sup_r2() -> dict:
    """R2 — SAFE: Approved. Load path reference added."""
    return {
        "revision_code": "R2",

        "change_summary": "Structural load case reference ATLAS-LOAD-1803 added. "
                          "All review items resolved. Approved for manufacture.",
        "source_filename": "CHAS-SUP-1803-R2.pdf",
        "changed_by": "P. Iyer (Design Authority)",
        "design_data_json": {
            "approval_status": "APPROVED_REFERENCE",
            "reference_baseline": True,
            "process": "Laser Cut + MIG Weld",
            "material_spec": "S235 Structural Steel",
            "thickness": "4.0",
            "title_block": {
                "drawing_number": "CHAS-SUP-1803",
                "revision": "R2",
                "material": "S235 JR",
                "scale": "1:3",
                "approval_status": "RELEASED",
            },
            "geometric_entities": [
                {"id": "MAIN_BODY",    "name": "Bracket main body",    "region": "Main view"},
                {"id": "GUSSET_L",     "name": "Left gusset plate",    "region": "Main view"},
                {"id": "GUSSET_R",     "name": "Right gusset plate",   "region": "Main view"},
                {"id": "DATUM_SYM",    "name": "Vehicle datum X0Y0Z0", "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "FRAME_FL", "name": "Frame front-left mount",  "diameter": "16.0", "region": "Mounting layout"},
                {"id": "FRAME_FR", "name": "Frame front-right mount", "diameter": "16.0", "region": "Mounting layout"},
                {"id": "FRAME_RL", "name": "Frame rear-left mount",   "diameter": "16.0", "region": "Mounting layout"},
                {"id": "FRAME_RR", "name": "Frame rear-right mount",  "diameter": "16.0", "region": "Mounting layout"},
            ],
            "weld_locations": [
                {"id": "GUSSET_WELD_L", "name": "Left gusset weld",  "throat_depth": "4.0", "region": "Main view"},
                {"id": "GUSSET_WELD_R", "name": "Right gusset weld", "throat_depth": "4.0", "region": "Main view"},
            ],
            "dimensions": [
                {"key": "W_BODY",  "name": "Body width",    "nominal": 180.0, "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "H_BODY",  "name": "Body height",   "nominal": 95.0,  "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "T_BODY",  "name": "Body thickness","nominal": 4.0,   "unit": "mm", "tolerance": {"plus": 0.2, "minus": 0.2}, "region": "Section B-B"},
                {"key": "WLD_THR", "name": "Weld throat",   "nominal": 4.0,   "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.0}, "region": "Weld callout"},
                {"key": "HOLE_PCD","name": "Mount hole PCD","nominal": 140.0, "unit": "mm", "tolerance": {"plus": 0.2, "minus": 0.2}, "region": "Mounting layout"},
            ],
            "validation_profile": {},
        },
    }


# ── HVAC-PLT-2201: HVAC Evaporator Mounting Plate (HVAC_SYSTEMS) ────────────

def _hvac_plt_artifact() -> dict:
    return {
        "artifact_number": "HVAC-PLT-2201",
        "title": "HVAC Evaporator Mounting Plate",
        "artifact_type": "ENGINEERING_DRAWING",
        "domain": "MECHANICAL",
        "product_segment": "HVAC_SYSTEMS",
        "assembly_family": "CABIN_HVAC",
        "vehicle_program": "NOVA-HB-24 Hatchback",
        "material": "CRCA IS 513 Grade D, 1.2 mm",
        "supplier": "Precision Parts India Pvt Ltd",
        "owning_team": "Thermal Systems",
        "linked_part_number": "HVAC-PLT-2201",
    }


def _hvac_plt_r0() -> dict:
    """R0 — BLOCK: Missing tolerance on critical mount dimension, missing section reference."""
    return {
        "revision_code": "R0",

        "change_summary": "Initial HVAC mounting plate issued. Evaporator slot tolerance missing. "
                          "Section B-B cross-reference absent from main view.",
        "source_filename": "HVAC-PLT-2201-R0.pdf",
        "changed_by": "S. Mehta",
        "design_data_json": {
            "process": "Laser Cut + Punch",
            "material_spec": "CRCA IS 513 Grade D",
            "thickness": "1.2",
            "title_block": {
                "drawing_number": "HVAC-PLT-2201",
                "revision": "R0",
                "material": "CRCA IS 513 Grade D",
                "scale": "1:1",
            },
            "geometric_entities": [
                {"id": "PLATE_BODY",     "name": "Mounting plate body",      "region": "Main view"},
                {"id": "EVAP_SLOT",      "name": "Evaporator slot",          "region": "Main view"},
                {"id": "DRAIN_KNOCKOUT", "name": "Drain knockout",           "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "EVAP_MNT_TL", "name": "Evap mount top-left",     "diameter": "5.0", "region": "Mounting layout"},
                {"id": "EVAP_MNT_TR", "name": "Evap mount top-right",    "diameter": "5.0", "region": "Mounting layout"},
                {"id": "EVAP_MNT_BL", "name": "Evap mount bottom-left",  "diameter": "5.0", "region": "Mounting layout"},
                {"id": "EVAP_MNT_BR", "name": "Evap mount bottom-right", "diameter": "5.0", "region": "Mounting layout"},
            ],
            "section_geometry": [
                {"id": "SECT_B", "name": "Section B-B", "region": "Section B-B"},
            ],
            "dimensions": [
                {"key": "PLT_W",    "name": "Plate width",        "nominal": 210.0, "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Main view"},
                {"key": "PLT_H",    "name": "Plate height",       "nominal": 155.0, "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Main view"},
                {"key": "SLOT_W",   "name": "Evap slot width",    "nominal": 148.0, "unit": "mm", "region": "Main view"},
                {"key": "SLOT_H",   "name": "Evap slot height",   "nominal": 92.0,  "unit": "mm", "region": "Main view"},
            ],
            "validation_profile": {
                "missing_tolerances": [
                    {"name": "Evap slot width",  "region": "Main view",
                     "reason": "Evaporator slot width Ø148 lacks ±tolerance — critical for unit fitment."},
                    {"name": "Evap slot height", "region": "Main view",
                     "reason": "Evaporator slot height Ø92 lacks ±tolerance — critical for unit fitment."},
                ],
                "missing_section_references": [
                    {"name": "Section B-B", "region": "Main view",
                     "reason": "Section B-B geometry shown on separate view but main view carries no section callout arrow."},
                ],
            },
        },
    }


def _hvac_plt_r1() -> dict:
    """R1 — SAFE: Approved. Tolerances and section reference corrected."""
    return {
        "revision_code": "R1",

        "change_summary": "Evaporator slot tolerances +0/−0.3 mm added. "
                          "Section B-B callout arrow added to main view. Approved for manufacture.",
        "source_filename": "HVAC-PLT-2201-R1.pdf",
        "changed_by": "K. Sharma (Design Authority)",
        "design_data_json": {
            "approval_status": "APPROVED_REFERENCE",
            "reference_baseline": True,
            "process": "Laser Cut + Punch",
            "material_spec": "CRCA IS 513 Grade D",
            "thickness": "1.2",
            "title_block": {
                "drawing_number": "HVAC-PLT-2201",
                "revision": "R1",
                "material": "CRCA IS 513 Grade D",
                "scale": "1:1",
                "approval_status": "RELEASED",
            },
            "geometric_entities": [
                {"id": "PLATE_BODY",     "name": "Mounting plate body",  "region": "Main view"},
                {"id": "EVAP_SLOT",      "name": "Evaporator slot",      "region": "Main view"},
                {"id": "DRAIN_KNOCKOUT", "name": "Drain knockout",       "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "EVAP_MNT_TL", "name": "Evap mount top-left",     "diameter": "5.0", "region": "Mounting layout"},
                {"id": "EVAP_MNT_TR", "name": "Evap mount top-right",    "diameter": "5.0", "region": "Mounting layout"},
                {"id": "EVAP_MNT_BL", "name": "Evap mount bottom-left",  "diameter": "5.0", "region": "Mounting layout"},
                {"id": "EVAP_MNT_BR", "name": "Evap mount bottom-right", "diameter": "5.0", "region": "Mounting layout"},
            ],
            "section_geometry": [
                {"id": "SECT_B", "name": "Section B-B", "region": "Section B-B"},
            ],
            "section_labels": [
                {"id": "SECT_B_LBL", "name": "Section B-B label", "region": "Main view"},
            ],
            "dimensions": [
                {"key": "PLT_W",  "name": "Plate width",      "nominal": 210.0, "unit": "mm", "tolerance": {"plus": 0.5,  "minus": 0.5},  "region": "Main view"},
                {"key": "PLT_H",  "name": "Plate height",     "nominal": 155.0, "unit": "mm", "tolerance": {"plus": 0.5,  "minus": 0.5},  "region": "Main view"},
                {"key": "SLOT_W", "name": "Evap slot width",  "nominal": 148.0, "unit": "mm", "tolerance": {"plus": 0.0,  "minus": 0.3},  "region": "Main view"},
                {"key": "SLOT_H", "name": "Evap slot height", "nominal": 92.0,  "unit": "mm", "tolerance": {"plus": 0.0,  "minus": 0.3},  "region": "Main view"},
                {"key": "HOLE_PCD","name": "Mount hole PCD",  "nominal": 185.0, "unit": "mm", "tolerance": {"plus": 0.15, "minus": 0.15}, "region": "Mounting layout"},
            ],
            "validation_profile": {},
        },
    }


# ── SUSP-RNF-4405: Suspension Reinforcement Bracket (CHASSIS_STRUCTURE) ─────

def _susp_rnf_artifact() -> dict:
    return {
        "artifact_number": "SUSP-RNF-4405",
        "title": "Suspension Reinforcement Bracket",
        "artifact_type": "ENGINEERING_DRAWING",
        "domain": "MECHANICAL",
        "product_segment": "CHASSIS_STRUCTURE",
        "assembly_family": "SUSPENSION_MOUNTS",
        "vehicle_program": "TITAN-SUV-31 Electric SUV",
        "material": "High Strength Steel 590 MPa, 3.5 mm",
        "supplier": "Heavy Fabrication Works",
        "owning_team": "Chassis Engineering",
        "linked_part_number": "SUSP-RNF-4405",
    }


def _susp_rnf_r0() -> dict:
    """R0 — BLOCK: Weld depth missing, datum missing, load path missing, incomplete dimension chain."""
    return {
        "revision_code": "R0",

        "change_summary": "Initial suspension bracket drawing. Major structural annotation gaps identified.",
        "source_filename": "SUSP-RNF-4405-R0.pdf",
        "changed_by": "D. Rao",
        "design_data_json": {
            "process": "Press Form + MIG Weld",
            "material_spec": "HSS 590 MPa",
            "thickness": "3.5",
            "title_block": {
                "drawing_number": "SUSP-RNF-4405",
                "revision": "R0",
                "material": "HSS 590 MPa",
                "scale": "1:2",
            },
            "geometric_entities": [
                {"id": "BODY",       "name": "Bracket body",          "region": "Main view"},
                {"id": "UPPER_ARM",  "name": "Upper suspension arm",  "region": "Main view"},
                {"id": "LOWER_ARM",  "name": "Lower suspension arm",  "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "BODY_MNT_TL", "name": "Body mount top-left",     "diameter": "14.0", "region": "Mounting layout"},
                {"id": "BODY_MNT_TR", "name": "Body mount top-right",    "diameter": "14.0", "region": "Mounting layout"},
                {"id": "SUSP_PIVOT",  "name": "Suspension pivot bore",   "diameter": "28.0", "region": "Main view"},
            ],
            "weld_locations": [
                {"id": "ARM_WELD_U", "name": "Upper arm weld", "region": "Main view"},
                {"id": "ARM_WELD_L", "name": "Lower arm weld", "region": "Main view"},
            ],
            "dimensions": [
                {"key": "W_BODY",    "name": "Body width",     "nominal": 145.0, "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "H_BODY",    "name": "Body height",    "nominal": 210.0, "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "PIVOT_D",   "name": "Pivot bore dia", "nominal": 28.0,  "unit": "mm", "region": "Main view"},
            ],
            "validation_profile": {
                "incomplete_dimension_chains": [
                    {"name": "Pivot bore position chain", "region": "Main view",
                     "reason": "Suspension pivot bore X/Y position cannot be traced from available datum references."},
                ],
                "segment_rule_violations": [
                    {
                        "rule_key": "WELD_PENETRATION_DEPTH",
                        "severity": "CRITICAL",
                        "title": "Weld penetration depth not specified",
                        "what": "Upper and lower arm weld symbols show full-penetration but no throat depth is called out.",
                        "why": "AWS D1.1 requires penetration depth on structural welds. Missing callout blocks fabrication quality verification.",
                        "action": "Add weld callout: 'FULL PENETRATION — MIN THROAT 5 mm' to both arm weld symbols.",
                        "entity": "Upper arm weld",
                        "region": "Main view",
                    },
                    {
                        "rule_key": "CHASSIS_LOAD_PATH",
                        "severity": "MAJOR",
                        "title": "Chassis load path not documented",
                        "what": "No load-case reference or load-path diagram present in title block notes.",
                        "why": "Suspension bracket structural sign-off requires documented load path. Missing reference blocks validation.",
                        "action": "Add note: 'LOAD CASE REF: TITAN-LOAD-4405. SEE SA-4405-REV0.'",
                        "entity": "Bracket body",
                        "region": "Title block notes",
                    },
                    {
                        "rule_key": "FRAME_ALIGNMENT_DATUM",
                        "severity": "MAJOR",
                        "title": "Frame alignment datum missing",
                        "what": "Vehicle coordinate datum not referenced on any view.",
                        "why": "Suspension geometry is highly position-critical. Datum reference is required for jig setup and alignment validation.",
                        "action": "Add datum annotation referencing vehicle X0/Y0/Z0 to main view.",
                        "entity": "Bracket body",
                        "region": "Main view",
                    },
                ],
            },
        },
    }


def _susp_rnf_r1() -> dict:
    """R1 — WARN: Weld and datum fixed. Load path and dim chain still outstanding."""
    return {
        "revision_code": "R1",

        "change_summary": "Weld penetration 5 mm added. Frame datum X0/Y0/Z0 added. "
                          "Load path doc reference and pivot bore chain outstanding.",
        "source_filename": "SUSP-RNF-4405-R1.pdf",
        "changed_by": "D. Rao",
        "design_data_json": {
            "process": "Press Form + MIG Weld",
            "material_spec": "HSS 590 MPa",
            "thickness": "3.5",
            "title_block": {
                "drawing_number": "SUSP-RNF-4405",
                "revision": "R1",
                "material": "HSS 590 MPa",
                "scale": "1:2",
            },
            "geometric_entities": [
                {"id": "BODY",       "name": "Bracket body",          "region": "Main view"},
                {"id": "UPPER_ARM",  "name": "Upper suspension arm",  "region": "Main view"},
                {"id": "LOWER_ARM",  "name": "Lower suspension arm",  "region": "Main view"},
                {"id": "DATUM_SYM",  "name": "Vehicle datum X0Y0Z0",  "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "BODY_MNT_TL", "name": "Body mount top-left",   "diameter": "14.0", "region": "Mounting layout"},
                {"id": "BODY_MNT_TR", "name": "Body mount top-right",  "diameter": "14.0", "region": "Mounting layout"},
                {"id": "SUSP_PIVOT",  "name": "Suspension pivot bore", "diameter": "28.0", "region": "Main view"},
            ],
            "weld_locations": [
                {"id": "ARM_WELD_U", "name": "Upper arm weld", "throat_depth": "5.0", "region": "Main view"},
                {"id": "ARM_WELD_L", "name": "Lower arm weld", "throat_depth": "5.0", "region": "Main view"},
            ],
            "dimensions": [
                {"key": "W_BODY",  "name": "Body width",     "nominal": 145.0, "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "H_BODY",  "name": "Body height",    "nominal": 210.0, "unit": "mm", "tolerance": {"plus": 1.0, "minus": 1.0}, "region": "Main view"},
                {"key": "PIVOT_D", "name": "Pivot bore dia", "nominal": 28.0,  "unit": "mm", "tolerance": {"plus": 0.0, "minus": 0.05}, "region": "Main view"},
                {"key": "WLD_THR", "name": "Weld throat",   "nominal": 5.0,   "unit": "mm", "region": "Weld callout"},
            ],
            "validation_profile": {
                "incomplete_dimension_chains": [
                    {"name": "Pivot bore position chain", "region": "Main view",
                     "reason": "Pivot bore X/Y position from datum still not fully resolved."},
                ],
                "segment_rule_violations": [
                    {
                        "rule_key": "CHASSIS_LOAD_PATH",
                        "severity": "MAJOR",
                        "title": "Chassis load path document reference still missing",
                        "what": "Load case analysis document reference not yet added.",
                        "why": "Structural sign-off requires load path documentation.",
                        "action": "Add note referencing TITAN-LOAD-4405 and SA-4405-REV0.",
                        "entity": "Bracket body",
                        "region": "Title block notes",
                    },
                ],
            },
        },
    }


def _susp_rnf_r2() -> dict:
    """R2 — WARN: Load path doc added. Minor annotation inconsistency remains."""
    return {
        "revision_code": "R2",

        "change_summary": "Load case reference TITAN-LOAD-4405 added. Pivot bore chain resolved. "
                          "Minor annotation leader inconsistency on lower arm view.",
        "source_filename": "SUSP-RNF-4405-R2.pdf",
        "changed_by": "D. Rao",
        "design_data_json": {
            "process": "Press Form + MIG Weld",
            "material_spec": "HSS 590 MPa",
            "thickness": "3.5",
            "title_block": {
                "drawing_number": "SUSP-RNF-4405",
                "revision": "R2",
                "material": "HSS 590 MPa",
                "scale": "1:2",
            },
            "geometric_entities": [
                {"id": "BODY",       "name": "Bracket body",          "region": "Main view"},
                {"id": "UPPER_ARM",  "name": "Upper suspension arm",  "region": "Main view"},
                {"id": "LOWER_ARM",  "name": "Lower suspension arm",  "region": "Main view"},
                {"id": "DATUM_SYM",  "name": "Vehicle datum X0Y0Z0",  "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "BODY_MNT_TL", "name": "Body mount top-left",   "diameter": "14.0", "region": "Mounting layout"},
                {"id": "BODY_MNT_TR", "name": "Body mount top-right",  "diameter": "14.0", "region": "Mounting layout"},
                {"id": "SUSP_PIVOT",  "name": "Suspension pivot bore", "diameter": "28.0", "region": "Main view"},
            ],
            "weld_locations": [
                {"id": "ARM_WELD_U", "name": "Upper arm weld", "throat_depth": "5.0", "region": "Main view"},
                {"id": "ARM_WELD_L", "name": "Lower arm weld", "throat_depth": "5.0", "region": "Main view"},
            ],
            "dimensions": [
                {"key": "W_BODY",  "name": "Body width",         "nominal": 145.0, "unit": "mm", "tolerance": {"plus": 1.0,  "minus": 1.0},  "region": "Main view"},
                {"key": "H_BODY",  "name": "Body height",        "nominal": 210.0, "unit": "mm", "tolerance": {"plus": 1.0,  "minus": 1.0},  "region": "Main view"},
                {"key": "PIVOT_D", "name": "Pivot bore dia",     "nominal": 28.0,  "unit": "mm", "tolerance": {"plus": 0.0,  "minus": 0.05}, "region": "Main view"},
                {"key": "PIVOT_X", "name": "Pivot bore X from datum","nominal": 72.5, "unit": "mm", "tolerance": {"plus": 0.1, "minus": 0.1}, "region": "Main view"},
                {"key": "PIVOT_Y", "name": "Pivot bore Y from datum","nominal": 105.0,"unit": "mm", "tolerance": {"plus": 0.1, "minus": 0.1}, "region": "Main view"},
                {"key": "WLD_THR", "name": "Weld throat",        "nominal": 5.0,   "unit": "mm", "region": "Weld callout"},
            ],
            "validation_profile": {
                "annotation_alignment_inconsistencies": [
                    {"name": "Lower arm view leader", "region": "Front view",
                     "reason": "Dimension leader for lower arm height crosses adjacent dimension line; needs repositioning."},
                ],
            },
        },
    }


def _susp_rnf_r3() -> dict:
    """R3 — SAFE: Approved. Annotation corrected."""
    return {
        "revision_code": "R3",

        "change_summary": "Lower arm annotation leader repositioned. All outstanding items resolved. "
                          "Approved for manufacture.",
        "source_filename": "SUSP-RNF-4405-R3.pdf",
        "changed_by": "P. Iyer (Design Authority)",
        "design_data_json": {
            "approval_status": "APPROVED_REFERENCE",
            "reference_baseline": True,
            "process": "Press Form + MIG Weld",
            "material_spec": "HSS 590 MPa",
            "thickness": "3.5",
            "title_block": {
                "drawing_number": "SUSP-RNF-4405",
                "revision": "R3",
                "material": "HSS 590 MPa",
                "scale": "1:2",
                "approval_status": "RELEASED",
            },
            "geometric_entities": [
                {"id": "BODY",       "name": "Bracket body",          "region": "Main view"},
                {"id": "UPPER_ARM",  "name": "Upper suspension arm",  "region": "Main view"},
                {"id": "LOWER_ARM",  "name": "Lower suspension arm",  "region": "Main view"},
                {"id": "DATUM_SYM",  "name": "Vehicle datum X0Y0Z0",  "region": "Main view"},
            ],
            "mounting_holes": [
                {"id": "BODY_MNT_TL", "name": "Body mount top-left",   "diameter": "14.0", "region": "Mounting layout"},
                {"id": "BODY_MNT_TR", "name": "Body mount top-right",  "diameter": "14.0", "region": "Mounting layout"},
                {"id": "SUSP_PIVOT",  "name": "Suspension pivot bore", "diameter": "28.0", "region": "Main view"},
            ],
            "weld_locations": [
                {"id": "ARM_WELD_U", "name": "Upper arm weld", "throat_depth": "5.0", "region": "Main view"},
                {"id": "ARM_WELD_L", "name": "Lower arm weld", "throat_depth": "5.0", "region": "Main view"},
            ],
            "dimensions": [
                {"key": "W_BODY",    "name": "Body width",              "nominal": 145.0, "unit": "mm", "tolerance": {"plus": 1.0,  "minus": 1.0},  "region": "Main view"},
                {"key": "H_BODY",    "name": "Body height",             "nominal": 210.0, "unit": "mm", "tolerance": {"plus": 1.0,  "minus": 1.0},  "region": "Main view"},
                {"key": "PIVOT_D",   "name": "Pivot bore dia",          "nominal": 28.0,  "unit": "mm", "tolerance": {"plus": 0.0,  "minus": 0.05}, "region": "Main view"},
                {"key": "PIVOT_X",   "name": "Pivot bore X from datum", "nominal": 72.5,  "unit": "mm", "tolerance": {"plus": 0.1,  "minus": 0.1},  "region": "Main view"},
                {"key": "PIVOT_Y",   "name": "Pivot bore Y from datum", "nominal": 105.0, "unit": "mm", "tolerance": {"plus": 0.1,  "minus": 0.1},  "region": "Main view"},
                {"key": "WLD_THR",   "name": "Weld throat",             "nominal": 5.0,   "unit": "mm", "tolerance": {"plus": 0.5,  "minus": 0.0},  "region": "Weld callout"},
                {"key": "MNT_PCD",   "name": "Mount hole PCD",          "nominal": 105.0, "unit": "mm", "tolerance": {"plus": 0.2,  "minus": 0.2},  "region": "Mounting layout"},
            ],
            "validation_profile": {},
        },
    }


# ---------------------------------------------------------------------------
# Program registry
# ---------------------------------------------------------------------------

PROGRAMS = [
    {
        "label": "ENG-LB-2401 Hatchback Engine Load Bracket",
        "artifact": _eng_lb_artifact,
        "revisions": [_eng_lb_r0, _eng_lb_r1, _eng_lb_r2],
    },
    {
        "label": "BATT-MNT-3102 SUV Battery Mounting Tray",
        "artifact": _batt_mnt_artifact,
        "revisions": [_batt_mnt_r0, _batt_mnt_r1, _batt_mnt_r2],
    },
    {
        "label": "CHAS-SUP-1803 Commercial Chassis Support Bracket",
        "artifact": _chas_sup_artifact,
        "revisions": [_chas_sup_r0, _chas_sup_r1, _chas_sup_r2],
    },
    {
        "label": "HVAC-PLT-2201 HVAC Evaporator Mounting Plate",
        "artifact": _hvac_plt_artifact,
        "revisions": [_hvac_plt_r0, _hvac_plt_r1],
    },
    {
        "label": "SUSP-RNF-4405 Suspension Reinforcement Bracket",
        "artifact": _susp_rnf_artifact,
        "revisions": [_susp_rnf_r0, _susp_rnf_r1, _susp_rnf_r2, _susp_rnf_r3],
    },
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _banner("Historical Vehicle Programs Seed")

    _step(1, "Wiping existing revision data for all programs …")
    for prog in PROGRAMS:
        artifact_def = prog["artifact"]()
        wipe_program(artifact_def["artifact_number"])

    _step(2, "Seeding artifacts + revisions + extraction + validation …")
    all_sessions: list[dict] = []

    for prog in PROGRAMS:
        artifact_def = prog["artifact"]()
        print(f"\n  ── {prog['label']}")
        artifact = create_design_artifact(artifact_def)
        artifact_id = str(artifact["id"])
        print(f"     Artifact ID: {artifact_id}")

        for rev_fn in prog["revisions"]:
            rev_data = rev_fn()
            revision_id = seed_revision(artifact_id, rev_data)
            blocks = fetch_one(
                "SELECT COUNT(*) AS n FROM drawing_validation_results "
                "WHERE design_revision_id = %s::uuid AND status = 'BLOCK'",
                (revision_id,),
            )["n"]
            warns = fetch_one(
                "SELECT COUNT(*) AS n FROM drawing_validation_results "
                "WHERE design_revision_id = %s::uuid AND status = 'WARN'",
                (revision_id,),
            )["n"]
            label = "✓" if not blocks and not warns else ("BLOCK" if blocks else "WARN")
            print(f"     {rev_data['revision_code']}  {label}  ({blocks} BLOCK, {warns} WARN)")

        sessions = create_sessions(artifact_id)
        all_sessions.append({
            "artifact_number": artifact_def["artifact_number"],
            "artifact_id": artifact_id,
            "sessions": sessions,
        })

    _step(3, "Summary")
    for entry in all_sessions:
        _banner(entry["artifact_number"])
        print_program_summary(
            entry["artifact_number"],
            entry["artifact_id"],
            entry["sessions"],
        )
        print(f"  → http://localhost:8000/design-artifacts/{entry['artifact_id']}")

    print("\n  Done. All 5 historical programs seeded.\n")


if __name__ == "__main__":
    main()
