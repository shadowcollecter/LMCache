# SPDX-License-Identifier: Apache-2.0
"""
Memory trace module for recording KV cache operations to CSV files.
This module implements the memory trace functionality described in
KV_CACHE_MEMORY_TRACE.md
"""

import csv
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from typing import Optional, Dict, Any, List
import atexit

from lmcache.logging import init_logger

logger = init_logger(__name__)


@dataclass
class MemoryTraceEvent:
    """Represents a single memory trace event"""
    timestamp_ns: int
    event: str  # kv_cache_hit, kv_cache_offload_to_host, etc.
    request_id: str
    seq_id: int
    address: str  # Hex string with 0x prefix
    size_bytes: int
    chunk_size: Optional[int] = None
    kv_dtype: Optional[str] = None
    layer_count: Optional[int] = None
    head_count: Optional[int] = None
    token_count: Optional[int] = None
    schema_version: str = "1.0"
    extra: Optional[Dict[str, Any]] = None

    def to_csv_row(
        self, include_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Convert event to CSV row format"""
        row = {
            "timestamp_ns": self.timestamp_ns,
            "event": self.event,
            "request_id": self.request_id,
            "seq_id": self.seq_id,
            "address": self.address,
            "size_bytes": self.size_bytes,
            "chunk_size": self.chunk_size or "",
            "kv_dtype": self.kv_dtype or "",
            "layer_count": self.layer_count or "",
            "head_count": self.head_count or "",
            "token_count": self.token_count or "",
            "schema_version": self.schema_version,
            "extra": json.dumps(self.extra) if self.extra else ""
        }
        
        if include_fields:
            return {k: v for k, v in row.items() if k in include_fields}
        return row


class MemoryTraceWriter:
    """Handles writing memory trace events to CSV files with rotation"""
    
    CSV_HEADERS = [
        "timestamp_ns", "event", "request_id", "seq_id", "address",
        "size_bytes", "chunk_size", "kv_dtype", "layer_count",
        "head_count", "token_count", "schema_version", "extra"
    ]
    
    def __init__(
        self,
        output_dir: str,
        rotate_max_bytes: int = 536870912,  # 512MB default
        rotate_interval_sec: int = 0,  # 0 means no time-based rotation
        include_fields: Optional[List[str]] = None,
        rank_suffix: Optional[str] = None
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.rotate_max_bytes = rotate_max_bytes
        self.rotate_interval_sec = rotate_interval_sec
        self.include_fields = include_fields
        self.rank_suffix = rank_suffix or ""
        
        self.current_file = None
        self.current_writer = None
        self.current_file_size = 0
        self.current_file_start_time = None
        self.lock = threading.Lock()
        
        self._rotate_file()
    
    def _get_filename(self) -> str:
        """Generate filename with timestamp and optional rank suffix"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"kv_cache_memory_trace_{timestamp}"
        if self.rank_suffix:
            base_name += f"_{self.rank_suffix}"
        return f"{base_name}.csv"
    
    def _rotate_file(self):
        """Rotate to a new file"""
        with self.lock:
            # Close current file if exists
            if self.current_file:
                self.current_file.close()
            
            # Create new file
            filename = self._get_filename()
            filepath = self.output_dir / filename
            self.current_file = open(
                filepath, 'w', newline='', encoding='utf-8'
            )
            
            # Determine headers to write
            headers = self.CSV_HEADERS
            if self.include_fields:
                headers = [
                    h for h in self.CSV_HEADERS if h in self.include_fields
                ]
            
            self.current_writer = csv.DictWriter(
                self.current_file, fieldnames=headers
            )
            self.current_writer.writeheader()
            
            self.current_file_size = 0
            self.current_file_start_time = time.time()
            
            logger.info(f"Created new trace file: {filepath}")
    
    def _should_rotate(self) -> bool:
        """Check if file rotation is needed"""
        if (self.rotate_max_bytes > 0 and
                self.current_file_size >= self.rotate_max_bytes):
            return True
        
        if self.rotate_interval_sec > 0:
            elapsed = time.time() - self.current_file_start_time
            if elapsed >= self.rotate_interval_sec:
                return True
        
        return False
    
    def write_event(self, event: MemoryTraceEvent):
        """Write a single event to the CSV file"""
        with self.lock:
            if self._should_rotate():
                self._rotate_file()
            
            row = event.to_csv_row(self.include_fields)
            if self.include_fields:
                row = {
                    k: v for k, v in row.items()
                    if k in self.include_fields
                }
            
            self.current_writer.writerow(row)
            self.current_file.flush()  # Ensure data is written
            
            # Estimate size (rough approximation)
            self.current_file_size += len(str(row)) + 10
    
    def close(self):
        """Close the current file"""
        with self.lock:
            if self.current_file:
                self.current_file.close()
                self.current_file = None


class MemoryTraceManager:
    """Manages memory tracing with background writing"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.enabled = False
        self.writer = None
        self.write_queue = Queue(maxsize=10000)
        self.writer_thread = None
        self.stop_event = threading.Event()
        
        # Register cleanup on exit
        atexit.register(self.shutdown)
    
    def initialize(
        self,
        enabled: bool = False,
        output_dir: str = "./traces",
        rotate_max_bytes: int = 536870912,
        rotate_interval_sec: int = 0,
        include_fields: Optional[List[str]] = None,
        rank_suffix: Optional[str] = None
    ):
        """Initialize the trace manager with configuration"""
        self.enabled = enabled
        
        if not self.enabled:
            logger.info("Memory tracing is disabled")
            return
        
        logger.info(
            f"Initializing memory trace manager with "
            f"output_dir={output_dir}"
        )
        
        self.writer = MemoryTraceWriter(
            output_dir=output_dir,
            rotate_max_bytes=rotate_max_bytes,
            rotate_interval_sec=rotate_interval_sec,
            include_fields=include_fields,
            rank_suffix=rank_suffix
        )
        
        # Start background writer thread
        self.writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True
        )
        self.writer_thread.start()
    
    def _writer_loop(self):
        """Background thread that writes events from queue to file"""
        while not self.stop_event.is_set():
            try:
                event = self.write_queue.get(timeout=0.1)
                if event is None:  # Poison pill
                    break
                self.writer.write_event(event)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Error writing trace event: {e}")
    
    def record_event(self, event: MemoryTraceEvent):
        """Record a memory trace event"""
        if not self.enabled:
            return
        
        try:
            self.write_queue.put_nowait(event)
        except Exception:
            logger.warning("Memory trace queue is full, dropping event")
    
    def record_kv_cache_hit(
        self,
        request_id: str,
        seq_id: int,
        address: int,
        size_bytes: int,
        chunk_size: Optional[int] = None,
        kv_dtype: Optional[str] = None,
        layer_count: Optional[int] = None,
        head_count: Optional[int] = None,
        token_count: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None
    ):
        """Record a KV cache hit event"""
        event = MemoryTraceEvent(
            timestamp_ns=time.time_ns(),
            event="kv_cache_hit",
            request_id=request_id,
            seq_id=seq_id,
            address=(f"0x{address:x}" if isinstance(address, int)
                     else str(address)),
            size_bytes=size_bytes,
            chunk_size=chunk_size,
            kv_dtype=kv_dtype,
            layer_count=layer_count,
            head_count=head_count,
            token_count=token_count,
            extra=extra
        )
        self.record_event(event)
    
    def record_kv_cache_offload(
        self,
        request_id: str,
        seq_id: int,
        address: int,
        size_bytes: int,
        chunk_size: Optional[int] = None,
        kv_dtype: Optional[str] = None,
        layer_count: Optional[int] = None,
        head_count: Optional[int] = None,
        token_count: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None
    ):
        """Record a KV cache offload to host event"""
        event = MemoryTraceEvent(
            timestamp_ns=time.time_ns(),
            event="kv_cache_offload_to_host",
            request_id=request_id,
            seq_id=seq_id,
            address=(f"0x{address:x}" if isinstance(address, int)
                     else str(address)),
            size_bytes=size_bytes,
            chunk_size=chunk_size,
            kv_dtype=kv_dtype,
            layer_count=layer_count,
            head_count=head_count,
            token_count=token_count,
            extra=extra
        )
        self.record_event(event)
    
    def record_memory_allocation(
        self,
        address: int,
        size_bytes: int,
        extra: Optional[Dict[str, Any]] = None
    ):
        """Record a memory allocation event"""
        event = MemoryTraceEvent(
            timestamp_ns=time.time_ns(),
            event="memory_allocation",
            request_id="allocator",
            seq_id=0,
            address=(f"0x{address:x}" if isinstance(address, int)
                     else str(address)),
            size_bytes=size_bytes,
            extra=extra
        )
        self.record_event(event)
    
    def record_memory_deallocation(
        self,
        address: int,
        size_bytes: int,
        extra: Optional[Dict[str, Any]] = None
    ):
        """Record a memory deallocation event"""
        event = MemoryTraceEvent(
            timestamp_ns=time.time_ns(),
            event="memory_deallocation",
            request_id="allocator",
            seq_id=0,
            address=(f"0x{address:x}" if isinstance(address, int)
                     else str(address)),
            size_bytes=size_bytes,
            extra=extra
        )
        self.record_event(event)
    
    def shutdown(self):
        """Shutdown the trace manager and flush pending events"""
        if not self.enabled or not self.writer_thread:
            return
        
        logger.info("Shutting down memory trace manager")
        
        # Signal writer thread to stop
        self.stop_event.set()
        self.write_queue.put(None)  # Poison pill
        
        # Wait for writer thread to finish
        if self.writer_thread.is_alive():
            self.writer_thread.join(timeout=5.0)
        
        # Close writer
        if self.writer:
            self.writer.close()


# Global instance
_memory_trace_manager = MemoryTraceManager()


def get_memory_trace_manager() -> MemoryTraceManager:
    """Get the global memory trace manager instance"""
    return _memory_trace_manager


def initialize_memory_trace_from_env():
    """Initialize memory trace from environment variables"""
    enabled = os.getenv("LMC_TRACE_ENABLE", "true").lower() == "true"
    
    if not enabled:
        return
    
    output_dir = os.getenv("LMC_TRACE_OUTPUT_DIR", "./traces")
    rotate_max_bytes = int(
        os.getenv("LMC_TRACE_ROTATE_MAX_BYTES", "536870912")
    )
    rotate_interval_sec = int(os.getenv("LMC_TRACE_ROTATE_INTERVAL_SEC", "0"))
    
    include_fields_str = os.getenv("LMC_TRACE_INCLUDE_FIELDS", "")
    include_fields = None
    if include_fields_str:
        include_fields = [
            f.strip() for f in include_fields_str.split(",") if f.strip()
        ]
    
    # Get rank suffix from environment if available
    rank_suffix = None
    tp_rank = os.getenv("TP_RANK")
    pp_rank = os.getenv("PP_RANK")
    world_rank = os.getenv("RANK")
    
    if tp_rank or pp_rank or world_rank:
        parts = []
        if tp_rank:
            parts.append(f"tp{tp_rank}")
        if pp_rank:
            parts.append(f"pp{pp_rank}")
        if world_rank:
            parts.append(f"rank{world_rank}")
        rank_suffix = "_".join(parts)
    
    manager = get_memory_trace_manager()
    manager.initialize(
        enabled=enabled,
        output_dir=output_dir,
        rotate_max_bytes=rotate_max_bytes,
        rotate_interval_sec=rotate_interval_sec,
        include_fields=include_fields,
        rank_suffix=rank_suffix
    )
