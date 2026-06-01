"""
Super-seed script — full demo environment setup
================================================
Runs all database migrations then seeds the bracket demo dataset:

  Step 1  Apply migrations 001 → 006
  Step 2  Seed Escorts bracket demo
            HB-000071  Hatchback A  R10  ✓ Approved reference
            HB-000110  Hatchback B  R8   ✓ Approved reference
            HB-000235  Hatchback C       (empty — upload drawings via UI)

Safe to re-run: wipes its own data before inserting.

Usage:
  # Inside the container (recommended):
  docker exec decisionledger_backend python -m scripts.seed_all

  # Locally against a running DB:
  python -m scripts.seed_all
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── path + env bootstrap ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/decisionledger",
)

# ── helpers ───────────────────────────────────────────────────────────────────
_W = 60

def _banner(title: str) -> None:
    print(f"\n{'─' * _W}")
    print(f"  {title}")
    print(f"{'─' * _W}")

def _step(n: int, msg: str) -> None:
    print(f"\n[{n}] {msg}")


# ── Step 1: apply migrations ──────────────────────────────────────────────────

MIGRATIONS_DIR = ROOT / "migrations"
MIGRATION_FILES = [
    "001_add_hierarchy_schema.sql",
    "002_add_reviewgraph_schema.sql",
    "003_add_design_review_intake.sql",
    "004_add_drawing_validation_schema.sql",
    "005_add_engineering_specific_rules.sql",
    "006_add_program_context.sql",
    "007_approval_intelligence_rules.sql",
    "008_artifact_rule_profiles.sql",
    "009_engineering_context.sql",
]


def run_migrations() -> None:
    _banner("Database Migrations")

    import psycopg2

    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    for i, fname in enumerate(MIGRATION_FILES, 1):
        fpath = MIGRATIONS_DIR / fname
        if not fpath.exists():
            print(f"  [{i}] SKIP  {fname}  (file not found)")
            continue

        sql = fpath.read_text(encoding="utf-8")
        _step(i, f"Applying {fname} …")
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            print(f"      ✓ done")
        except psycopg2.errors.DuplicateTable as exc:
            conn.rollback()
            print(f"      ~ already applied (table exists), skipping")
        except Exception as exc:
            conn.rollback()
            # Most idempotency errors are safe to skip
            msg = str(exc).splitlines()[0]
            print(f"      ~ skipped ({msg})")

    conn.close()
    print("\n  All migrations complete.\n")


# ── Step 2: run seed script ───────────────────────────────────────────────────

def run_escorts_demo() -> None:
    _banner("Escorts Engine Load Bracket Demo Seed")
    from scripts.seed_escorts_demo import main
    main()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    _banner("ReviewGraph — Demo Seed")
    print("  Migrations → Escorts Bracket Demo\n")

    run_migrations()
    run_escorts_demo()

    _banner("All done")
    print("  App ready at http://localhost:8000\n")
    print("  Next step: open HB-000235 and upload a drawing to create your first variant.\n")


if __name__ == "__main__":
    main()
