#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Example script demonstrating how to use LMCache with memory tracing enabled.
This script shows how to enable memory tracing via environment variables
or configuration options.
"""

import os
import torch
from lmcache import LMCacheEngine
from lmcache.config import LMCacheEngineConfig, LMCacheEngineMetadata


def setup_with_env_vars():
    """Example: Enable memory tracing using environment variables"""
    # Set environment variables before creating the engine
    os.environ["LMC_TRACE_ENABLE"] = "true"
    os.environ["LMC_TRACE_OUTPUT_DIR"] = "./memory_traces"
    os.environ["LMC_TRACE_ROTATE_MAX_BYTES"] = "104857600"  # 100MB
    
    # Create engine configuration
    config = LMCacheEngineConfig.from_defaults(
        chunk_size=256,
        local_device="cuda" if torch.cuda.is_available() else "cpu",
        max_local_cache_size=10,
    )
    
    # Create engine metadata
    metadata = LMCacheEngineMetadata(
        model_name="example_model",
        world_size=1,
        worker_id=0,
        fmt="huggingface",
        kv_dtype=torch.float16,
        kv_shape=(32, 2, 256, 32, 128),  # layers, kv, chunk, heads, head_dim
    )
    
    # Create the engine - memory tracing will be automatically initialized
    engine = LMCacheEngine(config, metadata)
    return engine


def setup_with_config():
    """Example: Enable memory tracing using configuration options"""
    # Create engine configuration with trace options
    config = LMCacheEngineConfig.from_defaults(
        chunk_size=256,
        local_device="cuda" if torch.cuda.is_available() else "cpu",
        max_local_cache_size=10,
        # Memory trace configuration
        trace_enable=True,
        trace_output_dir="./memory_traces_config",
        trace_rotate_max_bytes=52428800,  # 50MB
        trace_rotate_interval_sec=3600,  # 1 hour
        trace_include_fields=[
            "timestamp_ns", "event", "request_id", "address", "size_bytes"
        ]
    )
    
    # Create engine metadata
    metadata = LMCacheEngineMetadata(
        model_name="example_model",
        world_size=1,
        worker_id=0,
        fmt="huggingface",
        kv_dtype=torch.float16,
        kv_shape=(32, 2, 256, 32, 128),
    )
    
    # Create the engine
    engine = LMCacheEngine(config, metadata)
    return engine


def simulate_kv_operations(engine: LMCacheEngine):
    """Simulate some KV cache operations to generate trace events"""
    # Set request context for tracing
    engine.set_request_context(request_id="example-req-001", seq_id=0)
    
    # Create some dummy tokens and KV tensors
    seq_len = 512
    num_layers = 32
    num_heads = 32
    head_dim = 128
    
    # Generate dummy tokens
    tokens = torch.randint(0, 50000, (seq_len,))
    
    # Generate dummy KV cache (huggingface format)
    # Shape: (num_layers, 2, num_heads, seq_len, head_dim)
    kv_cache = []
    for _ in range(num_layers):
        k = torch.randn(num_heads, seq_len, head_dim, dtype=torch.float16)
        v = torch.randn(num_heads, seq_len, head_dim, dtype=torch.float16)
        kv_cache.append((k, v))
    
    # Store KV cache - this will generate kv_cache_offload_to_host events
    print("Storing KV cache...")
    engine.store(tokens, tuple(kv_cache))
    
    # Update sequence ID for next operation
    engine.set_request_context(seq_id=1)
    
    # Retrieve KV cache - this will generate kv_cache_hit events
    print("Retrieving KV cache...")
    retrieved_kv, mask = engine.retrieve(tokens)
    
    print(f"Retrieved {mask.sum().item()} tokens from cache")
    
    # Simulate another request
    engine.set_request_context(request_id="example-req-002", seq_id=0)
    
    # Partial retrieval
    partial_tokens = tokens[:256]
    retrieved_kv, mask = engine.retrieve(partial_tokens)
    print(f"Retrieved {mask.sum().item()} tokens from partial request")


def main():
    """Main function demonstrating memory trace usage"""
    print("LMCache Memory Trace Example")
    print("=" * 50)
    
    # Choose setup method
    use_env_vars = True
    
    if use_env_vars:
        print("Setting up with environment variables...")
        engine = setup_with_env_vars()
        trace_dir = "./memory_traces"
    else:
        print("Setting up with configuration...")
        engine = setup_with_config()
        trace_dir = "./memory_traces_config"
    
    # Run some operations
    print("\nRunning KV cache operations...")
    simulate_kv_operations(engine)
    
    print(f"\nMemory trace files will be saved to: {trace_dir}")
    print("Look for files named: kv_cache_memory_trace_*.csv")
    
    # The trace manager will automatically flush and close files on exit
    print("\nExample completed!")


if __name__ == "__main__":
    main()
