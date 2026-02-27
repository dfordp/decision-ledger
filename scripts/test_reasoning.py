"""
Test the reasoning engine with real data.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.reasoning import reason_about_requirement
from app.database import fetch_all

def test_reasoning():
    """Test reasoning for Tender #1"""
    
    print("=" * 70)
    print("DecisionLedger - Reasoning Engine Test")
    print("=" * 70)
    print()
    
    # Get Tender #1 dimensions
    tender_id = 1
    dimensions = ['MAINTENANCE_DURATION', 'WARRANTY_YEARS', 'PAYMENT_TERMS', 'LOCAL_CONTENT_PERCENT']
    
    for dimension_key in dimensions:
        print(f"\nTesting: {dimension_key}")
        print("-" * 70)
        
        try:
            result = reason_about_requirement(tender_id, dimension_key)
            
            print(f"Requirement: {result.requirement.required_value} {result.dimension_unit} ({result.requirement.strictness})")
            print(f"Policy: {result.policy.min_value}-{result.policy.max_value} (flexibility: {result.policy.flexibility})")
            print(f"\nRecommendation: {result.recommended_value} {result.dimension_unit}")
            print(f"Status: {result.status}")
            print(f"Confidence: {result.confidence:.0%}")
            
            print(f"\nReasoning:")
            for i, reason in enumerate(result.reasoning, 1):
                print(f"  {i}. {reason}")
            
            print(f"\nEvidence ({len(result.evidence)} similar decisions):")
            for e in result.evidence[:3]:
                print(f"  - {e.outcome}: {e.tender_name}")
                print(f"    Offered: {e.offered_value}, Similarity: {e.similarity:.2%}")
            
            print()
            
        except Exception as e:
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print("=" * 70)
    print("✓ Reasoning test complete")
    print("=" * 70)

if __name__ == "__main__":
    test_reasoning()