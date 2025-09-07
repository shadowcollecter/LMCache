# SPDX-License-Identifier: Apache-2.0
"""Tests for memory trace functionality"""

import os
import tempfile
import csv
from pathlib import Path
import pytest

from lmcache.memory_trace import (
    MemoryTraceEvent,
    MemoryTraceWriter,
    MemoryTraceManager,
    get_memory_trace_manager,
    initialize_memory_trace_from_env
)


class TestMemoryTraceEvent:
    """Test MemoryTraceEvent class"""
    
    def test_event_creation(self):
        """Test creating a memory trace event"""
        event = MemoryTraceEvent(
            timestamp_ns=1234567890,
            event="kv_cache_hit",
            request_id="req-001",
            seq_id=0,
            address="0x7f2a000000",
            size_bytes=2097152,
            chunk_size=128,
            kv_dtype="fp16",
            layer_count=32,
            head_count=32,
            token_count=128,
            extra={"test": "data"}
        )
        
        assert event.timestamp_ns == 1234567890
        assert event.event == "kv_cache_hit"
        assert event.schema_version == "1.0"
    
    def test_to_csv_row(self):
        """Test converting event to CSV row"""
        event = MemoryTraceEvent(
            timestamp_ns=1234567890,
            event="kv_cache_hit",
            request_id="req-001",
            seq_id=0,
            address="0x7f2a000000",
            size_bytes=2097152,
            extra={"test": "data"}
        )
        
        row = event.to_csv_row()
        assert row["timestamp_ns"] == 1234567890
        assert row["event"] == "kv_cache_hit"
        assert row["extra"] == '{"test": "data"}'
        
        # Test with include_fields
        row_filtered = event.to_csv_row(
            include_fields=["timestamp_ns", "event", "size_bytes"]
        )
        assert len(row_filtered) == 3
        assert "address" not in row_filtered


class TestMemoryTraceWriter:
    """Test MemoryTraceWriter class"""
    
    def test_writer_creation(self):
        """Test creating a trace writer"""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = MemoryTraceWriter(
                output_dir=tmpdir,
                rotate_max_bytes=1024,
                rotate_interval_sec=0
            )
            
            # Check that file was created
            files = list(Path(tmpdir).glob("kv_cache_memory_trace_*.csv"))
            assert len(files) == 1
            
            # Check headers
            with open(files[0], 'r') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                assert "timestamp_ns" in headers
                assert "event" in headers
                assert "address" in headers
            
            writer.close()
    
    def test_write_event(self):
        """Test writing events"""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = MemoryTraceWriter(output_dir=tmpdir)
            
            # Write an event
            event = MemoryTraceEvent(
                timestamp_ns=1234567890,
                event="kv_cache_hit",
                request_id="req-001",
                seq_id=0,
                address="0x7f2a000000",
                size_bytes=2097152
            )
            writer.write_event(event)
            writer.close()
            
            # Read back and verify
            files = list(Path(tmpdir).glob("kv_cache_memory_trace_*.csv"))
            with open(files[0], 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1
                assert rows[0]["event"] == "kv_cache_hit"
                assert rows[0]["size_bytes"] == "2097152"
    
    def test_file_rotation(self):
        """Test file rotation by size"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Small rotation size to trigger rotation
            writer = MemoryTraceWriter(
                output_dir=tmpdir,
                rotate_max_bytes=500  # Very small to force rotation
            )
            
            # Write multiple events
            for i in range(10):
                event = MemoryTraceEvent(
                    timestamp_ns=1234567890 + i,
                    event="kv_cache_hit",
                    request_id=f"req-{i:03d}",
                    seq_id=i,
                    address=f"0x{i:016x}",
                    size_bytes=1024 * 1024,
                    extra={"index": i, "data": "x" * 100}  # Make it bigger
                )
                writer.write_event(event)
            
            writer.close()
            
            # Should have multiple files due to rotation
            files = list(Path(tmpdir).glob("kv_cache_memory_trace_*.csv"))
            assert len(files) > 1


class TestMemoryTraceManager:
    """Test MemoryTraceManager class"""
    
    def test_singleton(self):
        """Test that manager is a singleton"""
        manager1 = get_memory_trace_manager()
        manager2 = get_memory_trace_manager()
        assert manager1 is manager2
    
    def test_disabled_by_default(self):
        """Test that tracing is disabled by default"""
        manager = MemoryTraceManager()
        assert not manager.enabled
    
    def test_initialize_and_record(self):
        """Test initializing and recording events"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryTraceManager()
            manager.initialize(
                enabled=True,
                output_dir=tmpdir
            )
            
            assert manager.enabled
            
            # Record some events
            manager.record_kv_cache_hit(
                request_id="test-req",
                seq_id=0,
                address=0x1000,
                size_bytes=4096,
                chunk_size=128
            )
            
            manager.record_kv_cache_offload(
                request_id="test-req",
                seq_id=1,
                address=0x2000,
                size_bytes=8192,
                chunk_size=128
            )
            
            # Shutdown to flush
            manager.shutdown()
            
            # Verify files were created
            files = list(Path(tmpdir).glob("kv_cache_memory_trace_*.csv"))
            assert len(files) > 0
    
    def test_env_initialization(self):
        """Test initialization from environment variables"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set environment variables
            os.environ["LMC_TRACE_ENABLE"] = "true"
            os.environ["LMC_TRACE_OUTPUT_DIR"] = tmpdir
            os.environ["LMC_TRACE_INCLUDE_FIELDS"] = "timestamp_ns,event,size_bytes"
            
            try:
                # Initialize from env
                initialize_memory_trace_from_env()
                
                manager = get_memory_trace_manager()
                assert manager.enabled
                
                # Record an event
                manager.record_memory_allocation(
                    address=0x3000,
                    size_bytes=16384
                )
                
                manager.shutdown()
                
                # Verify file
                files = list(Path(tmpdir).glob("kv_cache_memory_trace_*.csv"))
                assert len(files) > 0
                
                # Check that only specified fields are included
                with open(files[0], 'r') as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames
                    assert len(headers) == 3
                    assert "timestamp_ns" in headers
                    assert "event" in headers
                    assert "size_bytes" in headers
                    assert "address" not in headers  # Not included
                
            finally:
                # Clean up env vars
                del os.environ["LMC_TRACE_ENABLE"]
                del os.environ["LMC_TRACE_OUTPUT_DIR"]
                del os.environ["LMC_TRACE_INCLUDE_FIELDS"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
