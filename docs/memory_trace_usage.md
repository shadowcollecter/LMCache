# LMCache Memory Trace Usage Guide

This guide explains how to use the memory trace functionality in LMCache to record KV cache operations for analysis and simulation purposes.

## Overview

The memory trace feature records detailed information about KV cache operations to CSV files, including:
- **kv_cache_hit**: When cached data is retrieved from storage
- **kv_cache_offload_to_host**: When data is written to storage
- **memory_allocation**: When storage space is allocated
- **memory_deallocation**: When storage space is freed

## Quick Start

### Method 1: Using Environment Variables

Set the following environment variables before running your application:

```bash
# Enable memory tracing
export LMC_TRACE_ENABLE=true

# Set output directory for trace files
export LMC_TRACE_OUTPUT_DIR=./traces

# Optional: Set file rotation size (default: 512MB)
export LMC_TRACE_ROTATE_MAX_BYTES=536870912

# Optional: Set time-based rotation interval in seconds (0 = disabled)
export LMC_TRACE_ROTATE_INTERVAL_SEC=3600

# Optional: Specify which fields to include (comma-separated)
export LMC_TRACE_INCLUDE_FIELDS=timestamp_ns,event,address,size_bytes
```

### Method 2: Using Configuration

```python
from lmcache.config import LMCacheEngineConfig

config = LMCacheEngineConfig.from_defaults(
    # ... other config options ...
    trace_enable=True,
    trace_output_dir="./traces",
    trace_rotate_max_bytes=536870912,  # 512MB
    trace_rotate_interval_sec=0,
    trace_include_fields=["timestamp_ns", "event", "address", "size_bytes"]
)
```

## CSV Output Format

The trace files are saved as CSV with the following columns:

| Column | Type | Description |
|--------|------|-------------|
| timestamp_ns | int | Event timestamp in nanoseconds |
| event | string | Event type (kv_cache_hit, kv_cache_offload_to_host, etc.) |
| request_id | string | Request identifier |
| seq_id | int | Sequence number within request |
| address | hex string | Memory address (0x prefix) |
| size_bytes | int | Size of the operation in bytes |
| chunk_size | int | LMCache chunk size in tokens |
| kv_dtype | string | Data type (e.g., fp16, bf16) |
| layer_count | int | Number of model layers |
| head_count | int | Number of attention heads |
| token_count | int | Number of tokens in chunk |
| schema_version | string | CSV schema version (currently "1.0") |
| extra | JSON | Additional metadata |

## Example Usage

```python
import os
from lmcache import LMCacheEngine
from lmcache.config import LMCacheEngineConfig, LMCacheEngineMetadata

# Enable tracing via environment
os.environ["LMC_TRACE_ENABLE"] = "true"
os.environ["LMC_TRACE_OUTPUT_DIR"] = "./my_traces"

# Create engine as usual
config = LMCacheEngineConfig.from_defaults(chunk_size=256)
metadata = LMCacheEngineMetadata(
    model_name="my_model",
    world_size=1,
    worker_id=0,
    fmt="huggingface",
    kv_dtype=torch.float16,
    kv_shape=(32, 2, 256, 32, 128)
)

engine = LMCacheEngine(config, metadata)

# Set request context for better tracing
engine.set_request_context(request_id="req-123", seq_id=0)

# Normal operations will now be traced
engine.store(tokens, kv_cache)
retrieved_kv, mask = engine.retrieve(tokens)
```

## Analyzing Trace Files

### Using Pandas

```python
import pandas as pd

# Load trace file
df = pd.read_csv("traces/kv_cache_memory_trace_20250108_120000.csv")

# Analyze read operations
reads = df[df.event == "kv_cache_hit"]
print(f"Total reads: {len(reads)}")
print(f"Total bytes read: {reads.size_bytes.sum():,}")

# Analyze write operations
writes = df[df.event == "kv_cache_offload_to_host"]
print(f"Total writes: {len(writes)}")
print(f"Total bytes written: {writes.size_bytes.sum():,}")

# Calculate bandwidth over time
df['timestamp_s'] = df.timestamp_ns / 1e9
df['MB'] = df.size_bytes / (1024 * 1024)
bandwidth = df.groupby(df.timestamp_s.astype(int))['MB'].sum()
print(f"Peak bandwidth: {bandwidth.max():.2f} MB/s")
```

### Integration with CXL-SSD Simulator

The trace format is designed to be compatible with CXL-SSD simulators:

```python
# Example simulator integration
for _, row in df.iterrows():
    if row.event == "kv_cache_hit":
        simulator.issue_read(
            address=int(row.address, 16),
            size=row.size_bytes,
            timestamp=row.timestamp_ns
        )
    elif row.event == "kv_cache_offload_to_host":
        simulator.issue_write(
            address=int(row.address, 16),
            size=row.size_bytes,
            timestamp=row.timestamp_ns
        )
```

## Multi-Node/Multi-GPU Setup

In distributed settings, each rank will create its own trace file with a suffix:

- Single GPU: `kv_cache_memory_trace_20250108_120000.csv`
- Multi-GPU: `kv_cache_memory_trace_20250108_120000_tp0_pp0_rank0.csv`

The rank suffix is automatically added based on environment variables:
- `TP_RANK`: Tensor parallel rank
- `PP_RANK`: Pipeline parallel rank
- `RANK`: Overall rank

## Performance Considerations

- Tracing adds minimal overhead (<1% in most cases)
- Events are written asynchronously in a background thread
- File rotation prevents unbounded growth
- Consider using `LMC_TRACE_INCLUDE_FIELDS` to reduce file size

## Troubleshooting

### No trace files generated
- Verify `LMC_TRACE_ENABLE=true` is set
- Check the output directory exists and is writable
- Look for initialization messages in logs

### Missing events
- `kv_cache_miss` events are not traced (metadata only)
- Only data layer operations generate trace events
- Ensure request context is set for proper request_id tracking

### Large trace files
- Adjust `LMC_TRACE_ROTATE_MAX_BYTES` for smaller files
- Use `LMC_TRACE_INCLUDE_FIELDS` to record only needed columns
- Enable time-based rotation with `LMC_TRACE_ROTATE_INTERVAL_SEC`
