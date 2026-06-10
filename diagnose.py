#!/usr/bin/env python3
"""Diagnose partial Novatek MP4 repair failures."""
import mmap
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from repair_all import (
    read_moov, find_mdat_start, video_stco, walk_stco, valid_hdr, MAX_GAP,
    mdat_end_for, expected_sample_count, _reach, _forward_start,
)


def scan_headers(mm, start, end, step=1, limit=20):
    hits = []
    for off in range(start, end - 8, step):
        if valid_hdr(mm, off):
            hits.append(off)
            if len(hits) >= limit:
                break
    return hits


def diagnose(path):
    print(f"\n{'='*70}\n{path}")
    size = os.path.getsize(path)
    print(f"file size: {size:,} ({size/1e9:.3f} GB)")

    data, moov_start, moov_end = read_moov(path)
    mdat_start = find_mdat_start(data)
    file_size = os.path.getsize(path)
    mdat_end = mdat_end_for(file_size, moov_start, mdat_start)
    moov_first = mdat_start > moov_start
    mdat_payload = mdat_end - mdat_start
    target_n = expected_sample_count(data, moov_start, moov_end)
    print(f"mdat payload: {mdat_start:,} .. {mdat_end:,} ({mdat_payload:,} bytes)")
    print(f"layout: {'moov-first' if moov_first else 'moov-last'}  expected_samples={target_n or '?'}")

    _, co_base, sz_base, b_offs, b_sizes, bn = video_stco(data, moov_start, moov_end)
    print(f"moov samples (stco): {bn:,}")

    with open(path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        walk_limit = target_n if target_n else bn
        new_offs, ok = walk_stco(mm, b_offs, bn, mdat_end, mdat_start, max_samples=walk_limit)
        report_n = target_n or bn

        if ok > 0:
            last = new_offs[ok - 1]
            inner = struct.unpack(">I", mm[last : last + 4])[0]
            est_end = last + inner + 4
            print(f"walk recovered: {ok:,}/{report_n:,} ({ok/report_n*100:.1f}%)")
            print(f"last offset: {last:,}  inner={inner:,}  est chunk end={est_end:,}")
            print(f"unused mdat after last chunk: {mdat_end - est_end:,} bytes ({(mdat_end-est_end)/mdat_payload*100:.1f}% of mdat)")

            # Why did walk stop?
            if ok < report_n:
                i = ok
                prev = new_offs[ok - 1]
                broken_off = b_offs[i] if i < bn else 0
                print(f"\n--- stop at sample {i} ---")
                print(f"  prev offset: {prev:,}")
                print(f"  broken stco[{i}]: {broken_off:,}  valid={valid_hdr(mm, broken_off) if broken_off < mdat_end else False}")
                inner = struct.unpack(">I", mm[prev : prev + 4])[0]
                fwd_start = _forward_start(prev, inner)
                fwd_end = min(mdat_end, prev + _reach(inner))
                print(f"  forward search: {fwd_start:,} .. {fwd_end:,} (gap={fwd_end-fwd_start:,}, reach={_reach(inner)})")
                hits = scan_headers(mm, fwd_start, fwd_end)
                print(f"  valid headers in gap: {len(hits)}")
                if hits:
                    print(f"    first hits: {hits[:5]}")
                else:
                    # scan wider
                    wide_end = min(mdat_end, prev + MAX_GAP * 3)
                    wide = scan_headers(mm, fwd_end, wide_end, step=4, limit=10)
                    print(f"  headers in {fwd_end:,}..{wide_end:,}: {len(wide)}")
                    if wide:
                        print(f"    first beyond MAX_GAP: {wide[0]:,} (dist={wide[0]-prev:,})")

                # Show bytes at forward start
                sample = mm[fwd_start : fwd_start + 32]
                print(f"  bytes @ fwd_start: {sample.hex()}")

        # Bootstrap region stats
        boot_end = min(mdat_end, mdat_start + 600000)
        boot_hits = scan_headers(mm, mdat_start, boot_end, step=4, limit=5)
        print(f"\nbootstrap headers (first 600KB): {len(scan_headers(mm, mdat_start, boot_end, step=4, limit=99999))} found, first={boot_hits[:3]}")

        # Count valid headers in entire mdat
        total_hdr = 0
        type_a = type_b = 0
        for off in range(mdat_start, mdat_end - 8, 4):
            if valid_hdr(mm, off):
                total_hdr += 1
                h = mm[off+4:off+7]
                if h[1] == 0x9A:
                    type_a += 1
                elif h[0] == 0x65:
                    type_b += 1
        print(f"total valid headers in mdat (step=4): {total_hdr:,} (typeA={type_a:,}, typeB={type_b:,})")
        print(f"expected if contiguous ~30fps: ~{mdat_payload/28000:.0f} chunks")

        mm.close()


if __name__ == "__main__":
    for p in sys.argv[1:]:
        diagnose(p)
