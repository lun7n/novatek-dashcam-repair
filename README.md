# Novatek Dashcam MP4 Repair

**Fix dashcam videos that are full size but stop playing early.** The video data is usually still there; the file index (`stco`) is wrong. This tool rebuilds that index. **Your original files are not modified.**

Free, open-source repair for **Novatek-style** dashcam MP4/MOV files after power loss, card errors, or improper ejection. It walks Novatek chunk headers inside the file and writes repaired copies to a separate folder.

Good fit if:
- The file is roughly normal size but playback stops after a few minutes
- Re-encoding with ffmpeg gives you a **shorter** output file
- The `moov` atom is present at the end of the file (index problem, not a truncated recording)

For files with **no** `moov` atom at all, try [untrunc](https://github.com/anthwlock/untrunc) instead. Restore.Media and similar paid tools cover other failure modes.

---

## Quick start

### Windows (no Python needed)

**[Download DashcamRepair.exe (v1.0.3)](https://github.com/lun7n/novatek-dashcam-repair/releases/latest)**

1. Download `DashcamRepair.exe` from [Releases](https://github.com/lun7n/novatek-dashcam-repair/releases)
2. Double-click it
3. Choose your **input folder** (dashcam videos)
4. Confirm the **output folder** (defaults to `_repaired` inside the input folder)
5. Click **Start Repair**

### GUI (from source)

```bat
python repair_gui.py
```

To build your own `.exe`, see [BUILD.md](BUILD.md) or run `build_exe.bat`.

### Command line

```bat
python repair_all.py "D:\path\to\dashcam\videos"
```

Repaired copies go to `D:\path\to\dashcam\videos\_repaired\`.

```bat
python repair_all.py "D:\videos" --out-dir "D:\videos_fixed"
python repair_all.py "D:\videos" --suffix _fixed
python repair_all.py "D:\videos" --workers 4
python repair_all.py "D:\videos" --verify
```

`--workers` runs multiple files in parallel (default `min(4, CPU count)`). Originals are never modified.

### Requirements

- **Python 3.10+** for CLI/GUI from source (stdlib only for repair; no pip packages required)
- **ffmpeg** optional, for `--verify` or `run_verify.ps1` only

---

## Safety

| Rule | Why |
|------|-----|
| Output defaults to `_repaired` subfolder | Originals stay untouched |
| Blocks same input and output folder without `--suffix` | Avoids overwriting sources |
| Blocks any output path that matches a source file | Extra check before writing |
| Reads originals read-only | Never writes back to source files |

---

## Symptoms

| What you see | What it usually means |
|--------------|------------------------|
| Full file (~4 GB) but stops around 3-5 min | Corrupt `stco` offsets |
| ffmpeg re-encode stops early, smaller output | Index points at bad data mid-file |
| Long duration in VLC/ffprobe but decode errors | Bad sample table, video data often still OK |
| `moov atom not found` | Different problem; try untrunc |

---

## Supported formats

| Works with | Does not handle |
|------------|-----------------|
| MP4, MOV, M4V, 3GP (ISO BMFF) | AVI, MKV, TS |
| Many Novatek dashcams (Viofo, Street Guardian, common DVRs) | GoPro, phone, DJI containers |
| Corrupt index when `moov` is present | Missing `moov` entirely |

Output is **video only** (audio track is removed from the repaired file).

Tested on **1280x720 @ 30fps** Novatek segments with a `frea` atom and `moov` at the end of the file. Other resolutions on the same firmware family may work as well. Very high bitrates (e.g. 4K) might need small constant tweaks in the source.

---

## How it works

1. Read the existing `moov` (index is wrong, not missing)
2. Walk `mdat` using Novatek chunk headers:
   - Type A: `01/41 9a 00`
   - Type B: `65 88 80` (about every 15 frames)
3. Keep offsets that already look valid; walk forward when they do not
4. Rebuild `stsz` from chunk inner sizes
5. Write a new file: original `ftyp` + `frea` + `mdat` + fixed `moov`

No reference file is required. This is format-specific repair, not a generic ffmpeg remux.

---

## Other tools

| Tool | Missing moov | Corrupt stco (this issue) | Free |
|------|--------------|---------------------------|------|
| **This tool** | No | Yes | Yes |
| [untrunc](https://github.com/anthwlock/untrunc) | Yes | No on Novatek layout | Yes |
| [recover-mp4](https://github.com/ntrnghia/recover-mp4) | Yes | No | Yes |
| Restore.Media | Yes | Yes (Novatek) | Paid |

---

## Project layout

```
repair_all.py      # CLI repair engine
repair_gui.py      # Simple GUI
run_repair.bat     # Windows batch wrapper (edit MOVIE_FOLDER)
run_verify.ps1     # Optional ffmpeg decode check
build_exe.bat      # Build standalone DashcamRepair.exe (see BUILD.md)
BUILD.md           # Build and release notes for maintainers
```

---

## Notes

- If the video data in `mdat` is damaged, not just the index, recovery may be partial
- `--broken-only` is a legacy file-size filter; by default all candidate files are processed
- Constants like `MAX_GAP` are tuned for typical 720p/1080p Novatek files

---

## License

MIT. See [LICENSE](LICENSE).

---

## Contributing

Issues are welcome. Helpful details: camera model, symptoms, and whether untrunc or Restore.Media helped on the same file.
