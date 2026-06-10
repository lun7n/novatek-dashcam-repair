## v1.0.3

Batch repair fixes from C7/C8 repair testing.

### Repair engine
- Auto-detect moov-first vs moov-last layouts
- Rebuild truncated stco tables for moov-first exports
- Three Novatek chunk header types (A/B/C), including Type C with inner size under 6 bytes
- Dynamic search window (MAX_GAP + REACH_SLACK) with 1-byte forward search
- Output safety guardrails (never overwrite source files)
- FULL / PARTIAL / FAIL status with sample counts in logs

### Batch / CLI
- `--workers N` for parallel repair (default 1; use 2-4 on small moov-first batches)
- Compression removed (produced unplayable output)

### GUI
- Parallel workers spinbox (default 1)

Download **DashcamRepair.exe** below for Windows without Python.
