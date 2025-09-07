#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Integration test for memory trace functionality.
Run this script to verify that memory tracing is working correctly.
"""

import os
import sys
import tempfile
import csv
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lmcache.memory_trace import (
    get_memory_trace_manager,
    initialize_memory_trace_from_env
)


def test_basic_trace():
    """Test basic memory trace functionality"""
    print("Testing basic memory trace functionality...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Using temporary directory: {tmpdir}")
        
        # Set up environment
        os.environ["LMC_TRACE_ENABLE"] = "true"
        os.environ["LMC_TRACE_OUTPUT_DIR"] = tmpdir
        
        # Initialize
        initialize_memory_trace_from_env()
        manager = get_memory_trace_manager()
        
        print("Recording test events...")
        
        # Record some test events
        for i in range(5):
            manager.record_kv_cache_hit(
                request_id=f"test-req-{i}",
                seq_id=i,
                address=0x1000 + i * 0x1000,
                size_bytes=4096 * (i + 1),
                chunk_size=256,
                kv_dtype="fp16",
                layer_count=32,
                head_count=32,
                token_count=256
            )
        
        for i in range(3):
            manager.record_kv_cache_offload(
                request_id=f"test-req-{i}",
                seq_id=i + 10,
                address=0x10000 + i * 0x1000,
                size_bytes=8192 * (i + 1),
                chunk_size=256,
                extra={"reason": "eviction"}
            )
        
        # Shutdown to flush
        manager.shutdown()
        
        # Check results
        print("\nChecking output files...")
        files = list(Path(tmpdir).glob("kv_cache_memory_trace_*.csv"))
        
        if not files:
            print("ERROR: No trace files generated!")
            return False
        
        print(f"Found {len(files)} trace file(s)")
        
        # Analyze the trace file
        total_events = 0
        hit_events = 0
        offload_events = 0
        
        for file in files:
            print(f"\nAnalyzing {file.name}...")
            with open(file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_events += 1
                    if row['event'] == 'kv_cache_hit':
                        hit_events += 1
                    elif row['event'] == 'kv_cache_offload_to_host':
                        offload_events += 1
        
        print(f"\nSummary:")
        print(f"  Total events: {total_events}")
        print(f"  Hit events: {hit_events}")
        print(f"  Offload events: {offload_events}")
        
        # Verify counts
        if hit_events != 5 or offload_events != 3:
            print("ERROR: Event counts don't match expected values!")
            return False
        
        print("\nSUCCESS: All tests passed!")
        return True


def main():
    """Main test function"""
    print("LMCache Memory Trace Integration Test")
    print("=" * 50)
    
    try:
        success = test_basic_trace()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nERROR: Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Clean up environment
        for key in ["LMC_TRACE_ENABLE", "LMC_TRACE_OUTPUT_DIR"]:
            if key in os.environ:
                del os.environ[key]


if __name__ == "__main__":
    main()
