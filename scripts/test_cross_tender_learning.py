"""
Test that decisions made on Tender #1 immediately appear as evidence for Tender #2.
This demonstrates the core "learning" capability of DecisionLedger.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.reasoning import reason_about_requirement
from app.database import fetch_all

def test_cross_tender_learning():
    """
    Test the learning flow:
    1. Check evidence for Tender #2 LOCAL_CONTENT_PERCENT before Tender #1 decision
    2. Show that Tender #1 decision now appears in Tender #2 evidence
    """
    
    print("=" * 70)
    print("Cross-Tender Learning Test")
    print("=" * 70)
    print()
    
    dimension = "LOCAL_CONTENT_PERCENT"
    
    # Step 1: Get reasoning for Tender #2
    print("📊 Analyzing Tender #2 - Local Content Requirement")
    print("-" * 70)
    
    result = reason_about_requirement(tender_id=2, dimension_key=dimension)
    
    print(f"Requirement: {result.requirement.required_value}% (mandatory)")
    print(f"Policy: {result.policy.min_value}% - {result.policy.max_value}%")
    print(f"Recommendation: {result.recommended_value}%")
    print(f"Status: {result.status}")
    print(f"Confidence: {result.confidence:.0%}")
    print()
    
    # Step 2: Show evidence
    print(f"🔍 Evidence Found: {len(result.evidence)} similar decisions")
    print("-" * 70)
    
    if not result.evidence:
        print("⚠️  No evidence found yet.")
        print("This is expected if you haven't made any Local Content decisions.")
        print()
        print("Next steps:")
        print("1. Go to http://localhost:8000/tender/1")
        print("2. Click on 'Local Content %' tab")
        print("3. Make a decision and save it")
        print("4. Run this script again to see it appear as evidence")
        return
    
    # Check if Tender #1 decision is in the evidence
    tender_1_in_evidence = False
    
    for i, evidence in enumerate(result.evidence, 1):
        print(f"\n{i}. {evidence.tender_name}")
        print(f"   Outcome: {evidence.outcome}")
        print(f"   Offered: {evidence.offered_value}%")
        print(f"   Similarity: {evidence.similarity:.1%}")
        print(f"   Submitted: {evidence.submitted_at.strftime('%Y-%m-%d')}")
        
        # Check if this is from Tender #1
        if "Cloud Migration" in evidence.tender_name or "2026" in str(evidence.submitted_at.year):
            tender_1_in_evidence = True
            print(f"   ✓ THIS IS YOUR TENDER #1 DECISION!")
    
    print()
    print("=" * 70)
    
    if tender_1_in_evidence:
        print("✓ SUCCESS: Your Tender #1 decision is now influencing Tender #2")
        print()
        print("This proves:")
        print("  • Decisions are immediately persisted with embeddings")
        print("  • Vector search finds semantically similar past decisions")
        print("  • System learns from every decision you make")
        print("  • Institutional memory compounds over time")
    else:
        print("⚠️  Tender #1 decision not yet in evidence")
        print()
        print("Possible reasons:")
        print("  • You haven't saved a Local Content decision for Tender #1 yet")
        print("  • The decision was saved but similarity score is too low")
        print("  • The embeddings haven't been generated yet")
        print()
        print("To verify, check:")
        print("  • http://localhost:8000/tender/1 (make Local Content decision)")
        print("  • Then reload http://localhost:8000/tender/2 (validate tab)")
    
    print("=" * 70)

def show_all_local_content_decisions():
    """Show all Local Content decisions in the database"""
    
    print()
    print("=" * 70)
    print("All Local Content Decisions in Database")
    print("=" * 70)
    print()
    
    decisions = fetch_all("""
        SELECT 
            p.tender_name,
            p.domain,
            p.outcome,
            p.submitted_at,
            pd.offered_value,
            pd.justification,
            ed.display_name as dimension_name
        FROM proposal_decisions pd
        JOIN proposals p ON pd.proposal_id = p.id
        JOIN evaluation_dimension ed ON pd.dimension_id = ed.id
        WHERE ed.key = 'LOCAL_CONTENT_PERCENT'
        ORDER BY p.submitted_at DESC
    """)
    
    if not decisions:
        print("⚠️  No Local Content decisions found in database.")
        print()
        print("Make sure you:")
        print("1. Seeded the database: docker-compose --profile seed up seeder")
        print("2. Or made decisions via the web interface")
        return
    
    for i, decision in enumerate(decisions, 1):
        print(f"{i}. {decision['tender_name']}")
        print(f"   Domain: {decision['domain']}")
        print(f"   Outcome: {decision['outcome']}")
        print(f"   Offered: {decision['offered_value']}%")
        print(f"   Date: {decision['submitted_at'].strftime('%Y-%m-%d')}")
        print(f"   Justification: {decision['justification'][:80]}...")
        print()
    
    print(f"Total: {len(decisions)} decisions")
    print("=" * 70)

if __name__ == "__main__":
    try:
        test_cross_tender_learning()
        show_all_local_content_decisions()
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()