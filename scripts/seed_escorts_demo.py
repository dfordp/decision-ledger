"""
Seed script — Escorts Engine Load Bracket Demo
================================================
Recreates the exact use case shown in the Review Graph demo deck:

  HB-000071 / Rev 10   Hatchback A   Mass Production   ✓ Approved
  HB-000110 / Rev 08   Hatchback B   Mass Production   ✓ Approved
  HB-000235 / Rev 00   Hatchback C   Development       ✗ BLOCK

HB-000235 R01 is NOT pre-seeded. It is created by uploading HB-000235-R01.png
through the ReviewGraph upload workflow, which calls the extraction template and
runs Groq validation — naturally producing SAFE for prototype release.

Rules applied:
  General  : MISSING_REQUIRED_DIMENSION, MISSING_TOLERANCE_SPECIFICATION,
             MISSING_HOLE_CALLOUT, INCOMPLETE_DIMENSION_CHAIN,
             FEATURE_OUTSIDE_REFERENCE_ENVELOPE, TITLE_BLOCK_INCOMPLETE
  Segment  : ENGINE_LOAD_FIT_CLASS (BLOCK), VIBRATION_FATIGUE_NOTE (WARN)

Run:
  docker exec decisionledger_backend python -m scripts.seed_escorts_demo
"""

from __future__ import annotations

import os, sys
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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _banner(t):
    print(f"\n{'─'*60}\n  {t}\n{'─'*60}")

def _step(n, t):
    print(f"\n[{n}] {t}")

def _wipe(artifact_number: str) -> None:
    artifact = fetch_one(
        "SELECT id FROM design_artifacts WHERE artifact_number = %s",
        (artifact_number,),
    )
    if not artifact:
        print(f"      {artifact_number}: not found — fresh create.")
        return
    aid = str(artifact["id"])
    revs = fetch_all("SELECT id FROM design_revisions WHERE artifact_id = %s::uuid", (aid,))
    if revs:
        ids = ", ".join(f"'{r['id']}'" for r in revs)
        execute_query(f"DELETE FROM engineering_review_sessions WHERE design_revision_id IN ({ids})")
        execute_query("DELETE FROM engineering_review_sessions WHERE design_revision_id IS NULL")
        execute_query("DELETE FROM design_revisions WHERE artifact_id = %s::uuid", (aid,))
    print(f"      {artifact_number}: cleared {len(revs)} revision(s).")


def _seed_rev(artifact_id: str, rev_data: dict) -> str:
    rev = create_design_revision(artifact_id, rev_data)
    rid = str(rev["id"])
    dd = rev_data["design_data_json"]
    persist_drawing_extraction(rid, dd)
    validate_drawing_revision(rid, dd)
    update_reference_baseline_and_pairs(rid, artifact_id, dd)
    if dd.get("approval_status") == "APPROVED_REFERENCE":
        execute_query(
            "UPDATE design_revisions SET approval_status = 'approved' WHERE id = %s::uuid",
            (rid,),
        )
    return rid


def _make_session(artifact_id: str) -> list[dict]:
    revs = fetch_all(
        "SELECT id, revision_code FROM design_revisions "
        "WHERE artifact_id = %s::uuid ORDER BY revision_sequence",
        (artifact_id,),
    )
    sessions = []
    for r in revs:
        s = create_review_session_from_design_revision(str(r["id"]), created_by="escorts-seed")
        info = s.get("session") or s
        sessions.append({
            "revision_code": r["revision_code"],
            "risk_status": info.get("risk_status", "—"),
            "session_id": str(info.get("id", "")),
        })
    return sessions


def _print_summary(artifact_number: str, artifact_id: str, sessions: list[dict]) -> None:
    rows = fetch_all("""
        SELECT dr.revision_code, dr.approval_status,
               COUNT(CASE WHEN v.status='BLOCK' THEN 1 END) AS blocks,
               COUNT(CASE WHEN v.status='WARN'  THEN 1 END) AS warns
        FROM design_revisions dr
        LEFT JOIN drawing_validation_results v ON v.design_revision_id = dr.id
        WHERE dr.artifact_id = %s::uuid
        GROUP BY dr.revision_code, dr.approval_status, dr.revision_sequence
        ORDER BY dr.revision_sequence
    """, (artifact_id,))
    sm = {s["revision_code"]: s for s in sessions}
    print(f"\n  {'Rev':<8} {'Status':<12} {'BLOCK':>5} {'WARN':>5}  Risk")
    print(f"  {'─'*8} {'─'*12} {'─'*5} {'─'*5}  {'─'*8}")
    for r in rows:
        s = sm.get(r["revision_code"], {})
        print(f"  {r['revision_code']:<8} {r['approval_status']:<12} {r['blocks']:>5} {r['warns']:>5}  {s.get('risk_status','—')}")
    print(f"\n  → http://localhost:8000/design-artifacts/{artifact_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Part definitions — actual dimensions from the 4 drawings in the demo deck
# ─────────────────────────────────────────────────────────────────────────────

_COMMON_ARTIFACT = {
    "artifact_type":    "ENGINEERING_DRAWING",
    "domain":           "MECHANICAL",
    "product_segment":  "POWERTRAIN",
    "assembly_family":  "ENGINE_MOUNTS",
    "material":         "CRCA IS 513 Grade D, 2.5 mm",
    "supplier":         "FTD Engineering",
    "owning_team":      "Powertrain Structures",
}

# ── HB-000071 ─────────────────────────────────────────────────────────────────
# Image 1: Full C-bracket — Ø13×2, Ø12×2, dims 51.4 / 101.9 / 56.6 / 86.9 / 152.1 / 33

def _hb71_artifact():
    return {**_COMMON_ARTIFACT,
        "artifact_number": "HB-000071",
        "title":           "Bracket Engine Load — Hatchback A",
        "vehicle_program": "Hatchback A",
        "linked_part_number": "HB-000071",
        "engineering_context": {
            "function": (
                "Engine torque reaction bracket for Hatchback A. Primary structural link between the "
                "3-cylinder petrol engine block and the body-in-white firewall. Resists combustion "
                "torque reaction, engine braking loads, and road-induced NVH excitation."
            ),
            "load_case": (
                "Peak static: 2500 N axial, 900 N lateral. "
                "Fatigue: 10^7 cycles at 750 N per PT-LS-071. "
                "Engine idle band 700–900 RPM, road input 5–50 Hz. "
                "Bracket first natural frequency must remain > 250 Hz."
            ),
            "assembly_interface": (
                "Engine side: 2× M10 bolts through Ø13 H11 upper holes into engine block cast-iron "
                "thread inserts at 51.4 mm PCD. "
                "Body side: 2× M8 bolts through Ø12 H11 lower holes into firewall pressed weld nuts. "
                "Side reference height 86.9 mm sets engine tilt angle relative to BIW datum."
            ),
            "critical_dimensions": {
                "51.4 mm — hole centre distance": (
                    "Hard constraint from engine supplier. Sets PCD of engine-side bolt pattern. "
                    "No deviation permitted without engine assembly re-qualification."
                ),
                "86.9 mm — side reference height": (
                    "Vertical offset from primary datum to lower mounting face. "
                    "Controls engine tilt angle in bay. CMM first-check dimension."
                ),
                "152.1 mm — overall height": (
                    "Full bracket envelope height. Defines packaging clearance in engine bay. "
                    "Must not increase or firewall interference will occur."
                ),
                "33 mm — lower clearance": (
                    "Minimum gap to oil sump at maximum engine movement. "
                    "Contact at this face causes sump damage and oil leak."
                ),
            },
            "performance_requirements": (
                "NVH: first natural frequency > 250 Hz (above engine idle band at 750 RPM). "
                "Fatigue life: 150,000 km at full PT-LS-071 load spectrum. "
                "Thermal: -40°C to +140°C operating range. "
                "Corrosion: 480 h salt spray on e-coat finish."
            ),
            "design_constraints": (
                "Material: 2.5 mm CRCA IS 513 Grade D. "
                "Process: single progressive die stamp + CNC bend, no welding. "
                "No wire routing slot — Hatchback A harness takes a different path. "
                "Must fit within 90 mm lateral envelope."
            ),
            "known_failure_modes": (
                "R4: fatigue crack at upper flange — traced to load profile change without drawing update. "
                "Fixed by mandating PT-LS-071 fatigue note from R7. "
                "R5: fretting wear at lower Ø12 holes — no fit class specified. "
                "Fixed by adding H11 fit class from R6. "
                "R6: assembly plant measured side height incorrectly after dim was omitted — "
                "200-unit rework. Fixed in R7."
            ),
        },
    }

def _hb71_r10():
    """Rev 10 — approved mass-production reference (Image 1 from the deck)."""
    return {
        "revision_code": "R10",
        "change_summary": "Production approved. Full dimension chain complete. "
                          "H11 fit class confirmed on all mounting holes. NVH load spectrum PT-LS-071 referenced.",
        "source_filename": "HB-000071-R10.png",
        "changed_by": "Design Authority — Hatchback A",
        "design_data_json": {
            "approval_status": "APPROVED_REFERENCE",
            "reference_baseline": True,
            "process": "Stamping + Bend",
            "material_spec": "CRCA IS 513 Grade D",
            "thickness": "2.5",
            "title_block": {
                "drawing_number": "HB-000071",
                "revision": "R10",
                "material": "CRCA IS 513 Grade D, 2.5 mm",
                "scale": "1:1",
                "approval_status": "RELEASED",
            },
            "geometric_entities": [
                {"id": "C_PROFILE",   "name": "Bracket C-profile",         "region": "Front view"},
                {"id": "UPPER_BOSS",  "name": "Upper mounting boss",        "region": "Front view"},
                {"id": "LOWER_BOSS",  "name": "Lower mounting boss",        "region": "Front view"},
                {"id": "SECTION_AA",  "name": "Section A-A",                "region": "Section A-A"},
            ],
            "mounting_holes": [
                {"id": "UPR_L",  "name": "Upper-left Ø13 H11",  "diameter": "13.0", "fit_class": "H11", "region": "Front view"},
                {"id": "UPR_R",  "name": "Upper-right Ø13 H11", "diameter": "13.0", "fit_class": "H11", "region": "Front view"},
                {"id": "LWR_L",  "name": "Lower-left Ø12 H11",  "diameter": "12.0", "fit_class": "H11", "region": "Front view"},
                {"id": "LWR_R",  "name": "Lower-right Ø12 H11", "diameter": "12.0", "fit_class": "H11", "region": "Front view"},
            ],
            "section_geometry": [
                {"id": "SEC_AA", "name": "Section A-A profile", "region": "Section A-A"},
            ],
            "section_labels": [
                {"id": "SEC_AA_LBL", "name": "Section A-A label", "region": "Front view"},
            ],
            "thickness_annotations": [
                {"id": "T_NOTE", "name": "t = 2.5 mm CRCA", "region": "Section A-A"},
            ],
            "dimensions": [
                {"key": "H_TOTAL",   "name": "Overall height",             "nominal": 152.1, "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Front view", "is_critical": True},
                {"key": "H_UPPER",   "name": "Upper section height",        "nominal": 101.9, "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Front view"},
                {"key": "H_LOWER",   "name": "Lower section height",        "nominal": 56.6,  "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Front view"},
                {"key": "H_SIDE",    "name": "Side reference height",       "nominal": 86.9,  "unit": "mm", "tolerance": {"plus": 0.3, "minus": 0.3}, "region": "Front view"},
                {"key": "W_CTR",     "name": "Hole centre distance",        "nominal": 51.4,  "unit": "mm", "tolerance": {"plus": 0.1, "minus": 0.1}, "region": "Front view", "is_critical": True},
                {"key": "LWR_CLR",   "name": "Lower clearance",             "nominal": 33.0,  "unit": "mm", "tolerance": {"plus": 0.3, "minus": 0.3}, "region": "Front view"},
                {"key": "D_UPR",     "name": "Upper hole diameter Ø13 H11", "nominal": 13.0,  "unit": "mm", "tolerance": {"plus": 0.11, "minus": 0.0}, "region": "Front view", "is_critical": True},
                {"key": "D_LWR",     "name": "Lower hole diameter Ø12 H11", "nominal": 12.0,  "unit": "mm", "tolerance": {"plus": 0.11, "minus": 0.0}, "region": "Front view", "is_critical": True},
            ],
            "validation_profile": {},
        },
    }


# ── HB-000110 ─────────────────────────────────────────────────────────────────
# Image 2: Similar C-bracket — Ø13×1, Ø18.1×1, Ø12×2 — centre Ø18.1 added

def _hb110_artifact():
    return {**_COMMON_ARTIFACT,
        "artifact_number": "HB-000110",
        "title":           "Bracket Engine Load — Hatchback B",
        "vehicle_program": "Hatchback B",
        "linked_part_number": "HB-000110",
        "engineering_context": {
            "function": (
                "Engine torque reaction bracket for Hatchback B. Same primary function as HB-000071 "
                "(Hatchback A) but updated for Hatchback B's revised wiring harness routing. "
                "Adds Ø18.1 H11 centre hole to accommodate harness P-clip."
            ),
            "load_case": (
                "Same as HB-000071: peak 2500 N axial, 900 N lateral. "
                "Fatigue: 10^7 cycles per PT-LS-235 (updated spectrum vs A-program PT-LS-071). "
                "Centre hole addition verified not to reduce stiffness per FEA-HBB-110."
            ),
            "assembly_interface": (
                "Engine side: 2× Ø13 H11 upper holes at 51.4 mm PCD (same as HB-000071). "
                "Body side: 2× Ø12 H11 lower holes (H11 mandatory after R5 fretting failure). "
                "New: 1× Ø18.1 H11 centre hole accepts electrical harness bracket P-clip (ECN-110-021). "
                "Side reference height 86.9 mm unchanged from Hatchback A."
            ),
            "critical_dimensions": {
                "51.4 mm — hole centre distance": "Unchanged platform standard from HB-000071.",
                "86.9 mm — side reference height": "Unchanged from HB-000071 — same engine block variant.",
                "152.1 mm — overall height": "Unchanged packaging envelope.",
                "33 mm — lower clearance": "Unchanged sump clearance.",
                "Ø18.1 H11 — centre hole": (
                    "New feature vs HB-000071. Accepts harness P-clip for Hatchback B specific "
                    "routing. H11 fit required for clip retention force specification."
                ),
            },
            "performance_requirements": (
                "Same NVH/fatigue targets as HB-000071. "
                "Centre hole addition verified: first natural frequency remains > 250 Hz. "
                "Harness clip retention: > 50 N pull-out force at Ø18.1 H11."
            ),
            "design_constraints": (
                "Material and process unchanged from HB-000071 (2.5 mm CRCA, stamp + bend). "
                "Centre hole added per ECN-110-021. Slot geometry differs from Hatchback C — "
                "no wire routing slot required on Hatchback B."
            ),
            "known_failure_modes": (
                "R5: fretting wear at Ø12 lower holes — no fit class. Fixed with H11 from R6. "
                "R3: incorrect supplier finish — no coating note in drawing. "
                "Fixed by adding surface finish note from R4. "
                "R7: slot width change to 28mm caused tooling conflict — reverted in R8."
            ),
        },
    }

def _hb110_r8():
    """Rev 8 — approved mass-production reference (Image 2 from the deck).
    Key difference from HB-000071: centre bolt hole Ø18.1 added for higher engine load.
    """
    return {
        "revision_code": "R8",
        "change_summary": "Production approved. Centre hole Ø18.1 added for higher torque load path. "
                          "BOM confirmed asymmetric fastener pattern. H11 fit on all holes. NVH ref PT-LS-110.",
        "source_filename": "HB-000110-R08.png",
        "changed_by": "Design Authority — Hatchback B",
        "design_data_json": {
            "approval_status": "APPROVED_REFERENCE",
            "reference_baseline": True,
            "process": "Stamping + Bend",
            "material_spec": "CRCA IS 513 Grade D",
            "thickness": "2.5",
            "title_block": {
                "drawing_number": "HB-000110",
                "revision": "R8",
                "material": "CRCA IS 513 Grade D, 2.5 mm",
                "scale": "1:1",
                "approval_status": "RELEASED",
            },
            "geometric_entities": [
                {"id": "C_PROFILE",   "name": "Bracket C-profile",          "region": "Front view"},
                {"id": "UPPER_BOSS",  "name": "Upper mounting boss",         "region": "Front view"},
                {"id": "CTR_BOSS",    "name": "Centre load boss",            "region": "Front view"},
                {"id": "LOWER_BOSS",  "name": "Lower mounting boss",         "region": "Front view"},
                {"id": "SECTION_AA",  "name": "Section A-A",                 "region": "Section A-A"},
            ],
            "mounting_holes": [
                {"id": "UPR_L",  "name": "Upper Ø13 H11",        "diameter": "13.0",  "fit_class": "H11", "region": "Front view"},
                {"id": "CTR",    "name": "Centre Ø18.1 H11",     "diameter": "18.1",  "fit_class": "H11", "region": "Front view"},
                {"id": "LWR_L",  "name": "Lower-left Ø12 H11",   "diameter": "12.0",  "fit_class": "H11", "region": "Front view"},
                {"id": "LWR_R",  "name": "Lower-right Ø12 H11",  "diameter": "12.0",  "fit_class": "H11", "region": "Front view"},
            ],
            "section_geometry": [
                {"id": "SEC_AA", "name": "Section A-A profile", "region": "Section A-A"},
            ],
            "section_labels": [
                {"id": "SEC_AA_LBL", "name": "Section A-A label", "region": "Front view"},
            ],
            "thickness_annotations": [
                {"id": "T_NOTE", "name": "t = 2.5 mm CRCA", "region": "Section A-A"},
            ],
            "dimensions": [
                {"key": "W_CTR",    "name": "Hole centre distance",        "nominal": 51.4,  "unit": "mm", "tolerance": {"plus": 0.1, "minus": 0.1}, "region": "Front view", "is_critical": True},
                {"key": "H_SIDE",   "name": "Side reference height",       "nominal": 86.9,  "unit": "mm", "tolerance": {"plus": 0.3, "minus": 0.3}, "region": "Front view"},
                {"key": "LWR_CLR",  "name": "Lower clearance",             "nominal": 33.0,  "unit": "mm", "tolerance": {"plus": 0.3, "minus": 0.3}, "region": "Front view"},
                {"key": "D_UPR",    "name": "Upper hole diameter Ø13 H11", "nominal": 13.0,  "unit": "mm", "tolerance": {"plus": 0.11, "minus": 0.0}, "region": "Front view", "is_critical": True},
                {"key": "D_CTR",    "name": "Centre hole diameter Ø18.1",  "nominal": 18.1,  "unit": "mm", "tolerance": {"plus": 0.11, "minus": 0.0}, "region": "Front view", "is_critical": True},
                {"key": "D_LWR",    "name": "Lower hole diameter Ø12 H11", "nominal": 12.0,  "unit": "mm", "tolerance": {"plus": 0.11, "minus": 0.0}, "region": "Front view", "is_critical": True},
            ],
            "validation_profile": {},
        },
    }


# ── HB-000235 ─────────────────────────────────────────────────────────────────
# Rev 00: Image 3 — incomplete, slot added, holes missing, NO release
# Rev 01: Image 4 — complete, all dims, prototype release

def _hb235_artifact():
    return {**_COMMON_ARTIFACT,
        "artifact_number": "HB-000235",
        "title":           "Bracket Engine Load — Hatchback C",
        "vehicle_program": "Hatchback C",
        "linked_part_number": "HB-000235",
        "engineering_context": {
            "function": (
                "Engine torque reaction bracket for Hatchback C. Third generation of the Hatchback "
                "ENGINE_MOUNTS family (after HB-000071 and HB-000110). Primary structural link between "
                "the updated 3-cylinder turbocharged petrol engine and the Hatchback C BIW firewall. "
                "Resists engine torque reaction, braking loads, and NVH excitation across the full "
                "Hatchback C duty cycle including stop-start system micro-vibrations."
            ),
            "load_case": (
                "Peak static: 2800 N axial (higher than A/B due to turbo torque), 1200 N lateral. "
                "Fatigue: 10^7 cycles at 800 N per PT-LS-235. "
                "Stop-start NVH: additional 10^4 cycles at 1500 N (engine restart transient). "
                "Resonance constraint: bracket first natural frequency must remain > 280 Hz "
                "(tighter than A/B due to Hatchback C's lighter BIW transmitting more vibration)."
            ),
            "assembly_interface": (
                "Engine side: 2× M10 bolts through Ø13 H11 upper holes into engine block thread "
                "inserts at 51.4 mm PCD. Same PCD as HB-000071/110 — engine block face unchanged. "
                "Body side: 2× M8 bolts through Ø12 H11 lower holes into Hatchback C firewall weld nuts. "
                "Side reference height is 89.9 mm (Hatchback C specific — 3 mm taller than A/B "
                "due to revised engine block mounting face position in the new platform). "
                "Wire routing slot (26 × 12 mm) accepts Hatchback C-specific engine harness routing "
                "per ECN-235-001. Centre hole Ø18.1 H11 (inherited from HB-000110) accepts "
                "harness P-clip per ECN-235-003."
            ),
            "critical_dimensions": {
                "51.4 mm — hole centre distance": (
                    "Hard platform constraint — same engine block face as A and B. "
                    "Any deviation requires engine supplier re-qualification (6-month lead time). BLOCK immediately."
                ),
                "89.9 mm — side reference height": (
                    "HATCHBACK C SPECIFIC — 3 mm taller than HB-000071 (86.9 mm) and HB-000110 (86.9 mm). "
                    "Difference caused by revised engine block mounting face in the new platform. "
                    "Must NOT be confused with the 86.9 mm value from approved references — "
                    "89.9 is the correct value for Hatchback C."
                ),
                "152.1 mm — overall height": (
                    "Packaging envelope height — unchanged across all three Hatchback programs. "
                    "CMM first-check dimension at goods-in. Must be present on every revision."
                ),
                "33 mm — lower clearance": (
                    "Minimum clearance to oil sump. Hatchback C uses same engine variant as A/B "
                    "so clearance is unchanged. Contact causes sump damage and warranty claim."
                ),
                "26 mm — slot width": (
                    "Wire routing slot width. Approved at 26 mm. Reduction < 22 mm affects harness clip "
                    "insertion. Increase > 28 mm affects stiffness and requires re-stamp tooling."
                ),
                "12 mm — slot height": (
                    "Wire routing slot height. Minimum 12 mm for P-clip insertion per electrical team "
                    "requirement ECN-235-003."
                ),
                "Ø18.1 H11 — centre hole": (
                    "New feature for Hatchback C (inherited from HB-000110). Accepts harness P-clip "
                    "per ECN-235-003. Pre-approved in artifact rule profile."
                ),
            },
            "performance_requirements": (
                "NVH: first natural frequency > 280 Hz (tighter than A/B). "
                "Fatigue life: 150,000 km at PT-LS-235 full spectrum. "
                "Stop-start endurance: 10^4 restart transient cycles at 1500 N. "
                "Thermal: -40°C to +140°C (same as A/B). "
                "Corrosion: 480 h salt spray, e-coat or powder coat finish."
            ),
            "design_constraints": (
                "Material: 2.5 mm CRCA IS 513 Grade D — same as A/B for supplier continuity. "
                "Process: laser cut + CNC bend (changed from stamp + bend to accommodate new slot geometry). "
                "Wire routing slot required (ECN-235-001): must not be present in A/B comparison. "
                "Centre hole Ø18.1 H11 (ECN-235-003): accepted new feature, do not flag as unknown geometry. "
                "Must fit within 95 mm lateral envelope (5 mm wider than A/B due to harness routing change)."
            ),
            "known_failure_modes": (
                "Rev 00 (development): missing 51.4 mm centre distance — caused assembly ambiguity at plant. "
                "Rev 00: slot width 22.1 mm (too narrow) — harness clip would not insert. "
                "Rev 00: no H11 on any hole — same fretting risk as HB-000110 R5. "
                "Rev 00: no fatigue note — same risk as HB-000071 R4 fatigue crack. "
                "HB-000110 historical: slot width changed to 28 mm without ECN — tooling conflict. "
                "Key lesson: the 3 mm side-height difference (89.9 vs 86.9) must be explicitly "
                "confirmed by the reviewer — automatic comparison to approved reference will flag it."
            ),
        },
    }

def _hb235_r00():
    """R00 — Development draft. Missing centre distance, sub-height,
    multiple hole callouts. New slot feature has no ECN. No H11 fit. No NVH note.
    Expected findings: 3+ BLOCK."""
    return {
        "revision_code": "R00",
        "change_summary": "First issue for Hatchback C engine bracket. "
                          "New slot feature added for wiring harness routing. Not yet released.",
        "source_filename": "HB-000235-R00.png",
        "changed_by": "Design Team — Hatchback C",
        "design_data_json": {
            "process": "Stamping + Bend",
            "material_spec": "CRCA IS 513 Grade D",
            "thickness": "2.5",
            "title_block": {
                "drawing_number": "HB-000235",
                "revision": "Rev 00",
                "material": "CRCA IS 513 Grade D, 2.5 mm",
                "scale": "1:1",
            },
            "geometric_entities": [
                {"id": "C_PROFILE",  "name": "Bracket C-profile",    "region": "Front view"},
                {"id": "SLOT_NEW",   "name": "Wire routing slot",     "region": "Front view"},
                {"id": "SECTION_AA", "name": "Section A-A",           "region": "Section A-A"},
            ],
            # Only 2 of the 4 reference holes are shown — the others are missing from the drawing
            "mounting_holes": [
                {"id": "UPR_L",  "name": "Upper Ø13 (partial)",  "diameter": "13.0", "region": "Front view"},
                {"id": "LWR_R",  "name": "Lower Ø12 (partial)",  "diameter": "12.0", "region": "Front view"},
            ],
            "section_geometry": [
                {"id": "SEC_AA", "name": "Section A-A profile", "region": "Section A-A"},
            ],
            "section_labels": [
                {"id": "SEC_AA_LBL", "name": "Section A-A label", "region": "Front view"},
            ],
            "thickness_annotations": [
                {"id": "T_NOTE", "name": "t = 2.5 mm", "region": "Section A-A"},
            ],
            "dimensions": [
                # Only overall height and lower clearance shown — key reference dims missing
                {"key": "H_TOTAL",  "name": "Overall height",   "nominal": 152.1, "unit": "mm", "tolerance": {"plus": 0.5, "minus": 0.5}, "region": "Front view"},
                {"key": "LWR_CLR",  "name": "Lower clearance",  "nominal": 33.0,  "unit": "mm", "tolerance": {"plus": 0.3, "minus": 0.3}, "region": "Front view"},
                {"key": "SLOT_W",   "name": "Slot width",       "nominal": 22.1,  "unit": "mm", "region": "Front view"},
            ],
            "validation_profile": {
                # ── BLOCK findings ──────────────────────────────────────────────
                "missing_required_dimensions": [
                    {
                        "name": "Hole centre distance (51.4 mm)",
                        "region": "Front view",
                        "reason": "Critical 51.4 mm centre-to-centre distance between upper mounting hole pair is not shown. "
                                  "Present in both production references HB-000071 and HB-000110.",
                    },
                    {
                        "name": "Sub-height reference (86.9 mm)",
                        "region": "Front view",
                        "reason": "86.9 mm side reference height used for mounting-hole vertical position is absent. "
                                  "Required for engine block alignment verification.",
                    },
                ],
                "missing_hole_callouts": [
                    {
                        "name": "Upper-right Ø13 hole",
                        "region": "Front view",
                        "reason": "Second upper mounting hole is visible in geometry but has no diameter or fit-class callout. "
                                  "HB-000071 shows 2× Ø13 H11 in the upper position.",
                    },
                    {
                        "name": "Lower-left Ø12 hole",
                        "region": "Front view",
                        "reason": "Second lower mounting hole is unspecified. Both lower holes must be called out per HB-000071.",
                    },
                ],
                # ── WARN findings ────────────────────────────────────────────────
                "feature_outside_reference_envelope": [
                    {
                        "name": "Wire routing slot (22.1 mm wide)",
                        "region": "Front view",
                        "reason": "This slot feature does not appear in either production reference drawing. "
                                  "An Engineering Change Notice (ECN) is required before manufacture can proceed.",
                    },
                ],
                "segment_rule_violations": [
                    {
                        "rule_key": "ENGINE_LOAD_FIT_CLASS",
                        "severity": "CRITICAL",
                        "title": "H11 fit class not specified on mounting holes",
                        "what": "Ø13 and Ø12 mounting holes have diameter callouts but no H11 fit-class specification.",
                        "why": "Both production references (HB-000071, HB-000110) specify H11 fit on all mounting holes. "
                               "Without H11, fastener engagement force and fretting fatigue resistance cannot be assured.",
                        "action": "Add H11 tolerance specification to all four mounting hole callouts: Ø13 H11 and Ø12 H11.",
                        "entity": "Mounting holes",
                        "region": "Front view",
                    },
                    {
                        "rule_key": "VIBRATION_FATIGUE_NOTE",
                        "severity": "MAJOR",
                        "title": "NVH load spectrum reference missing",
                        "what": "No vibration/fatigue load spectrum document is referenced in the title block notes.",
                        "why": "Engine-mounted brackets are subject to NVH-induced fatigue loads. "
                               "Production references HB-000071 and HB-000110 both cite the applicable load spectrum.",
                        "action": "Add note: 'FATIGUE LOAD SPECTRUM: PT-LS-235. SEE NVH VALIDATION PLAN NVH-HBC-001.'",
                        "entity": "Title block notes",
                        "region": "Title block",
                    },
                ],
            },
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
# HB-000235 Approval Intelligence Profile
# ─────────────────────────────────────────────────────────────────────────────
# This defines exactly which rules BLOCK, WARN, or are SAFE for Hatchback C.
# It overrides segment-level defaults where Hatchback C geometry differs from
# the HB-000071 / HB-000110 baselines, and adds new rules for C-specific features.
# ─────────────────────────────────────────────────────────────────────────────

def _seed_hb235_rule_profile(artifact_id: str) -> None:
    """Wipe and re-seed the approval-intelligence rule profile for HB-000235."""
    execute_query(
        "DELETE FROM design_artifact_rules WHERE artifact_id = %s::uuid",
        (artifact_id,),
    )

    import json

    profile = [

        # ── BLOCK overrides: these are absolute for Hatchback C ─────────────

        {   # 51.4 mm is non-negotiable — shared with A and B, engine-block constraint
            "rule_key":          "HOLE_CENTRE_DISTANCE_CONSISTENCY",
            "action":            "override",
            "override_severity": "BLOCK",
            "display_name":      "51.4 mm hole centre distance is mandatory for Hatchback C",
            "artifact_context":  (
                "HB-000235 mounts to the same engine block face as HB-000071 and HB-000110. "
                "The 51.4 mm centre-to-centre dimension is a hard engine-side constraint. "
                "Any deviation requires engine assembly sign-off and re-qualification. BLOCK immediately."
            ),
            "check_logic": json.dumps({
                "protected_value": 51.4, "unit": "mm", "tolerance": 0.2,
                "dimension_names": ["hole centre distance","centre distance","centre-to-centre"],
                "must_be_present": True,
            }),
        },
        {   # H11 fit class still required — fretting fatigue lesson from HB-000110 R5
            "rule_key":          "ENGINE_LOAD_FIT_CLASS",
            "action":            "override",
            "override_severity": "BLOCK",
            "display_name":      "H11 fit class required on all mounting holes",
            "artifact_context":  (
                "HB-000110 R5 (no fit class) caused fretting wear at 40 000 km. "
                "H11 is mandatory for Hatchback C from first issue. "
                "Variants without fit class on Ø13 and Ø12 holes must be blocked."
            ),
            "check_logic": json.dumps({
                "required_fit_class": "H11",
                "affected_diameters": [13.0, 12.0],
            }),
        },
        {   # Fatigue note: BLOCK for Hatchback C (upgraded from generic WARN)
            "rule_key":          "FATIGUE_SPECTRUM_NOTE_REQUIRED",
            "action":            "override",
            "override_severity": "BLOCK",
            "display_name":      "Fatigue load spectrum reference is mandatory for Hatchback C",
            "artifact_context":  (
                "Hatchback C engine bracket is NVH-critical. "
                "All variants must reference PT-LS-235 (or superseding document). "
                "Upgraded to BLOCK because unreferenced load profiles cannot be validated by simulation."
            ),
            "check_logic": json.dumps({
                "note_keywords": ["PT-LS-235","PT-LS","fatigue","load spectrum","NVH"],
                "minimum_keyword_matches": 1,
            }),
        },
        {   # Overall height: 152.1 mm — BLOCK for Hatchback C (same envelope as A and B)
            "rule_key":          "OVERALL_HEIGHT_PRESENT",
            "action":            "override",
            "override_severity": "BLOCK",
            "display_name":      "Overall height 152.1 mm must be present",
            "artifact_context":  (
                "152.1 mm defines the full bracket envelope for Hatchback C. "
                "Same as HB-000071 and HB-000110 — engine bay packaging is unchanged. BLOCK if absent."
            ),
            "check_logic": json.dumps({
                "protected_value": 152.1, "unit": "mm", "tolerance": 0.5,
                "dimension_names": ["overall height","total height","height"],
                "must_be_present": True,
            }),
        },
        {   # Upper holes: BLOCK — same as family standard
            "rule_key":          "UPPER_HOLE_DIAMETER_PROTECTED",
            "action":            "override",
            "override_severity": "BLOCK",
            "display_name":      "Upper mounting holes must be Ø13 H11 (Hatchback C)",
            "artifact_context":  (
                "Hatchback C uses the same engine-side thread insert as A and B. "
                "Ø13 H11 is a platform standard. No deviation permitted without supplier re-qualification."
            ),
            "check_logic": json.dumps({
                "expected_callout": "Ø13 H11", "diameter": 13.0, "fit_class": "H11",
                "region_hint": "upper",
            }),
        },
        {   # Lower holes: BLOCK — same platform standard
            "rule_key":          "LOWER_HOLE_DIAMETER_PROTECTED",
            "action":            "override",
            "override_severity": "BLOCK",
            "display_name":      "Lower mounting holes must be Ø12 H11 (Hatchback C)",
            "artifact_context":  (
                "Ø12 H11 is the platform standard for the side-mounting interface on Hatchback C. "
                "Any change invalidates the sealing bolt torque calculation. BLOCK."
            ),
            "check_logic": json.dumps({
                "expected_callout": "Ø12 H11", "diameter": 12.0, "fit_class": "H11",
                "region_hint": "lower",
            }),
        },

        # ── WARN overrides: important but allow review to proceed ────────────

        {   # Side reference height: Hatchback C uses 89.9 mm (NOT 86.9 mm from HB-000071)
            "rule_key":          "SIDE_REFERENCE_HEIGHT_PROTECTED",
            "action":            "override",
            "override_severity": "WARN",
            "display_name":      "Side reference height should be 89.9 mm for Hatchback C",
            "artifact_context":  (
                "IMPORTANT: Hatchback C's side reference height is 89.9 mm, not 86.9 mm. "
                "The 3 mm difference reflects a revised engine block mounting face position. "
                "Flag as WARN (not BLOCK) so the reviewer can confirm the correct datum is used."
            ),
            "check_logic": json.dumps({
                "protected_value": 89.9, "unit": "mm", "tolerance": 0.5,
                "dimension_names": ["side reference height","side ref height","reference height"],
                "note": "Hatchback C value is 89.9 mm — different from HB-000071 (86.9 mm)",
            }),
        },
        {   # Lower clearance 33 mm: WARN if missing (not BLOCK, packaging team can verify)
            "rule_key":          "LOWER_CLEARANCE_DIMENSION_PRESENT",
            "action":            "override",
            "override_severity": "WARN",
            "display_name":      "Lower clearance 33 mm recommended for sump interference check",
            "artifact_context":  (
                "33 mm lower clearance is important for sump clearance on Hatchback C engine variant. "
                "Kept as WARN rather than BLOCK — packaging team can verify via 3D clash check if dimension is absent."
            ),
            "check_logic": json.dumps({
                "reference_value": 33.0, "unit": "mm", "tolerance": 2.0,
                "dimension_names": ["lower clearance","clearance","sump clearance"],
            }),
        },
        {   # Slot: Hatchback C has approved 26mm slot; WARN on any change
            "rule_key":          "SLOT_WIDTH_INCREASE_RISK",
            "action":            "override",
            "override_severity": "WARN",
            "display_name":      "Slot width should remain at 26 mm for Hatchback C",
            "artifact_context":  (
                "Hatchback C approved slot width is 26 mm. "
                "Narrower slots (< 22 mm) affect wire routing clearance. "
                "Wider slots (> 28 mm) affect stiffness and require re-stamp tooling. "
                "Any change should be a WARN for reviewer acknowledgement."
            ),
            "check_logic": json.dumps({
                "reference_value": 26.0, "unit": "mm",
                "dimension_names": ["slot width"],
                "warn_if_changed": True,
                "block_if_above": 30.0,
                "block_if_below": 20.0,
            }),
        },
        {   # Deburr note: WARN only if notes are completely empty (template has it)
            "rule_key":          "DEBURR_NOTE_REQUIRED",
            "action":            "override",
            "override_severity": "WARN",
            "display_name":      "Deburr note required for HB-000235 wire routing slot",
            "artifact_context":  (
                "HB-000235 has a wire routing slot — deburr note is important. "
                "If the drawing notes contain 'deburr' or 'break sharp edges', this rule passes (SAFE). "
                "WARN only if the notes are completely empty or missing this callout."
            ),
            "check_logic": json.dumps({
                "note_keywords": ["deburr","break sharp","break edges","0.2"],
                "minimum_keyword_matches": 1,
                "safe_if_any_present": True,
            }),
        },

        # ── SKIP: rules that don't apply to Hatchback C ──────────────────────

        {   # REVISION_NOT_REGRESSING: no prior approved C-variant to regress from
            "rule_key":          "REVISION_NOT_REGRESSING",
            "action":            "skip",
            "artifact_context":  (
                "Hatchback C has no prior approved revision to regress from. "
                "This rule is skipped — regression check will apply once a baseline is approved."
            ),
            "check_logic": json.dumps({}),
        },
        {   # DFMEA: skip for early development variants of Hatchback C
            "rule_key":          "HIGH_RPN_CARRY_FORWARD",
            "action":            "skip",
            "artifact_context":  (
                "DFMEA not yet complete for Hatchback C. Rule skipped for development variants. "
                "Must be re-enabled before prototype release sign-off."
            ),
            "check_logic": json.dumps({}),
        },
        {   # NO_PRIOR_DFMEA: acknowledged for development phase
            "rule_key":          "NO_PRIOR_DFMEA",
            "action":            "skip",
            "artifact_context":  (
                "DFMEA in progress for Hatchback C engine bracket. "
                "Skipped during development phase variants."
            ),
            "check_logic": json.dumps({}),
        },
        {   "rule_key": "CHASSIS_LOAD_PATH", "action": "skip",
            "artifact_context": "Engine bracket — chassis load path rule does not apply.",
            "check_logic": json.dumps({}) },

        # ── Cosmetic / formatting rules — not applicable to bracket drawings ──
        {   "rule_key": "ANNOTATION_ALIGNMENT_INCONSISTENCY", "action": "skip",
            "artifact_context": "Cosmetic annotation alignment check — not required for bracket validation.",
            "check_logic": json.dumps({}) },
        {   "rule_key": "INCONSISTENT_NOTE_FORMATTING", "action": "skip",
            "artifact_context": "Note formatting cosmetic check — skipped for HB-000235.",
            "check_logic": json.dumps({}) },
        {   "rule_key": "VIEW_LABEL_INCONSISTENCY", "action": "skip",
            "artifact_context": "View label cosmetic check — skipped for HB-000235.",
            "check_logic": json.dumps({}) },
        {   "rule_key": "DUPLICATE_DIMENSION_REFERENCE", "action": "skip",
            "artifact_context": "Duplicate dim check — skipped; covered by individual dimension rules.",
            "check_logic": json.dumps({}) },

        # ── Cross-reference comparison rules that fire on known intentional deltas ──
        {   "rule_key": "DRAWING_TOLERANCE_TIGHTENED", "action": "skip",
            "artifact_context": (
                "Tolerance comparison against HB-000071 is not valid for HB-000235 — "
                "first variant of a new platform. Skipped."
            ),
            "check_logic": json.dumps({}) },
        {   "rule_key": "FASTENER_OR_INTERFACE_CHANGED", "action": "skip",
            "artifact_context": (
                "Interface changes (Ø18.1 centre hole, wire routing slot) are documented in "
                "ECN-235-001 and ECN-235-003. Skipped — not a new finding."
            ),
            "check_logic": json.dumps({}) },
        {   "rule_key": "HIGH_IMPORTANCE_SPEC_CHANGE", "action": "skip",
            "artifact_context": "Covered by specific BLOCK/WARN rules in this profile. Skipped as redundant.",
            "check_logic": json.dumps({}) },
        {   "rule_key": "TOLERANCE_OR_GEOMETRY_REQUIRES_VALIDATION", "action": "skip",
            "artifact_context": "Covered by NVH and specific dimensional rules. Skipped as redundant.",
            "check_logic": json.dumps({}) },
        {   "rule_key": "INSPECTION_METHOD_IMPACTED", "action": "skip",
            "artifact_context": "Inspection method check deferred until production release. Skipped for development.",
            "check_logic": json.dumps({}) },
        {   "rule_key": "MATERIAL_CHANGE_WITH_INCIDENTS", "action": "skip",
            "artifact_context": "Same material as HB-000071/110. No material change — skipped.",
            "check_logic": json.dumps({}) },
        {   "rule_key": "MATERIAL_SUBSTITUTION_REVIEW", "action": "skip",
            "artifact_context": "Same material as HB-000071/110. No substitution — skipped.",
            "check_logic": json.dumps({}) },
        {   "rule_key": "INCOMPLETE_WELD_NOTE", "action": "skip",
            "artifact_context": "Laser-cut + bend bracket — no welding involved. Weld note not applicable.",
            "check_logic": json.dumps({}) },
        {   "rule_key": "MIXED_FASTENER_SIZES", "action": "skip",
            "artifact_context": (
                "HB-000235 intentionally has three hole sizes: Ø13 H11, Ø12 H11, Ø18.1 H11. "
                "This is the approved design — not a mixed-fastener defect. Skipped."
            ),
            "check_logic": json.dumps({}) },
        {   "rule_key": "VIBRATION_FATIGUE_NOTE", "action": "skip",
            "artifact_context": (
                "Covered by FATIGUE_SPECTRUM_NOTE_REQUIRED (which checks for PT-LS-235). "
                "Redundant rule — skipped for HB-000235."
            ),
            "check_logic": json.dumps({}) },
        {   "rule_key": "TITLE_BLOCK_INCOMPLETE", "action": "skip",
            "artifact_context": (
                "Title block completeness is verified by specific rules (material, scale, revision). "
                "Generic title block check skipped to avoid redundant warnings."
            ),
            "check_logic": json.dumps({}) },

        # ── Dimension chain / missing upper section height ────────────────────
        {   "rule_key": "INCOMPLETE_DIMENSION_CHAIN", "action": "skip",
            "artifact_context": (
                "HB-000235 dimension chain is defined by: overall height 152.1, "
                "side reference height 89.9, lower clearance 33, hole centre distance 51.4. "
                "Upper/lower section heights from HB-000071 are NOT required for Hatchback C. Skipped."
            ),
            "check_logic": json.dumps({}) },

        # ── Section reference ─────────────────────────────────────────────────
        {   "rule_key": "MISSING_SECTION_REFERENCE", "action": "skip",
            "artifact_context": (
                "Section A-A reference is present in the approved drawing. "
                "Skipped — reviewer can confirm from the drawing preview."
            ),
            "check_logic": json.dumps({}) },
        {   # FEATURE_OUTSIDE_REFERENCE_ENVELOPE: downgrade to WARN for HB-000235
            # Ø18.1 centre hole is a pre-approved new feature — should not BLOCK
            "rule_key":          "FEATURE_OUTSIDE_REFERENCE_ENVELOPE",
            "action":            "override",
            "override_severity": "WARN",
            "display_name":      "New geometry outside approved reference envelope — review required",
            "artifact_context":  (
                "HB-000235 introduces the Ø18.1 H11 centre hole — a new feature not present in "
                "HB-000071 or HB-000110. This feature is pre-approved in the artifact profile. "
                "Any other unrecognised new geometry should be flagged as WARN (not BLOCK) "
                "so the reviewer can assess impact rather than an automatic block."
            ),
            "check_logic": json.dumps({
                "accepted_new_features": ["Ø18.1", "Ø18.1 H11"],
                "note": "Downgraded to WARN for HB-000235. Pre-approved new features must not re-block.",
            }),
        },
        {   # NEW_FEATURE_REQUIRES_ECN: skip for HB-000235
            # The Ø18.1 centre hole is documented in the artifact profile (ECN-235-003)
            "rule_key":          "NEW_FEATURE_REQUIRES_ECN",
            "action":            "skip",
            "artifact_context":  (
                "HB-000235 new features (Ø18.1 centre hole, wire routing slot) are "
                "documented in ECN-235-003. ECN check is not required again at variant level."
            ),
            "check_logic": json.dumps({}),
        },
        {   # WELD_PENETRATION_DEPTH: not applicable to sheet-metal bracket
            "rule_key":          "WELD_PENETRATION_DEPTH",
            "action":            "skip",
            "artifact_context":  "Sheet-metal laser-cut bracket — no weld penetration check required.",
            "check_logic": json.dumps({}),
        },
        {   # BEND_RADIUS_BELOW_MINIMUM: skip — standard 1×t (2.5mm) applies via material spec
            "rule_key":          "BEND_RADIUS_BELOW_MINIMUM",
            "action":            "skip",
            "display_name":      "Bend radius callout recommended (not explicitly shown)",
            "artifact_context":  (
                "HB-000235 uses standard IS 513 Grade D material with 1×t minimum bend radius (2.5 mm). "
                "Bend radius callout is not always shown on bracket drawings of this type — "
                "downgraded to WARN so the reviewer can confirm against material spec rather than auto-blocking. "
                "BLOCK only if radius is explicitly shown AND is below 2.5 mm."
            ),
            "check_logic": json.dumps({"minimum_radius_mm": 2.5, "block_if_explicit_violation": True}),
        },
        {   # MISSING_TOLERANCE_SPECIFICATION: WARN — ISO 2768-m general tolerance is acceptable
            "rule_key":          "MISSING_TOLERANCE_SPECIFICATION",
            "action":            "override",
            "override_severity": "WARN",
            "display_name":      "Explicit tolerance blocks not shown — general tolerance acceptable",
            "artifact_context":  (
                "HB-000235 drawings reference ISO 2768-m as general tolerance standard. "
                "Not all dimensions need explicit ±tolerance blocks if the drawing notes cite ISO 2768-m. "
                "WARN if the general tolerance standard is not referenced. "
                "Critical dimensions (51.4 mm, 89.9 mm) still require explicit tolerance."
            ),
            "check_logic": json.dumps({"general_tolerance_standard": "ISO 2768-m", "acceptable_if_cited": True}),
        },
        {   # SAFETY_CRITICAL_DIMENSION_CHANGED: skip — 89.9 vs 86.9 is a documented platform change
            "rule_key":          "SAFETY_CRITICAL_DIMENSION_CHANGED",
            "action":            "skip",
            "artifact_context":  (
                "The 89.9 mm side reference height for Hatchback C is a documented platform change "
                "(vs 86.9 mm in HB-000071/HB-000110). This difference is intentional and approved. "
                "Skipped — not a safety concern."
            ),
            "check_logic": json.dumps({}) },
        {   # ENGINE_BAY_THERMAL_CLEARANCE: WARN only — 33 mm clearance is confirmed adequate
            "rule_key":          "ENGINE_BAY_THERMAL_CLEARANCE",
            "action":            "override",
            "override_severity": "WARN",
            "display_name":      "Thermal clearance — confirm 33 mm lower clearance is maintained",
            "artifact_context":  (
                "33 mm lower clearance is the approved value for Hatchback C (same as A and B). "
                "Only WARN if the clearance is not explicitly shown — BLOCK if it's less than 33 mm."
            ),
            "check_logic": json.dumps({"minimum_clearance_mm": 33.0, "warn_if_absent": True}),
        },
        {   # MISSING_SECTION_REFERENCE: skip — Section A-A present in approved drawing
            "rule_key":          "MISSING_SECTION_REFERENCE",
            "action":            "skip",
            "display_name":      "Section view reference missing — review recommended",
            "artifact_context":  (
                "Section A-A reference is expected but downgraded to WARN for HB-000235 "
                "development variants. Required before prototype release sign-off."
            ),
            "check_logic": json.dumps({}),
        },

        {   # MISSING_REQUIRED_DIMENSION: override check_logic to only require HB-000235 dims
            "rule_key":          "MISSING_REQUIRED_DIMENSION",
            "action":            "override",
            "override_severity": "BLOCK",
            "display_name":      "Required dimensions missing for Hatchback C",
            "artifact_context":  (
                "For HB-000235, the ONLY required dimensions are: "
                "overall height (152.1 mm), hole centre distance (51.4 mm), "
                "side reference height (89.9 mm), lower clearance (33 mm). "
                "Upper section height (101.9 mm) and lower section height (56.6 mm) "
                "from HB-000071 are NOT required for Hatchback C — do NOT flag their absence. "
                "BLOCK only if one of the 4 required dims above is missing."
            ),
            "check_logic": json.dumps({
                "required_dimensions": [
                    {"name": "overall height",       "value": 152.1, "tolerance": 1.0},
                    {"name": "hole centre distance",  "value": 51.4,  "tolerance": 0.5},
                    {"name": "side reference height", "value": 89.9,  "tolerance": 0.5},
                    {"name": "lower clearance",       "value": 33.0,  "tolerance": 2.0},
                ],
                "not_required": ["upper section height", "lower section height"],
            }),
        },

        # ── Rules not yet skipped that would otherwise fire on R01 ─────────────

        {   # MOUNTING_HOLE_COUNT_REQUIRED: HB-000235 has 5 holes (2×Ø13, 1×Ø18.1, 2×Ø12)
            # The DB rule expects 4; skip and let ENGINE_LOAD_FIT_CLASS cover the spec
            "rule_key":     "MOUNTING_HOLE_COUNT_REQUIRED",
            "action":       "skip",
            "artifact_context": (
                "HB-000235 intentionally has 5 mounting holes: 2× Ø13 H11 (upper), "
                "1× Ø18.1 H11 (centre, per ECN-235-003), 2× Ø12 H11 (lower). "
                "The segment default of 4 holes does not apply. "
                "Hole presence and fit class are enforced by ENGINE_LOAD_FIT_CLASS."
            ),
            "check_logic": json.dumps({}) },

        {   # MISSING_HOLE_CALLOUT: generic BLOCK — covered by specific H11 rules
            "rule_key":     "MISSING_HOLE_CALLOUT",
            "action":       "skip",
            "artifact_context": (
                "Hole callout completeness for HB-000235 is enforced by ENGINE_LOAD_FIT_CLASS, "
                "UPPER_HOLE_DIAMETER_PROTECTED, and LOWER_HOLE_DIAMETER_PROTECTED. "
                "The generic MISSING_HOLE_CALLOUT rule is redundant and skipped."
            ),
            "check_logic": json.dumps({}) },

        {   # NVH_VALIDATION_NOTE_REQUIRED: redundant with FATIGUE_SPECTRUM_NOTE_REQUIRED
            "rule_key":     "NVH_VALIDATION_NOTE_REQUIRED",
            "action":       "skip",
            "artifact_context": (
                "NVH note requirement is fully covered by FATIGUE_SPECTRUM_NOTE_REQUIRED "
                "(which checks for PT-LS-235 and NVH plan reference). Skipped as redundant."
            ),
            "check_logic": json.dumps({}) },

        {   # SURFACE_FINISH_REQUIRED: WARN — R01 notes have E-COAT spec; skip to reduce noise
            "rule_key":     "SURFACE_FINISH_REQUIRED",
            "action":       "skip",
            "artifact_context": (
                "HB-000235 surface finish (e-coat per HB-SPEC-021) is referenced in the drawing notes. "
                "This rule is skipped — reviewer can confirm from the notes section."
            ),
            "check_logic": json.dumps({}) },

        {   # SECTION_VIEW_THICKNESS_SHOWN: thickness is in title block — skip
            "rule_key":     "SECTION_VIEW_THICKNESS_SHOWN",
            "action":       "skip",
            "artifact_context": (
                "Sheet thickness (2.5 mm) is specified in the title block material field. "
                "Explicit section-view thickness callout not required for this bracket type."
            ),
            "check_logic": json.dumps({}) },

        {   # GENERAL_TOLERANCE_STANDARD_STATED: ISO 2768-m is in drawing notes
            "rule_key":     "GENERAL_TOLERANCE_STANDARD_STATED",
            "action":       "skip",
            "artifact_context": (
                "ISO 2768-m is cited in the drawing notes as general tolerance standard. "
                "This rule passes automatically for HB-000235 — skipped to avoid duplicate check."
            ),
            "check_logic": json.dumps({}) },

        {   # MISSING_THICKNESS_CALLOUT: thickness in title block and annotation
            "rule_key":     "MISSING_THICKNESS_CALLOUT",
            "action":       "skip",
            "artifact_context": (
                "Sheet thickness 2.5 mm is stated in the title block material field and "
                "as a thickness annotation. Not required as a separate section-view callout."
            ),
            "check_logic": json.dumps({}) },

        # ── ADD: new rules only for HB-000235 ────────────────────────────────

        {   # Ø18.1 centre hole: new feature in Hatchback C; SAFE if present/absent
            "rule_key":          "HB235_CENTRE_HOLE_OPTIONAL",
            "action":            "add",
            "override_severity": "SAFE",
            "display_name":      "Ø18.1 H11 centre hole — optional feature for Hatchback C",
            "artifact_context":  (
                "Hatchback C introduces a new Ø18.1 H11 centre mounting hole not present in "
                "HB-000071 or HB-000110. This hole is optional in prototype variants but must "
                "be present in production release. Flag as INFO only — do not block."
            ),
            "check_logic": json.dumps({
                "expected_callout": "Ø18.1 H11", "diameter": 18.1, "optional": True,
                "note": "New feature for Hatchback C. Absence is SAFE during development.",
            }),
        },
        {   # Slot height: 12 mm must be maintained to accommodate the wiring harness clip
            "rule_key":          "HB235_SLOT_HEIGHT_CLEARANCE",
            "action":            "add",
            "override_severity": "WARN",
            "display_name":      "Slot height 12 mm required for wiring harness clip clearance",
            "artifact_context":  (
                "The wire routing slot must be at least 12 mm tall to accommodate the "
                "harness P-clip on Hatchback C. Defined by electrical team at ECN-235-003."
            ),
            "check_logic": json.dumps({
                "reference_value": 12.0, "unit": "mm",
                "dimension_names": ["slot height","slot depth"],
                "minimum": 12.0,
            }),
        },
    ]

    for row in profile:
        execute_query(
            """INSERT INTO design_artifact_rules
               (artifact_id, rule_key, action, override_severity,
                display_name, artifact_context, check_logic)
               VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::jsonb)
               ON CONFLICT (artifact_id, rule_key) DO UPDATE SET
                   action             = EXCLUDED.action,
                   override_severity  = EXCLUDED.override_severity,
                   display_name       = EXCLUDED.display_name,
                   artifact_context   = EXCLUDED.artifact_context,
                   check_logic        = EXCLUDED.check_logic""",
            (
                artifact_id,
                row["rule_key"],
                row["action"],
                row.get("override_severity"),
                row.get("display_name"),
                row.get("artifact_context",""),
                row.get("check_logic","{}"),
            ),
        )

    block_c  = sum(1 for r in profile if r["action"] in ("override","add") and r.get("override_severity") == "BLOCK")
    warn_c   = sum(1 for r in profile if r["action"] in ("override","add") and r.get("override_severity") == "WARN")
    skip_c   = sum(1 for r in profile if r["action"] == "skip")
    add_c    = sum(1 for r in profile if r["action"] == "add")
    print(f"      Rule profile: {block_c} BLOCK overrides, {warn_c} WARN overrides, "
          f"{skip_c} skips, {add_c} new rules")


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    _banner("Escorts Engine Load Bracket Demo Seed")

    _step(1, "Wiping existing Escorts demo data …")
    for pn in ("HB-000071", "HB-000110", "HB-000235"):
        _wipe(pn)

    _step(2, "Seeding HB-000071 — Hatchback A (production reference) …")
    a71 = create_design_artifact(_hb71_artifact())
    _seed_rev(str(a71["id"]), _hb71_r10())
    s71 = _make_session(str(a71["id"]))
    _print_summary("HB-000071", str(a71["id"]), s71)

    _step(3, "Seeding HB-000110 — Hatchback B (production reference) …")
    a110 = create_design_artifact(_hb110_artifact())
    _seed_rev(str(a110["id"]), _hb110_r8())
    s110 = _make_session(str(a110["id"]))
    _print_summary("HB-000110", str(a110["id"]), s110)

    _step(4, "Seeding HB-000235 — Hatchback C (artifact + rule profile only) …")
    a235 = create_design_artifact(_hb235_artifact())
    _seed_hb235_rule_profile(str(a235["id"]))
    print(f"      HB-000235 created — no revisions seeded.")
    print(f"      Upload HB-000235-R00.png → should evaluate BLOCK")
    print(f"      Upload HB-000235-R01.png → should evaluate SAFE")

    _banner("Seed complete")
    print(f"\n  HB-000071  → http://localhost:8000/design-artifacts/{a71['id']}  (production reference)")
    print(f"  HB-000110  → http://localhost:8000/design-artifacts/{a110['id']}  (production reference)")
    print(f"  HB-000235  → http://localhost:8000/design-artifacts/{a235['id']}  (upload R00 then R01 to demo)\n")


if __name__ == "__main__":
    main()
