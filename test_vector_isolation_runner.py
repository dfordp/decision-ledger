#!/usr/bin/env python
"""
Run vector search isolation tests to ensure proper domain and part context filtering.
Usage: python test_vector_isolation_runner.py
"""

import subprocess
import sys
import os

def run_tests():
    """Run the vector isolation test suite"""
    print("=" * 70)
    print("VECTOR SEARCH ISOLATION TEST SUITE")
    print("=" * 70)
    print("\nEnsuring that failure modes don't cross-contaminate between parts/domains...")
    print()
    
    # Run pytest with verbose output
    cmd = [
        sys.executable, "-m", "pytest",
        "test_vector_isolation.py",
        "-v",                    # Verbose
        "-s",                    # Show print statements
        "--tb=short",           # Short traceback format
        "-x"                    # Stop on first failure
    ]
    
    print(f"Running: {' '.join(cmd)}\n")
    
    result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
    
    if result.returncode == 0:
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED - Vector search isolation is working correctly")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("❌ TESTS FAILED - Vector search isolation needs fixes")
        print("=" * 70)
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
