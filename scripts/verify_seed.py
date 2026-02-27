"""
Verification script to check seeded data quality.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import fetch_all, fetch_one_value

def verify_seed_data():
    """Verify that seed data was created correctly"""
    
    print("=" * 60)
    print("DecisionLedger - Seed Data Verification")
    print("=" * 60)
    print()
    
    # Check vendor
    vendor_count = fetch_one_value("SELECT COUNT(*) FROM vendors")
    print(f"✓ Vendors: {vendor_count}")
    
    # Check policies
    policy_count = fetch_one_value("SELECT COUNT(*) FROM vendor_policy")
    policies_by_domain = fetch_all("""
        SELECT domain, COUNT(*) as count 
        FROM vendor_policy 
        GROUP BY domain 
        ORDER BY domain
    """)
    print(f"✓ Vendor Policies: {policy_count}")
    for row in policies_by_domain:
        print(f"  - {row['domain']}: {row['count']} policies")
    
    # Check proposals
    proposal_count = fetch_one_value("SELECT COUNT(*) FROM proposals")
    proposals_by_outcome = fetch_all("""
        SELECT outcome, COUNT(*) as count 
        FROM proposals 
        GROUP BY outcome 
        ORDER BY outcome
    """)
    print(f"\n✓ Proposals: {proposal_count}")
    for row in proposals_by_outcome:
        print(f"  - {row['outcome']}: {row['count']} proposals")
    
    # Check decisions
    decision_count = fetch_one_value("SELECT COUNT(*) FROM proposal_decisions")
    decisions_by_dimension = fetch_all("""
        SELECT ed.key, COUNT(*) as count
        FROM proposal_decisions pd
        JOIN evaluation_dimension ed ON pd.dimension_id = ed.id
        GROUP BY ed.key
        ORDER BY ed.key
    """)
    print(f"\n✓ Proposal Decisions: {decision_count}")
    for row in decisions_by_dimension:
        print(f"  - {row['key']}: {row['count']} decisions")
    
    # Check tenders
    tender_count = fetch_one_value("SELECT COUNT(*) FROM tenders")
    tenders = fetch_all("SELECT id, name FROM tenders ORDER BY id")
    print(f"\n✓ Tenders: {tender_count}")
    for tender in tenders:
        print(f"  - Tender #{tender['id']}: {tender['name']}")
    
    # Check requirements
    requirement_count = fetch_one_value("SELECT COUNT(*) FROM tender_requirements")
    print(f"\n✓ Tender Requirements: {requirement_count}")
    
    # Check embeddings
    print("\n✓ Embedding checks:")
    
    policies_with_embeddings = fetch_one_value(
        "SELECT COUNT(*) FROM vendor_policy WHERE embedding IS NOT NULL"
    )
    print(f"  - Policies with embeddings: {policies_with_embeddings}/{policy_count}")
    
    proposals_with_embeddings = fetch_one_value(
        "SELECT COUNT(*) FROM proposals WHERE embedding IS NOT NULL"
    )
    print(f"  - Proposals with embeddings: {proposals_with_embeddings}/{proposal_count}")
    
    decisions_with_embeddings = fetch_one_value(
        "SELECT COUNT(*) FROM proposal_decisions WHERE embedding IS NOT NULL"
    )
    print(f"  - Decisions with embeddings: {decisions_with_embeddings}/{decision_count}")
    
    requirements_with_embeddings = fetch_one_value(
        "SELECT COUNT(*) FROM tender_requirements WHERE embedding IS NOT NULL"
    )
    print(f"  - Requirements with embeddings: {requirements_with_embeddings}/{requirement_count}")
    
    print("\n" + "=" * 60)
    print("✓ VERIFICATION COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    verify_seed_data()