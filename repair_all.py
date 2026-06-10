#!/usr/bin/env python3
"""Repair corrupted video index tables in Novatek-style dashcam MP4/MOV files."""

from __future__ import annotations

import argparse
import mmap
import os
import shutil
import struct
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

# ISO BMFF containers (same atom structure). Not AVI/MKV/TS.
SUPPORTED_EXTENSIONS = (".mp4", ".mov", ".m4v", ".3gp")

# Legacy size heuristic for --broken-only (camera-specific; optional filter).
HEALTHY_SIZES: set[int] = set()

MIN_SIZE = 1_000_000  # skip tiny junk; include short shutdown clips (~200 MB)
DEFAULT_VERIFY_TIMEOUT = 1800  # 30 min per file (full decode of ~4 GB)
DEFAULT_OUT_SUBFOLDER = "_repaired"


def default_workers():
    return 1


class RepairCancelled(Exception):
    pass


class OutputSafetyError(ValueError):
    """Output path would overwrite a source file."""


def norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def valid_hdr(mm, off):
    if off + 8 > len(mm):
        return False
    hdr = mm[off : off + 8]
    inner = struct.unpack(">I", hdr[:4])[0]
    b4, b5, b6 = hdr[4], hdr[5], hdr[6]
    # Type C: moov-first exports (tag 4e010101; inner may be < 6)
    if b4 == 0x4E and b5 == 0x01 and b6 == 0x01:
        return inner <= 250000
    if inner < 6 or inner > 250000:
        return False
    # Type A
    if b5 == 0x9A and b6 == 0x00 and b4 in (0x01, 0x41):
        return True
    # Type B
    if b4 == 0x65 and b5 == 0x88 and b6 == 0x80:
        return True
    return False


def is_moov_first(mdat_start, moov_start):
    return mdat_start > moov_start


def mdat_end_for(file_size, moov_start, mdat_start):
    return file_size if is_moov_first(mdat_start, moov_start) else moov_start


def expected_sample_count(data, moov_start, moov_end):
    """Sample count from stsz/ctts when stco entry count is truncated (moov-first exports)."""
    moov = data[moov_start:moov_end]
    v = moov.find(b"vide")
    if v < 0:
        return None
    for tag in (b"stsz", b"ctts"):
        pos = moov.find(tag, v)
        if pos < 0:
            continue
        cnt = struct.unpack(">I", moov[pos + 12 : pos + 16])[0]
        if 1000 < cnt < 5_000_000:
            return cnt
    return None


def read_moov(path):
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    while pos + 8 <= len(data):
        size, btype = struct.unpack(">I4s", data[pos : pos + 8])
        if size == 0:
            size = len(data) - pos
        if btype == b"moov":
            return data, pos, pos + size
        pos += size
    raise ValueError(f"no moov in {path}")


def find_mdat_start(data) -> int:
    """Return byte offset of the mdat payload (first byte after the mdat box header)."""
    pos = 0
    while pos + 8 <= len(data):
        size, btype = struct.unpack(">I4s", data[pos : pos + 8])
        if size == 0:
            size = len(data) - pos
        if size < 8:
            break
        if btype == b"mdat":
            return pos + 8
        pos += size
    return 7528  # fallback for odd layouts


def video_stco(data, moov_start, moov_end):
    moov = data[moov_start:moov_end]
    v = moov.find(b"vide")
    stco = moov.find(b"stco", v)
    stsz = moov.find(b"stsz", v)
    n = struct.unpack(">I", moov[stco + 8 : stco + 12])[0]
    co_base = moov_start + stco + 16
    sz_base = moov_start + stsz + 16
    offs = [struct.unpack(">I", data[co_base + 4 * i : co_base + 4 * i + 4])[0] for i in range(n)]
    sizes = list(struct.unpack(f">{n}I", data[sz_base : sz_base + n * 4]))
    return bytearray(data), co_base, sz_base, offs, sizes, n


MAX_GAP = 150000
# Novatek I-frames can exceed MAX_GAP; search/trust window must span at least inner+slack.
REACH_SLACK = 50000


def _reach(prev_inner):
    return max(MAX_GAP, prev_inner) + REACH_SLACK


def _forward_start(prev, inner_prev):
    if inner_prev <= 8:
        return prev + 8
    return prev + max(inner_prev, 8)


def walk_stco(mm, b_offs, n, mdat_end, mdat_payload_start, max_samples=None):
    limit = max(max_samples or 0, n)
    out = [0] * limit
    prev = None
    count = 0
    bootstrap_end = min(mdat_end, mdat_payload_start + 600000)
    for i in range(limit):
        chosen = None
        inner_prev = 0
        if prev is not None:
            inner_prev = struct.unpack(">I", mm[prev : prev + 4])[0]
        reach = _reach(inner_prev)
        broken_off = b_offs[i] if i < n else 0
        if broken_off < mdat_end and valid_hdr(mm, broken_off):
            if prev is None or (prev < broken_off <= prev + reach):
                chosen = broken_off
        if chosen is None and prev is not None:
            start = _forward_start(prev, inner_prev)
            end = min(mdat_end, prev + reach)
            for off in range(start, end - 8):
                if valid_hdr(mm, off) and off > prev:
                    chosen = off
                    break
        if chosen is None and prev is None:
            for off in range(mdat_payload_start, bootstrap_end):
                if valid_hdr(mm, off):
                    chosen = off
                    break
        if chosen is None:
            break
        out[i] = chosen
        prev = chosen
        count += 1
    return out, count


def rebuild_moov_first_stco(bdata, moov_start, moov_end, new_offs, ok):
    """Write full stco table after constant-size stsz; drop corrupted tail stco atom."""
    moov = bytearray(bdata[moov_start:moov_end])
    v = moov.find(b"vide")
    stsz = moov.find(b"stsz", v)
    tail_stco = moov.find(b"stco", v)
    if stsz < 0 or tail_stco < 0:
        raise ValueError("moov-first layout missing stsz/stco")
    table_rel = stsz + 20
    struct.pack_into(">I", moov, table_rel, 16 + 4 * ok)
    moov[table_rel + 4 : table_rel + 8] = b"stco"
    struct.pack_into(">I", moov, table_rel + 12, ok)
    for i in range(ok):
        struct.pack_into(">I", moov, table_rel + 16 + 4 * i, new_offs[i])
    moov_out = moov[:tail_stco]
    struct.pack_into(">I", moov_out, 0, len(moov_out))
    return bytes(moov_out)


def classify_repair(ok, target):
    """Label repair outcome for logging (full / partial / fail)."""
    if ok == 0:
        return "fail"
    if target and ok >= target * 0.98:
        return "full"
    if ok >= 1000:
        return "partial"
    return "fail"


def strip_audio(data, moov_start, moov_end):
    moov = bytearray(data[moov_start:moov_end])
    soun = moov.find(b"soun")
    if soun < 0:
        return bytes(moov)
    trak = moov.rfind(b"trak", 0, soun)
    sz = struct.unpack(">I", moov[trak : trak + 4])[0]
    out = moov[:trak] + moov[trak + sz :]
    struct.pack_into(">I", out, 0, len(out))
    return bytes(out)


def repair_file(broken_path, out_path, log=print):
    name = os.path.basename(broken_path)
    t0 = time.perf_counter()
    file_size = os.path.getsize(broken_path)

    bdata, bms, bme = read_moov(broken_path)
    mdat_start = find_mdat_start(bdata)
    mdat_end = mdat_end_for(file_size, bms, mdat_start)
    moov_first = is_moov_first(mdat_start, bms)
    target_n = expected_sample_count(bdata, bms, bme) if moov_first else None

    bdata, co_base, sz_base, b_offs, b_sizes, bn = video_stco(bdata, bms, bme)
    walk_limit = target_n if target_n else bn

    with open(broken_path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        new_offs, ok = walk_stco(mm, b_offs, bn, mdat_end, mdat_start, max_samples=walk_limit)
        new_sizes = list(b_sizes)
        while len(new_sizes) < ok:
            new_sizes.append(0)
        for i in range(1, ok):
            inner = struct.unpack(">I", mm[new_offs[i - 1] : new_offs[i - 1] + 4])[0]
            if inner <= 8:
                new_sizes[i] = new_offs[i] - new_offs[i - 1]
            else:
                new_sizes[i] = inner + 4
        mm.close()

    report_n = target_n or bn
    if moov_first:
        raw_moov = rebuild_moov_first_stco(bdata, bms, bme, new_offs, ok)
        temp = bdata[:bms] + raw_moov + bdata[bme:]
        new_moov = strip_audio(temp, bms, bms + len(raw_moov))
        with open(out_path, "wb") as f:
            f.write(bdata[:bms])
            f.write(new_moov)
            f.write(bdata[bme:])
    else:
        for i in range(min(ok, bn)):
            struct.pack_into(">I", bdata, co_base + 4 * i, new_offs[i])
            if i < len(new_sizes):
                struct.pack_into(">I", bdata, sz_base + 4 * i, new_sizes[i])
        new_moov = strip_audio(bdata, bms, bme)
        with open(out_path, "wb") as f:
            f.write(bdata[:bms])
            f.write(new_moov)

    dur = ok / 30 / 60
    status = classify_repair(ok, report_n)
    layout = "moov-first" if moov_first else "moov-last"
    log(f"  {name}: {status.upper()} {ok:,}/{report_n:,} samples ({dur:.1f} min) [{layout}]")
    log(f"    time={time.perf_counter()-t0:.1f}s")
    return ok, report_n


def is_candidate(path, extensions=None):
    ext = os.path.splitext(path)[1].lower()
    allowed = extensions or SUPPORTED_EXTENSIONS
    if ext not in allowed:
        return False
    return os.path.getsize(path) >= MIN_SIZE


def is_broken(path, extensions=None):
    if not HEALTHY_SIZES:
        return is_candidate(path, extensions)
    return is_candidate(path, extensions) and os.path.getsize(path) not in HEALTHY_SIZES


def find_candidates(movie_dir, extensions=None, broken_only=False):
    exts = tuple(e.lower() if e.startswith(".") else f".{e.lower()}" for e in (extensions or SUPPORTED_EXTENSIONS))
    targets = []
    for name in os.listdir(movie_dir):
        path = os.path.join(movie_dir, name)
        if not os.path.isfile(path):
            continue
        if broken_only:
            if is_broken(path, exts):
                targets.append(path)
        elif is_candidate(path, exts):
            targets.append(path)
    return sorted(targets)


def output_filename(src_path, name_suffix=""):
    base, ext = os.path.splitext(os.path.basename(src_path))
    if name_suffix:
        return f"{base}{name_suffix}{ext}"
    return os.path.basename(src_path)


def resolve_out_dir(movie_dir, out_dir=None, out_subfolder=DEFAULT_OUT_SUBFOLDER):
    if out_dir:
        return out_dir if os.path.isabs(out_dir) else os.path.join(movie_dir, out_dir)
    if out_subfolder:
        return os.path.join(movie_dir, out_subfolder)
    return movie_dir


def validate_output_plan(movie_dir, out_dir, targets, name_suffix=""):
    """Refuse plans that would overwrite source files."""
    movie_norm = norm_path(movie_dir)
    out_norm = norm_path(out_dir)

    if movie_norm == out_norm and not name_suffix:
        raise OutputSafetyError(
            "Output folder is the same as the input folder and no filename suffix is set. "
            "Repairs would overwrite your originals. "
            f"Use a separate output folder (default: {DEFAULT_OUT_SUBFOLDER}) or add --suffix _fixed."
        )

    collisions = []
    for src in targets:
        out_path = os.path.join(out_dir, output_filename(src, name_suffix))
        if norm_path(src) == norm_path(out_path):
            collisions.append(os.path.basename(src))

    if collisions:
        sample = ", ".join(collisions[:5])
        extra = f" (+{len(collisions) - 5} more)" if len(collisions) > 5 else ""
        raise OutputSafetyError(
            "These output paths would overwrite source files: "
            f"{sample}{extra}. Use a different output folder or add --suffix."
        )

    return out_dir


def find_ffmpeg():
    return shutil.which("ffmpeg")


def verify_file(path, timeout=DEFAULT_VERIFY_TIMEOUT):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return "skip", "ffmpeg not on PATH"

    t0 = time.perf_counter()
    try:
        dec = subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-i", path,
             "-map", "0:v:0", "-f", "null", "-"],
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        _kill_process_tree(e)
        elapsed = time.perf_counter() - t0
        return "timeout", f"decode exceeded {timeout}s ({elapsed:.0f}s elapsed)"

    elapsed = time.perf_counter() - t0
    if dec.returncode != 0:
        err = dec.stderr.decode(errors="replace").strip().replace("\r\n", " ")[:200]
        return "fail", f"{err or f'exit {dec.returncode}'} ({elapsed:.1f}s)"

    try:
        ffprobe = shutil.which("ffprobe") or "ffprobe"
        probe = subprocess.run(
            [ffprobe, "-nostdin", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration", "-of", "csv=p=0", path],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "pass", f"decode ok, ffprobe timed out ({elapsed:.1f}s)"

    dur = probe.stdout.strip() if probe.returncode == 0 else "?"
    return "pass", f"duration={dur}s ({elapsed:.1f}s)"


def _kill_process_tree(exc):
    proc = exc.process
    if proc is None:
        return
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def _parallel_repair_job(job):
    """Worker for ProcessPoolExecutor; must be module-level for pickling."""
    index, total, src, out, name = job
    try:
        ok, n = repair_file(src, out, log=lambda _m: None)
        status = classify_repair(ok, n)
        dur = ok / 30 / 60
        detail = f"  {name}: {status.upper()} {ok:,}/{n:,} samples ({dur:.1f} min)"
        return index, src, ok, n, status, detail
    except Exception as e:
        return index, src, 0, 0, str(e), f"  FAIL {name}: {e}"


def _make_logger(log=print, log_path=None):
    fh = open(log_path, "w", encoding="utf-8") if log_path else None

    def combined(msg):
        log(msg)
        if fh:
            fh.write(msg + "\n")
            try:
                fh.flush()
            except OSError:
                pass

    return combined, fh


def run_repair_batch(
    movie_dir,
    broken_only=False,
    out_dir=None,
    out_subfolder=DEFAULT_OUT_SUBFOLDER,
    extensions=None,
    name_suffix="",
    workers=None,
    cancel_event=None,
    log=print,
    on_progress=None,
    log_file=None,
):
    """Repair candidate files. cancel_event.set() stops after the current file."""
    movie_dir = os.path.abspath(movie_dir)
    if not os.path.isdir(movie_dir):
        raise FileNotFoundError(f"Input folder not found: {movie_dir}")

    targets = find_candidates(movie_dir, extensions, broken_only=broken_only)
    if not targets:
        raise FileNotFoundError(
            f"No matching video files in {movie_dir}. "
            f"Supported: {', '.join(extensions or SUPPORTED_EXTENSIONS)}"
        )

    out_dir = resolve_out_dir(movie_dir, out_dir, out_subfolder)
    validate_output_plan(movie_dir, out_dir, targets, name_suffix)
    os.makedirs(out_dir, exist_ok=True)

    log_path = log_file or os.path.join(out_dir, "repair_log.txt")
    log_fn, log_handle = _make_logger(log, log_path)

    mode = "broken only" if broken_only else "all segments"
    ext_label = ", ".join(extensions or SUPPORTED_EXTENSIONS)

    worker_count = max(1, workers if workers is not None else default_workers())

    log_fn(f"Repairing {len(targets)} files ({mode})")
    log_fn(f"Formats: {ext_label}")
    log_fn(f"Input:  {movie_dir}")
    log_fn(f"Output: {out_dir}")
    log_fn(f"Workers: {worker_count}")
    log_fn("Originals are never modified.")
    if name_suffix:
        log_fn(f"Filename suffix: {name_suffix}")
    log_fn("")

    jobs = []
    results = []
    for i, src in enumerate(targets, 1):
        name = os.path.basename(src)
        out_name = output_filename(src, name_suffix)
        out = os.path.join(out_dir, out_name)

        if norm_path(src) == norm_path(out):
            log_fn(f"  SKIP {name}: would overwrite source (use --suffix or another output folder)")
            results.append((src, 0, 0, "overwrite blocked"))
            continue

        jobs.append((i, len(targets), src, out, name))

    cancelled = False
    if worker_count <= 1:
        for index, total, src, out, name in jobs:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                log_fn("\nStopped by user (current file finished; remaining files skipped).")
                break

            if on_progress:
                on_progress(index, total, name)

            log_fn(f"[{index}/{total}] {name} ...")
            try:
                ok, n = repair_file(src, out, log=log_fn)
                status = classify_repair(ok, n)
                results.append((src, ok, n, status))
            except Exception as e:
                log_fn(f"  FAIL {name}: {e}")
                results.append((src, 0, 0, str(e)))
    else:
        pending = list(jobs)
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(_parallel_repair_job, job): job for job in pending}
            done = 0
            for fut in as_completed(futures):
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    for f in futures:
                        f.cancel()
                    log_fn("\nStop requested; in-flight repairs may still finish.")
                    break

                index, src, ok, n, status, detail = fut.result()
                name = os.path.basename(src)
                done += 1
                if on_progress:
                    on_progress(done, len(jobs), name)
                log_fn(f"[{index}/{len(jobs)}] {name} ...")
                log_fn(detail)
                results.append((src, ok, n, status))

            if cancelled:
                log_fn("\nStopped by user (remaining queued files skipped).")

    ok_count = sum(1 for *_, status in results if status in ("full", "partial"))
    full_count = sum(1 for *_, status in results if status == "full")
    partial_count = sum(1 for *_, status in results if status == "partial")
    fail_count = sum(1 for *_, status in results if status == "fail" or status not in ("full", "partial"))

    if cancelled:
        log_fn(f"\nStopped. {ok_count} files written before cancel.")
    else:
        log_fn(f"\nDone. {ok_count}/{len(results)} files written ({full_count} full, {partial_count} partial).")
    if partial_count:
        log_fn(f"  {partial_count} file(s) partially recovered (see sample counts above).")
    if fail_count:
        log_fn(f"  {fail_count} file(s) failed.")
    log_fn(f"Log saved: {log_path}")
    log_fn(f"Output folder: {out_dir}")

    if log_handle:
        try:
            log_handle.close()
        except OSError:
            pass

    return out_dir, results, cancelled


def main():
    parser = argparse.ArgumentParser(
        description="Repair Novatek dashcam MP4/MOV files with corrupted video index (stco)."
    )
    parser.add_argument(
        "movie_dir",
        nargs="?",
        help="Folder containing dashcam video files",
    )
    parser.add_argument(
        "--broken-only",
        action="store_true",
        help="Only process files whose size does not match known-good sizes (legacy filter)",
    )
    parser.add_argument(
        "--out-dir",
        help=f"Output folder (default: <movie_dir>/{DEFAULT_OUT_SUBFOLDER})",
    )
    parser.add_argument(
        "--suffix",
        default="",
        help="Append to output filenames before extension (e.g. _fixed)",
    )
    parser.add_argument(
        "--ext",
        action="append",
        help="File extension to include (repeatable). Default: mp4 mov m4v 3gp",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run ffmpeg decode check after each repair",
    )
    parser.add_argument(
        "--verify-timeout",
        type=int,
        default=DEFAULT_VERIFY_TIMEOUT,
        help=f"Seconds before killing a hung ffmpeg verify (default {DEFAULT_VERIFY_TIMEOUT})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel repair workers (default: 1; use 2-4 for small moov-first batches)",
    )
    args = parser.parse_args()

    if not args.movie_dir:
        parser.error("movie_dir is required (folder containing dashcam videos)")

    extensions = tuple(f".{e.lstrip('.').lower()}" for e in args.ext) if args.ext else None

    try:
        out_dir, results, _ = run_repair_batch(
            args.movie_dir,
            broken_only=args.broken_only,
            out_dir=args.out_dir,
            extensions=extensions,
            name_suffix=args.suffix,
            workers=args.workers,
        )
    except (OutputSafetyError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not args.verify:
        print("\nTip: run with --verify to decode-check outputs (requires ffmpeg on PATH)")
        return

    print(f"\n{'='*60}\nVerify (video only, timeout={args.verify_timeout}s):")
    for src, ok, n, status in results:
        if status not in ("full", "partial"):
            continue
        out = os.path.join(out_dir, output_filename(src, args.suffix))
        vstatus, notes = verify_file(out, timeout=args.verify_timeout)
        print(f"  {os.path.basename(src)}: {vstatus.upper()} {notes} samples={ok}/{n}")


if __name__ == "__main__":
    main()
