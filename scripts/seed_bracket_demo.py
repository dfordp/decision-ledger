"""
Seed script — HORN-HSG-2705 Bracket Drawing Demo
=================================================
Wipes any existing HORN-HSG-2705 data and rebuilds the complete demo dataset:

  R1  Part 1 design.pdf  →  4 findings (WARN)   risk: WARN
  R2  Part 2 design.pdf  → 11 findings (BLOCK)   risk: BLOCK
  R3  Part 3 design.pdf  →  0 findings           risk: SAFE  ← approved reference

Run from the project root:

  python -m scripts.seed_bracket_demo          (inside Docker or venv)
  docker exec decisionledger_backend python -m scripts.seed_bracket_demo

What this script does
---------------------
1. Delete any existing HORN-HSG-2705 sessions, artifact, and all related data
2. Reset the engineering_review_rules catalog to the correct 15 rules
3. Create the artifact + 3 revisions with real extracted PDF dimension values
4. Populate drawing entities, dimensions, annotations (persist_drawing_extraction)
5. Run deterministic validation on each revision
6. Register R3 as the approved reference baseline
7. Create revision comparison pairs (R3 vs R1, R3 vs R2)
8. Open a review session for each revision (creates findings, evidence, graph nodes)
9. Print a full summary
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running from project root or scripts/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/decisionledger",
)

from psycopg2.extras import Json

from app.database import execute_query, fetch_all, fetch_one
from app.design_review import (
    create_review_session_from_design_revision,
    seed_mock_bracket_review_data,
)


# ---------------------------------------------------------------------------
# Engineering review rule catalog
# ---------------------------------------------------------------------------
CORRECT_RULES = [
    # ── BLOCK rules ──────────────────────────────────────────────────────────
    ("MISSING_REQUIRED_DIMENSION",        "Missing required dimension",
     "Blocks release when a critical drawing feature lacks a dimensional reference.",
     "BLOCK", "DRAWING_VALIDATION"),
    ("MISSING_TOLERANCE_SPECIFICATION",   "Missing tolerance specification",
     "Blocks release when production-critical dimensions lack tolerance guidance.",
     "BLOCK", "DRAFTING_COMPLIANCE"),
    ("MISSING_HOLE_CALLOUT",              "Missing hole callout",
     "Blocks release when mounting holes lack diameter, thread, or callout definition.",
     "BLOCK", "ASSEMBLY_INTERFACE"),
    ("MISSING_SECTION_REFERENCE",         "Missing section reference",
     "Blocks release when section geometry lacks explicit section annotation.",
     "BLOCK", "FABRICATION_READINESS"),
    ("FEATURE_OUTSIDE_REFERENCE_ENVELOPE","Feature outside reference envelope",
     "Blocks release when a feature in this revision is absent from the approved "
     "reference drawing. An Engineering Change Notice (ECN) is required before manufacture.",
     "BLOCK", "ASSEMBLY_INTERFACE"),
    ("BEND_RADIUS_BELOW_MINIMUM",         "Bend radius below 1×t minimum",
     "Blocks release when the specified inside bend radius is below the 1×material-thickness "
     "minimum for CRCA IS 513 Grade D sheet metal.",
     "BLOCK", "MANUFACTURING_CONSTRAINT"),
    # ── WARN rules ───────────────────────────────────────────────────────────
    ("INCOMPLETE_DIMENSION_CHAIN",        "Incomplete dimension chain",
     "Flags features that cannot be fully traced through inspection dimensions.",
     "WARN", "INSPECTION_READINESS"),
    ("INCOMPLETE_WELD_NOTE",              "Incomplete weld note",
     "Flags weld locations without sufficient fabrication guidance.",
     "WARN", "FABRICATION_READINESS"),
    ("TITLE_BLOCK_INCOMPLETE",            "Title block incomplete",
     "Flags missing drawing metadata such as revision, material, or scale.",
     "WARN", "DOCUMENT_TRACEABILITY"),
    ("MISSING_THICKNESS_CALLOUT",         "Missing thickness callout",
     "Flags missing sheet thickness definition on fabrication drawings.",
     "WARN", "MATERIAL_DEFINITION"),
    ("ANNOTATION_ALIGNMENT_INCONSISTENCY","Annotation alignment inconsistency",
     "Flags annotation placement or leader inconsistencies that reduce drawing clarity.",
     "WARN", "DRAFTING_CLARITY"),
    ("DUPLICATE_DIMENSION_REFERENCE",     "Duplicate dimension reference",
     "Flags repeated dimensions that may create conflicting inspection interpretation.",
     "WARN", "DRAFTING_CLARITY"),
    ("INCONSISTENT_NOTE_FORMATTING",      "Inconsistent note formatting",
     "Flags inconsistent note formatting across drawing views.",
     "WARN", "DRAFTING_CLARITY"),
    ("VIEW_LABEL_INCONSISTENCY",          "View label inconsistency",
     "Flags inconsistent or missing view labels.",
     "WARN", "DRAFTING_CLARITY"),
    ("MIXED_FASTENER_SIZES",              "Mixed fastener/hole sizes",
     "Flags asymmetric hole diameters that imply different fastener standards; "
     "requires BOM confirmation.",
     "WARN", "ASSEMBLY_INTERFACE"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")


def _step(n: int, text: str) -> None:
    print(f"\n[{n}] {text}")


def wipe_existing_data() -> None:
    """
    Remove revision-level data for HORN-HSG-2705 without deleting the artifact.

    Preserving the artifact keeps its UUID stable — page URLs and bookmarks
    remain valid across reseeds.  Only revisions (and their dependent drawing
    entities, dimensions, annotations, validation results, sessions, etc.) are
    cleared.
    """
    artifact = fetch_one(
        "SELECT id FROM design_artifacts WHERE artifact_number = 'HORN-HSG-2705'"
    )
    if not artifact:
        print("    No existing artifact found — will be created fresh.")
        return

    artifact_id = str(artifact["id"])
    print(f"    Artifact ID (preserved): {artifact_id}")

    revision_ids = fetch_all(
        "SELECT id FROM design_revisions WHERE artifact_id = %s::uuid",
        (artifact_id,),
    )

    if revision_ids:
        id_list = ", ".join(f"'{str(r['id'])}'" for r in revision_ids)
        # engineering_review_sessions uses SET NULL on revision FK deletion,
        # so sessions must be deleted explicitly before revisions are dropped.
        # Cascade then cleans up findings, evidence, items, rule_results, audit_log.
        execute_query(
            f"DELETE FROM engineering_review_sessions "
            f"WHERE design_revision_id IN ({id_list})"
        )
        # Also clear any orphaned sessions left over from previous partial reseeds
        execute_query(
            "DELETE FROM engineering_review_sessions WHERE design_revision_id IS NULL"
        )
        # Delete revisions — cascades to ALL drawing sub-tables
        execute_query(
            f"DELETE FROM design_revisions WHERE artifact_id = %s::uuid",
            (artifact_id,),
        )
        print(f"    Cleared {len(revision_ids)} revision(s) and all dependent data.")
    else:
        print("    No existing revisions — nothing to clear.")


def reset_rule_catalog() -> None:
    """Replace the engineering_review_rules table with the correct 15 rules."""
    # Remove any stale rules not in the correct set
    correct_keys = tuple(r[0] for r in CORRECT_RULES)
    execute_query(
        f"DELETE FROM engineering_review_rules WHERE rule_key NOT IN "
        f"({', '.join('%s' for _ in correct_keys)})",
        correct_keys,
    )

    for rule_key, display_name, description, severity, rule_group in CORRECT_RULES:
        execute_query(
            """
            INSERT INTO engineering_review_rules
                (rule_key, display_name, description, severity, rule_group)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (rule_key) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                description  = EXCLUDED.description,
                severity     = EXCLUDED.severity,
                rule_group   = EXCLUDED.rule_group
            """,
            (rule_key, display_name, description, severity, rule_group),
        )

    count = fetch_one("SELECT COUNT(*) as n FROM engineering_review_rules")["n"]
    print(f"    Rule catalog: {count} rules active.")


def create_all_sessions(artifact_id: str) -> list[dict]:
    """Create review sessions for every revision of the given artifact."""
    revisions = fetch_all(
        "SELECT id, revision_code, revision_sequence "
        "FROM design_revisions WHERE artifact_id = %s::uuid "
        "ORDER BY revision_sequence",
        (artifact_id,),
    )
    sessions = []
    for rev in revisions:
        session = create_review_session_from_design_revision(
            str(rev["id"]), created_by="seed-script"
        )
        sessions.append(
            {
                "revision_code": rev["revision_code"],
                "session_id": session.get("session", {}).get("id")
                or session.get("id"),
                "risk_status": session.get("session", {}).get("risk_status")
                or session.get("risk_status"),
                "session_number": session.get("session", {}).get("session_number")
                or session.get("session_number"),
            }
        )
    return sessions


def print_summary(artifact_id: str, sessions: list[dict]) -> None:
    """Print a human-readable summary of the seeded data."""
    _banner("Seed complete — HORN-HSG-2705")

    rows = fetch_all(
        """
        SELECT
            dr.revision_code,
            dr.source_filename,
            (SELECT COUNT(*) FROM drawing_feature_entities e WHERE e.design_revision_id = dr.id) as entities,
            (SELECT COUNT(*) FROM drawing_dimensions d WHERE d.design_revision_id = dr.id) as dimensions,
            (SELECT COUNT(*) FROM drawing_validation_results v WHERE v.design_revision_id = dr.id) as findings,
            (SELECT COUNT(*) FROM drawing_validation_results v WHERE v.design_revision_id = dr.id AND v.status = 'BLOCK') as blocks,
            (SELECT COUNT(*) FROM drawing_validation_results v WHERE v.design_revision_id = dr.id AND v.status = 'WARN') as warns
        FROM design_revisions dr
        WHERE dr.artifact_id = %s::uuid
        ORDER BY dr.revision_sequence
        """,
        (artifact_id,),
    )

    session_map = {s["revision_code"]: s for s in sessions}

    print(f"\n  {'Rev':<4} {'File':<22} {'Ent':>4} {'Dim':>4} {'BLOCK':>6} {'WARN':>5} {'Risk':<8} Session")
    print(f"  {'─'*4} {'─'*22} {'─'*4} {'─'*4} {'─'*6} {'─'*5} {'─'*8} {'─'*42}")
    for r in rows:
        s = session_map.get(r["revision_code"], {})
        print(
            f"  {r['revision_code']:<4} {(r['source_filename'] or '—'):<22} "
            f"{r['entities']:>4} {r['dimensions']:>4} "
            f"{r['blocks']:>6} {r['warns']:>5} "
            f"{s.get('risk_status','—'):<8} "
            f"{s.get('session_number','—')}"
        )

    rule_count = fetch_one("SELECT COUNT(*) as n FROM engineering_review_rules")["n"]
    base_count = fetch_one(
        "SELECT COUNT(*) as n FROM drawing_reference_baselines WHERE artifact_id = %s::uuid",
        (artifact_id,),
    )["n"]
    pair_count = fetch_one(
        "SELECT COUNT(*) as n FROM drawing_revision_pairs WHERE artifact_id = %s::uuid",
        (artifact_id,),
    )["n"]

    print(f"\n  Rules: {rule_count}   Baselines: {base_count}   Revision pairs: {pair_count}")
    print(f"\n  → http://localhost:8000/design-artifacts/{artifact_id}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _banner("HORN-HSG-2705 Bracket Demo Seed")

    _step(1, "Wiping existing data …")
    wipe_existing_data()

    _step(2, "Resetting rule catalog (15 rules) …")
    reset_rule_catalog()

    _step(3, "Seeding artifact + 3 revisions + drawing extraction + validation …")
    result = seed_mock_bracket_review_data()
    artifact_id = str(result["artifact"]["id"])
    print(f"    Artifact: {artifact_id}")
    print(f"    Revisions created: {result['revision_count']}")

    _step(4, "Creating review sessions (R1, R2, R3) …")
    sessions = create_all_sessions(artifact_id)
    for s in sessions:
        print(f"    {s['revision_code']}  {s['risk_status']:<6}  {s['session_number']}")

    print_summary(artifact_id, sessions)


if __name__ == "__main__":
    main()
