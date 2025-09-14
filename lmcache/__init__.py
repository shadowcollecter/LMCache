# SPDX-License-Identifier: Apache-2.0
"""LMCache - A KV cache management system for LLMs"""

from lmcache.cache_engine import LMCacheEngine
from lmcache.config import (
    LMCacheEngineConfig,
    LMCacheEngineMetadata,
    LMCacheMemPoolMetadata
)
from lmcache.memory_trace import (
    get_memory_trace_manager,
    initialize_memory_trace_from_env,
    MemoryTraceManager
)

__all__ = [
    "LMCacheEngine",
    "LMCacheEngineConfig",
    "LMCacheEngineMetadata",
    "LMCacheMemPoolMetadata",
    "get_memory_trace_manager",
    "initialize_memory_trace_from_env",
    "MemoryTraceManager",
]

__version__ = "0.1.0"

# Auto-initialize memory trace from environment variables
initialize_memory_trace_from_env()
