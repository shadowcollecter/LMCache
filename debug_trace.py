#!/usr/bin/env python3
"""
Debug script for LMCache memory trace - no torch dependency
"""

import os
import sys
import time

# Clear any existing environment variable to test default behavior
if 'LMC_TRACE_ENABLE' in os.environ:
    del os.environ['LMC_TRACE_ENABLE']

print("=== LMCache Memory Trace Debug Information ===")
print(f"Python version: {sys.version}")
print(f"Working directory: {os.getcwd()}")
print(f"LMC_TRACE_ENABLE: {os.environ.get('LMC_TRACE_ENABLE', 'NOT_SET')}")

# Test 1: Direct memory_trace import
print("\n1. Testing direct memory_trace import...")
try:
    from lmcache.memory_trace import (
        initialize_memory_trace_from_env,
        get_memory_trace_manager
    )
    print("✓ Successfully imported memory_trace module")
except Exception as e:
    print(f"✗ Failed to import memory_trace: {e}")
    sys.exit(1)

# Test 2: Manual initialization
print("\n2. Testing manual initialization...")
try:
    print("Calling initialize_memory_trace_from_env()...")
    initialize_memory_trace_from_env()
    print("✓ Manual initialization completed")
except Exception as e:
    print(f"✗ Manual initialization failed: {e}")

# Test 3: Check manager status
print("\n3. Checking memory trace manager...")
try:
    manager = get_memory_trace_manager()
    print(f"Manager object: {manager}")
    print(f"Manager enabled: {getattr(manager, 'enabled', 'NO_ENABLED_ATTR')}")
    print(f"Manager writer: {getattr(manager, 'writer', 'NO_WRITER_ATTR')}")
    
    if hasattr(manager, 'writer') and manager.writer:
        print(f"Writer output_dir: {manager.writer.output_dir}")
        print(f"Writer current_file: {manager.writer.current_file}")
except Exception as e:
    print(f"✗ Failed to check manager: {e}")

# Test 4: Record a test event
print("\n4. Testing event recording...")
try:
    manager = get_memory_trace_manager()
    if manager.enabled:
        print("Recording test event...")
        manager.record_memory_allocation(
            address=0x7f000000,
            size_bytes=4096,
            extra={"debug": "test_event"}
        )
        print("✓ Event recorded successfully")
        
        # Wait for background writing
        time.sleep(0.5)
        print("✓ Waited for background write")
    else:
        print("✗ Manager not enabled, cannot record events")
except Exception as e:
    print(f"✗ Failed to record event: {e}")

# Test 5: Check for trace files
print("\n5. Checking for trace files...")
try:
    import glob
    
    # Check current directory
    current_traces = glob.glob("./traces/kv_cache_memory_trace_*.csv")
    root_traces = glob.glob("kv_cache_memory_trace_*.csv")
    
    print(f"Traces in ./traces/: {current_traces}")
    print(f"Traces in current dir: {root_traces}")
    
    all_traces = current_traces + root_traces
    if all_traces:
        latest_file = max(all_traces, key=os.path.getmtime)
        print(f"Latest trace file: {latest_file}")
        
        # Check file content
        try:
            with open(latest_file, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
                print(f"File size: {len(content)} bytes")
                print(f"Line count: {len(lines)}")
                
                if len(lines) >= 1:
                    print(f"Header: {lines[0]}")
                if len(lines) >= 2:
                    print(f"First data line: {lines[1]}")
                    print("✓ File contains data")
                else:
                    print("✗ File only contains header or is empty")
                    
        except Exception as e:
            print(f"✗ Failed to read file content: {e}")
    else:
        print("✗ No trace files found")
        
        # Check if traces directory exists
        if os.path.exists("./traces"):
            print("✓ ./traces directory exists")
            trace_files = os.listdir("./traces")
            print(f"Files in ./traces: {trace_files}")
        else:
            print("✗ ./traces directory does not exist")
            
except Exception as e:
    print(f"✗ Failed to check for files: {e}")

# Test 6: Environment and path info
print("\n6. Environment debug info...")
print(f"Current working directory: {os.getcwd()}")
print(f"Python path: {sys.path[:3]}...")  # First 3 entries
print(f"LMCache location: {os.path.dirname(__file__)}")

# Check if we can create files in current directory
try:
    test_file = "test_write_permission.tmp"
    with open(test_file, 'w') as f:
        f.write("test")
    os.remove(test_file)
    print("✓ Can write files in current directory")
except Exception as e:
    print(f"✗ Cannot write files in current directory: {e}")

print("\n=== Debug Complete ===")
print("\nTo help diagnose your issue, please share:")
print("1. The complete output above")
print("2. Your actual usage code that calls LMCache")
print("3. Whether you're running on the same machine or remote")
print("4. Any error messages from your application")
