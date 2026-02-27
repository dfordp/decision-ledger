"""
Seed script for DecisionLedger POC.
Generates realistic historical proposals, decisions, policies, and tenders.
"""

import sys
import os
from datetime import datetime, timedelta
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import (
    execute_query, insert_and_return_id, fetch_one_value, get_connection
)
from app.embeddings import (
    generate_policy_embedding,
    generate_proposal_embedding,
    generate_decision_embedding,
    generate_requirement_embedding
)

def clear_existing_data():
    """Clear all data from tables (for clean re-seeding)"""
    print("Clearing existing data...")
    
    tables = [
        'proposal_decisions',
        'proposals',
        'tender_requirements',
        'tenders',
        'vendor_policy',
        'vendors'
    ]
    
    for table in tables:
        execute_query(f"DELETE FROM {table}")
    
    print("✓ Existing data cleared\n")

def seed_vendor():
    """Create the single vendor for this POC"""
    print("Seeding vendor...")
    
    vendor_id = insert_and_return_id(
        "INSERT INTO vendors (name) VALUES (%s)",
        ("AcmeCorp Industrial",)
    )
    
    print(f"✓ Created vendor: AcmeCorp Industrial (ID: {vendor_id})\n")
    return vendor_id

def seed_vendor_policies(vendor_id: int):
    """Create vendor policies across different domains"""
    print("Seeding vendor policies...")
    
    # Get dimension IDs
    dimensions = {
        'MAINTENANCE_DURATION': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'MAINTENANCE_DURATION'"
        ),
        'WARRANTY_YEARS': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'WARRANTY_YEARS'"
        ),
        'PAYMENT_TERMS': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'PAYMENT_TERMS'"
        ),
        'LOCAL_CONTENT_PERCENT': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'LOCAL_CONTENT_PERCENT'"
        )
    }
    
    policies = [
        # RAIL_HVAC domain
        {
            'dimension_id': dimensions['MAINTENANCE_DURATION'],
            'dimension_name': 'Maintenance Duration',
            'domain': 'RAIL_HVAC',
            'min_value': 3.0,
            'max_value': 5.0,
            'default_value': 4.0,
            'flexibility': 'negotiable',
            'notes': 'Our rail HVAC maintenance capacity is optimized for 3-5 year contracts. Can extend to 6 years with advance planning.'
        },
        {
            'dimension_id': dimensions['WARRANTY_YEARS'],
            'dimension_name': 'Warranty Period',
            'domain': 'RAIL_HVAC',
            'min_value': 2.0,
            'max_value': 3.0,
            'default_value': 2.0,
            'flexibility': 'fixed',
            'notes': 'Standard warranty coverage for HVAC systems. Component manufacturers limit our flexibility here.'
        },
        {
            'dimension_id': dimensions['PAYMENT_TERMS'],
            'dimension_name': 'Payment Terms',
            'domain': 'RAIL_HVAC',
            'min_value': 30.0,
            'max_value': 90.0,
            'default_value': 60.0,
            'flexibility': 'flexible',
            'notes': 'Cash flow allows flexibility on payment terms for rail projects.'
        },
        {
            'dimension_id': dimensions['LOCAL_CONTENT_PERCENT'],
            'dimension_name': 'Local Content',
            'domain': 'RAIL_HVAC',
            'min_value': 35.0,
            'max_value': 55.0,
            'default_value': 45.0,
            'flexibility': 'negotiable',
            'notes': 'Local supply chain well-established for rail HVAC. Can push to 60% with advance notice.'
        },
        
        # POWER_GRID domain
        {
            'dimension_id': dimensions['MAINTENANCE_DURATION'],
            'dimension_name': 'Maintenance Duration',
            'domain': 'POWER_GRID',
            'min_value': 2.0,
            'max_value': 4.0,
            'default_value': 3.0,
            'flexibility': 'fixed',
            'notes': 'Power grid maintenance requires specialized team. Limited capacity beyond 4 years.'
        },
        {
            'dimension_id': dimensions['WARRANTY_YEARS'],
            'dimension_name': 'Warranty Period',
            'domain': 'POWER_GRID',
            'min_value': 1.0,
            'max_value': 2.0,
            'default_value': 1.0,
            'flexibility': 'fixed',
            'notes': 'Power infrastructure has higher risk. Conservative warranty policy.'
        },
        {
            'dimension_id': dimensions['PAYMENT_TERMS'],
            'dimension_name': 'Payment Terms',
            'domain': 'POWER_GRID',
            'min_value': 30.0,
            'max_value': 60.0,
            'default_value': 45.0,
            'flexibility': 'negotiable',
            'notes': 'Power projects have tighter cash requirements.'
        },
        {
            'dimension_id': dimensions['LOCAL_CONTENT_PERCENT'],
            'dimension_name': 'Local Content',
            'domain': 'POWER_GRID',
            'min_value': 25.0,
            'max_value': 40.0,
            'default_value': 30.0,
            'flexibility': 'negotiable',
            'notes': 'Specialized power components often imported. Limited local options.'
        },
        
        # GLOBAL fallback policies
        {
            'dimension_id': dimensions['MAINTENANCE_DURATION'],
            'dimension_name': 'Maintenance Duration',
            'domain': 'GLOBAL',
            'min_value': 2.0,
            'max_value': 5.0,
            'default_value': 3.0,
            'flexibility': 'flexible',
            'notes': 'Default maintenance policy across all domains.'
        },
        {
            'dimension_id': dimensions['WARRANTY_YEARS'],
            'dimension_name': 'Warranty Period',
            'domain': 'GLOBAL',
            'min_value': 1.0,
            'max_value': 3.0,
            'default_value': 2.0,
            'flexibility': 'negotiable',
            'notes': 'Standard warranty policy.'
        },
        {
            'dimension_id': dimensions['PAYMENT_TERMS'],
            'dimension_name': 'Payment Terms',
            'domain': 'GLOBAL',
            'min_value': 30.0,
            'max_value': 90.0,
            'default_value': 60.0,
            'flexibility': 'flexible',
            'notes': 'Standard payment terms across domains.'
        },
        {
            'dimension_id': dimensions['LOCAL_CONTENT_PERCENT'],
            'dimension_name': 'Local Content',
            'domain': 'GLOBAL',
            'min_value': 30.0,
            'max_value': 50.0,
            'default_value': 40.0,
            'flexibility': 'negotiable',
            'notes': 'Default local content target.'
        }
    ]
    
    for policy in policies:
        # Generate embedding
        embedding = generate_policy_embedding(
            dimension_name=policy['dimension_name'],
            domain=policy['domain'],
            min_value=policy['min_value'],
            max_value=policy['max_value'],
            flexibility=policy['flexibility'],
            notes=policy['notes']
        )
        
        # Convert embedding to PostgreSQL array format
        embedding_str = "[" + ",".join(map(str, embedding)) + "]"
        
        policy_id = insert_and_return_id(
            """
            INSERT INTO vendor_policy 
            (vendor_id, dimension_id, domain, min_value, max_value, default_value, flexibility, notes, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
            """,
            (
                vendor_id,
                policy['dimension_id'],
                policy['domain'],
                policy['min_value'],
                policy['max_value'],
                policy['default_value'],
                policy['flexibility'],
                policy['notes'],
                embedding_str
            )
        )
        
        print(f"  ✓ Policy: {policy['dimension_name']} / {policy['domain']}")
    
    print(f"✓ Created {len(policies)} vendor policies\n")

def seed_historical_proposals(vendor_id: int):
    """Create historical proposals with decisions"""
    print("Seeding historical proposals...")
    
    # Get dimension IDs
    dimensions = {
        'MAINTENANCE_DURATION': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'MAINTENANCE_DURATION'"
        ),
        'WARRANTY_YEARS': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'WARRANTY_YEARS'"
        ),
        'PAYMENT_TERMS': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'PAYMENT_TERMS'"
        ),
        'LOCAL_CONTENT_PERCENT': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'LOCAL_CONTENT_PERCENT'"
        )
    }
    
    proposals = [
        # WON proposals
        {
            'tender_name': '2023 Metro North Rail HVAC System',
            'domain': 'RAIL_HVAC',
            'outcome': 'WON',
            'outcome_reason': 'Our 5-year maintenance commitment and competitive pricing won the contract.',
            'submitted_at': datetime(2023, 3, 15),
            'decisions': [
                {
                    'dimension_id': dimensions['MAINTENANCE_DURATION'],
                    'dimension_name': 'Maintenance Duration',
                    'offered_value': 5.0,
                    'justification': 'Offered 5 years to match client preference and demonstrate long-term commitment.',
                    'source_excerpt': 'Client emphasized importance of extended maintenance. We positioned this as a strength given our rail HVAC track record.'
                },
                {
                    'dimension_id': dimensions['WARRANTY_YEARS'],
                    'dimension_name': 'Warranty Period',
                    'offered_value': 3.0,
                    'justification': 'Extended warranty to maximum policy allows to strengthen proposal.',
                    'source_excerpt': 'Pushed warranty to 3 years despite cost impact. Confidence in our HVAC quality justified the risk.'
                },
                {
                    'dimension_id': dimensions['PAYMENT_TERMS'],
                    'dimension_name': 'Payment Terms',
                    'offered_value': 60.0,
                    'justification': 'Standard 60-day terms accepted by client.',
                    'source_excerpt': 'No pressure on payment terms. Went with standard 60 days.'
                },
                {
                    'dimension_id': dimensions['LOCAL_CONTENT_PERCENT'],
                    'dimension_name': 'Local Content',
                    'offered_value': 48.0,
                    'justification': 'Exceeded minimum requirement to score higher on local content criteria.',
                    'source_excerpt': 'Client weighted local content heavily. Leveraged our regional supplier network to reach 48%.'
                }
            ]
        },
        {
            'tender_name': '2024 Eastern Suburbs Rail Climate Control',
            'domain': 'RAIL_HVAC',
            'outcome': 'WON',
            'outcome_reason': 'Strong technical proposal with balanced maintenance terms.',
            'submitted_at': datetime(2024, 6, 20),
            'decisions': [
                {
                    'dimension_id': dimensions['MAINTENANCE_DURATION'],
                    'dimension_name': 'Maintenance Duration',
                    'offered_value': 4.0,
                    'justification': 'Balanced commitment within policy comfort zone.',
                    'source_excerpt': '4 years aligned with our capacity planning and client expectations.'
                },
                {
                    'dimension_id': dimensions['WARRANTY_YEARS'],
                    'dimension_name': 'Warranty Period',
                    'offered_value': 2.0,
                    'justification': 'Standard warranty sufficient for this project scale.',
                    'source_excerpt': 'Standard 2-year warranty. No client pressure for extension.'
                },
                {
                    'dimension_id': dimensions['PAYMENT_TERMS'],
                    'dimension_name': 'Payment Terms',
                    'offered_value': 75.0,
                    'justification': 'Client requested extended terms, we accommodated within policy.',
                    'source_excerpt': 'Client needed 75-day terms for budget cycles. Acceptable under our flexible payment policy.'
                },
                {
                    'dimension_id': dimensions['LOCAL_CONTENT_PERCENT'],
                    'dimension_name': 'Local Content',
                    'offered_value': 45.0,
                    'justification': 'Met requirement with standard supply chain.',
                    'source_excerpt': 'Our default 45% local content met the 40% requirement comfortably.'
                }
            ]
        },
        {
            'tender_name': '2024 Central Power Grid Expansion',
            'domain': 'POWER_GRID',
            'outcome': 'WON',
            'outcome_reason': 'Technical excellence and realistic commitments.',
            'submitted_at': datetime(2024, 9, 10),
            'decisions': [
                {
                    'dimension_id': dimensions['MAINTENANCE_DURATION'],
                    'dimension_name': 'Maintenance Duration',
                    'offered_value': 3.0,
                    'justification': 'Standard 3-year maintenance for power infrastructure.',
                    'source_excerpt': 'Power grid projects typically 3 years. Matches our specialized team capacity.'
                },
                {
                    'dimension_id': dimensions['WARRANTY_YEARS'],
                    'dimension_name': 'Warranty Period',
                    'offered_value': 2.0,
                    'justification': 'Extended to maximum policy for competitive edge.',
                    'source_excerpt': 'Pushed to 2-year warranty despite higher risk. Needed competitive advantage.'
                },
                {
                    'dimension_id': dimensions['PAYMENT_TERMS'],
                    'dimension_name': 'Payment Terms',
                    'offered_value': 45.0,
                    'justification': 'Standard terms for power sector.',
                    'source_excerpt': 'Government client preferred shorter payment cycles. 45 days worked for both parties.'
                }
            ]
        },
        
        # LOST proposals (we submitted but didn't win)
        {
            'tender_name': '2023 Southern Rail Ventilation Upgrade',
            'domain': 'RAIL_HVAC',
            'outcome': 'LOST',
            'outcome_reason': 'Competitor offered longer maintenance period at lower cost.',
            'submitted_at': datetime(2023, 11, 5),
            'decisions': [
                {
                    'dimension_id': dimensions['MAINTENANCE_DURATION'],
                    'dimension_name': 'Maintenance Duration',
                    'offered_value': 3.0,
                    'justification': 'Offered minimum policy duration due to capacity constraints.',
                    'source_excerpt': 'Team capacity limited. Could only commit to 3 years despite client preference for 5+.'
                },
                {
                    'dimension_id': dimensions['WARRANTY_YEARS'],
                    'dimension_name': 'Warranty Period',
                    'offered_value': 2.0,
                    'justification': 'Standard warranty offered.',
                    'source_excerpt': 'Standard 2-year warranty. In retrospect, should have extended to 3 years.'
                },
                {
                    'dimension_id': dimensions['LOCAL_CONTENT_PERCENT'],
                    'dimension_name': 'Local Content',
                    'offered_value': 38.0,
                    'justification': 'Met minimum but competitor exceeded significantly.',
                    'source_excerpt': 'Offered 38% local content. Competitor went to 55% which was decisive.'
                }
            ]
        },
        {
            'tender_name': '2024 Western Power Substation',
            'domain': 'POWER_GRID',
            'outcome': 'LOST',
            'outcome_reason': 'Lost on technical evaluation, not commercial terms.',
            'submitted_at': datetime(2024, 4, 12),
            'decisions': [
                {
                    'dimension_id': dimensions['MAINTENANCE_DURATION'],
                    'dimension_name': 'Maintenance Duration',
                    'offered_value': 2.0,
                    'justification': 'Minimum maintenance due to specialized requirements.',
                    'source_excerpt': 'Substation work requires specialist team. Limited to 2 years.'
                },
                {
                    'dimension_id': dimensions['WARRANTY_YEARS'],
                    'dimension_name': 'Warranty Period',
                    'offered_value': 1.0,
                    'justification': 'Conservative warranty for high-risk infrastructure.',
                    'source_excerpt': 'High voltage work carries significant risk. Held at 1-year warranty.'
                }
            ]
        },
        
        # REJECTED proposals (we withdrew before submission)
        {
            'tender_name': '2024 Airport Rail Link HVAC',
            'domain': 'RAIL_HVAC',
            'outcome': 'REJECTED',
            'outcome_reason': 'Payment terms unacceptable (120+ days), withdrew from tender.',
            'submitted_at': datetime(2024, 2, 28),
            'decisions': [
                {
                    'dimension_id': dimensions['PAYMENT_TERMS'],
                    'dimension_name': 'Payment Terms',
                    'offered_value': 90.0,
                    'justification': 'Client demanded 120 days, we countered with 90, ultimately withdrew.',
                    'source_excerpt': 'Client insisted on 120-day terms which exceeds our cash flow tolerance. Could only offer 90 days maximum. Declined to proceed.'
                },
                {
                    'dimension_id': dimensions['MAINTENANCE_DURATION'],
                    'dimension_name': 'Maintenance Duration',
                    'offered_value': 6.0,
                    'justification': 'Client required 6 years which stretches our capacity.',
                    'source_excerpt': 'Required 6-year maintenance exceeded our comfort zone. Combined with payment terms, made project unviable.'
                }
            ]
        },
        {
            'tender_name': '2023 Industrial Complex Power',
            'domain': 'POWER_GRID',
            'outcome': 'REJECTED',
            'outcome_reason': 'Warranty requirements exceeded our risk tolerance.',
            'submitted_at': datetime(2023, 8, 18),
            'decisions': [
                {
                    'dimension_id': dimensions['WARRANTY_YEARS'],
                    'dimension_name': 'Warranty Period',
                    'offered_value': 2.0,
                    'justification': 'Client demanded 5-year warranty, we could not justify risk.',
                    'source_excerpt': 'Client required 5-year warranty on power infrastructure. Our maximum is 2 years. Risk assessment showed unacceptable exposure. Withdrew.'
                },
                {
                    'dimension_id': dimensions['LOCAL_CONTENT_PERCENT'],
                    'dimension_name': 'Local Content',
                    'offered_value': 25.0,
                    'justification': 'Client required 60% local content, beyond our supply chain capability.',
                    'source_excerpt': 'Required 60% local content impossible with specialized power equipment. Our maximum is 40%. Rejected.'
                }
            ]
        }
    ]
    
    for proposal_data in proposals:
        # Generate proposal embedding
        proposal_embedding = generate_proposal_embedding(
            tender_name=proposal_data['tender_name'],
            domain=proposal_data['domain'],
            outcome=proposal_data['outcome'],
            outcome_reason=proposal_data['outcome_reason']
        )
        
        proposal_embedding_str = "[" + ",".join(map(str, proposal_embedding)) + "]"
        
        # Insert proposal
        proposal_id = insert_and_return_id(
            """
            INSERT INTO proposals 
            (vendor_id, tender_name, domain, outcome, outcome_reason, submitted_at, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
            """,
            (
                vendor_id,
                proposal_data['tender_name'],
                proposal_data['domain'],
                proposal_data['outcome'],
                proposal_data['outcome_reason'],
                proposal_data['submitted_at'],
                proposal_embedding_str
            )
        )
        
        print(f"  ✓ Proposal: {proposal_data['tender_name']} ({proposal_data['outcome']})")
        
        # Insert proposal decisions
        for decision in proposal_data['decisions']:
            decision_embedding = generate_decision_embedding(
                dimension_name=decision['dimension_name'],
                offered_value=float(decision['offered_value']),
                justification=decision['justification'],
                domain=proposal_data['domain'],
                outcome=proposal_data['outcome'],
                source_excerpt=decision['source_excerpt']
            )
            
            decision_embedding_str = "[" + ",".join(map(str, decision_embedding)) + "]"
            
            insert_and_return_id(
                """
                INSERT INTO proposal_decisions
                (proposal_id, dimension_id, offered_value, justification, source_excerpt, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector)
                """,
                (
                    proposal_id,
                    decision['dimension_id'],
                    decision['offered_value'],
                    decision['justification'],
                    decision['source_excerpt'],
                    decision_embedding_str
                )
            )
        
        print(f"    → {len(proposal_data['decisions'])} decisions recorded")
    
    print(f"\n✓ Created {len(proposals)} historical proposals\n")

def seed_demo_tenders():
    """Create two demo tenders for live evaluation"""
    print("Seeding demo tenders...")
    
    # Get dimension IDs
    dimensions = {
        'MAINTENANCE_DURATION': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'MAINTENANCE_DURATION'"
        ),
        'WARRANTY_YEARS': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'WARRANTY_YEARS'"
        ),
        'PAYMENT_TERMS': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'PAYMENT_TERMS'"
        ),
        'LOCAL_CONTENT_PERCENT': fetch_one_value(
            "SELECT id FROM evaluation_dimension WHERE key = 'LOCAL_CONTENT_PERCENT'"
        )
    }
    
    tenders = [
        {
            'name': '2025 Regional Rail HVAC Modernization',
            'domain': 'RAIL_HVAC',
            'year': 2025,
            'status': 'OPEN',
            'requirements': [
                {
                    'dimension_id': dimensions['MAINTENANCE_DURATION'],
                    'dimension_name': 'Maintenance Duration',
                    'required_value': 4.0,
                    'strictness': 'mandatory',
                    'description': 'Minimum 4-year maintenance contract required to ensure system reliability through warranty period.'
                },
                {
                    'dimension_id': dimensions['WARRANTY_YEARS'],
                    'dimension_name': 'Warranty Period',
                    'required_value': 2.0,
                    'strictness': 'preferred',
                    'description': 'Preference for 2+ year warranty but not mandatory.'
                },
                {
                    'dimension_id': dimensions['PAYMENT_TERMS'],
                    'dimension_name': 'Payment Terms',
                    'required_value': 90.0,
                    'strictness': 'mandatory',
                    'description': 'Government budget cycles require 90-day payment terms minimum.'
                },
                {
                    'dimension_id': dimensions['LOCAL_CONTENT_PERCENT'],
                    'dimension_name': 'Local Content',
                    'required_value': 40.0,
                    'strictness': 'preferred',
                    'description': 'Target 40% local content for economic development goals.'
                }
            ]
        },
        {
            'name': '2025 City Metro Expansion - Climate Control',
            'domain': 'RAIL_HVAC',
            'year': 2025,
            'status': 'OPEN',
            'requirements': [
                {
                    'dimension_id': dimensions['MAINTENANCE_DURATION'],
                    'dimension_name': 'Maintenance Duration',
                    'required_value': 6.0,
                    'strictness': 'mandatory',
                    'description': 'Extended 6-year maintenance required for whole-of-life support model.'
                },
                {
                    'dimension_id': dimensions['WARRANTY_YEARS'],
                    'dimension_name': 'Warranty Period',
                    'required_value': 3.0,
                    'strictness': 'mandatory',
                    'description': 'Minimum 3-year warranty mandatory for this critical infrastructure.'
                },
                {
                    'dimension_id': dimensions['PAYMENT_TERMS'],
                    'dimension_name': 'Payment Terms',
                    'required_value': 60.0,
                    'strictness': 'preferred',
                    'description': 'Standard 60-day payment terms preferred.'
                },
                {
                    'dimension_id': dimensions['LOCAL_CONTENT_PERCENT'],
                    'dimension_name': 'Local Content',
                    'required_value': 50.0,
                    'strictness': 'preferred',
                    'description': 'Target 50% local content for job creation.'
                }
            ]
        }
    ]
    
    for tender_data in tenders:
        # Insert tender
        tender_id = insert_and_return_id(
            """
            INSERT INTO tenders (name, domain, year, status)
            VALUES (%s, %s, %s, %s)
            """,
            (tender_data['name'], tender_data['domain'], tender_data['year'], tender_data['status'])
        )
        
        print(f"  ✓ Tender: {tender_data['name']}")
        
        # Insert requirements
        for req in tender_data['requirements']:
            req_embedding = generate_requirement_embedding(
                dimension_name=req['dimension_name'],
                required_value=float(req['required_value']),
                strictness=req['strictness'],
                domain=tender_data['domain'],
                description=req['description']
            )
            
            req_embedding_str = "[" + ",".join(map(str, req_embedding)) + "]"
            
            insert_and_return_id(
                """
                INSERT INTO tender_requirements
                (tender_id, dimension_id, required_value, strictness, description, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector)
                """,
                (
                    tender_id,
                    req['dimension_id'],
                    req['required_value'],
                    req['strictness'],
                    req['description'],
                    req_embedding_str
                )
            )
        
        print(f"    → {len(tender_data['requirements'])} requirements added")
    
    print(f"\n✓ Created {len(tenders)} demo tenders\n")

def main():
    """Main seed execution"""
    print("=" * 60)
    print("DecisionLedger - Seed Data Generator")
    print("=" * 60)
    print()
    
    try:
        # Clear existing data
        clear_existing_data()
        
        # Seed in order (respecting foreign keys)
        vendor_id = seed_vendor()
        seed_vendor_policies(vendor_id)
        seed_historical_proposals(vendor_id)
        seed_demo_tenders()
        
        print("=" * 60)
        print("✓ SEEDING COMPLETE")
        print("=" * 60)
        print()
        print("Next steps:")
        print("1. Run: uvicorn app.main:app --reload")
        print("2. Open: http://localhost:8000")
        print("3. Explore:")
        print("   - /history (view historical proposals)")
        print("   - /tender/1 (evaluate first demo tender)")
        print("   - /tender/2 (see persistence in action)")
        print()
        
    except Exception as e:
        print(f"\n✗ Seeding failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()