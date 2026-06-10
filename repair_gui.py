"""Dashcam repair GUI. Optional standalone .exe via PyInstaller."""

import json
import os
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import repair_all  # noqa: E402

CONFIG_PATH = os.path.join(APP_DIR, "dashcam_repair_settings.json")
FORMAT_OPTIONS = [
    (".mp4", "MP4"),
    (".mov", "MOV"),
    (".m4v", "M4V"),
    (".3gp", "3GP"),
]


class RepairApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Novatek Dashcam Repair")
        self.geometry("720x640")
        self.minsize(600, 540)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.suffix_var = tk.StringVar(value="")
        self.workers_var = tk.IntVar(value=repair_all.default_workers())
        self.status_var = tk.StringVar(value="Ready")
        self.ext_vars = {ext: tk.BooleanVar(value=ext == ".mp4") for ext, _ in FORMAT_OPTIONS}

        self.busy = False
        self.cancel_event = threading.Event()
        self.worker = None
        self.out_dir = None

        self._load_settings()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        tk.Label(
            self,
            text="Repairs Novatek dashcam MP4/MOV files when the index is corrupted "
            "(full file size, but playback stops early).\n"
            "Originals are never modified. Repaired copies go to the output folder.\n"
            "Not for AVI/MKV or files with a completely missing moov atom.",
            justify="left",
            wraplength=680,
        ).pack(anchor="w", padx=10, pady=(10, 6))

        self._folder_row("Input folder (videos to repair):", self.input_var, self.browse_input)
        self._folder_row("Output folder (repaired copies):", self.output_var, self.browse_output)

        opt = tk.LabelFrame(self, text="Options")
        opt.pack(fill="x", padx=10, pady=6)

        suf_row = tk.Frame(opt)
        suf_row.pack(fill="x", padx=8, pady=4)
        tk.Label(suf_row, text="Filename suffix (optional):").pack(side="left")
        tk.Entry(suf_row, textvariable=self.suffix_var, width=20).pack(side="left", padx=(8, 0))
        tk.Label(suf_row, text='Required if output = input folder', fg="gray").pack(side="left", padx=(8, 0))

        ext_row = tk.Frame(opt)
        ext_row.pack(fill="x", padx=8, pady=4)
        tk.Label(ext_row, text="File types:").pack(side="left")
        for ext, label in FORMAT_OPTIONS:
            tk.Checkbutton(ext_row, text=label, variable=self.ext_vars[ext]).pack(side="left", padx=(8, 0))

        worker_row = tk.Frame(opt)
        worker_row.pack(fill="x", padx=8, pady=4)
        tk.Label(worker_row, text="Parallel workers:").pack(side="left")
        tk.Spinbox(
            worker_row,
            from_=1,
            to=max(1, (os.cpu_count() or 4)),
            textvariable=self.workers_var,
            width=5,
        ).pack(side="left", padx=(8, 0))
        tk.Label(
            worker_row,
            text=f"(default {repair_all.default_workers()}; 1 = sequential)",
            fg="gray",
        ).pack(side="left", padx=(8, 0))

        btn_row = tk.Frame(self)
        btn_row.pack(fill="x", **pad)
        self.start_btn = tk.Button(btn_row, text="Start Repair", command=self.start_repair, width=14)
        self.start_btn.pack(side="left")
        self.stop_btn = tk.Button(btn_row, text="Stop", command=self.stop_repair, width=10, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.open_btn = tk.Button(btn_row, text="Open Output", command=self.open_output, state="disabled")
        self.open_btn.pack(side="left", padx=(8, 0))
        tk.Button(btn_row, text="Use default output", command=self.default_output).pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x", **pad)
        tk.Label(self, textvariable=self.status_var, anchor="w").pack(fill="x", padx=10)

        self.log = scrolledtext.ScrolledText(self, height=14, state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, **pad)

    def _folder_row(self, label, var, cmd):
        frame = tk.Frame(self)
        frame.pack(fill="x", padx=10, pady=4)
        tk.Label(frame, text=label, anchor="w").pack(fill="x")
        row = tk.Frame(frame)
        row.pack(fill="x", pady=(2, 0))
        tk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(row, text="Browse...", command=cmd, width=10).pack(side="right")

    def browse_input(self):
        path = filedialog.askdirectory(title="Select input folder")
        if path:
            self.input_var.set(path)
            if not self.output_var.get().strip():
                self.default_output()

    def browse_output(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_var.set(path)

    def default_output(self):
        inp = self.input_var.get().strip()
        if inp:
            self.output_var.set(os.path.join(inp, repair_all.DEFAULT_OUT_SUBFOLDER))

    def selected_extensions(self):
        exts = tuple(ext for ext, var in self.ext_vars.items() if var.get())
        return exts if exts else (".mp4",)

    def write_log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_busy(self, busy):
        self.busy = busy
        self.start_btn.configure(state="disabled" if busy else "normal")
        self.stop_btn.configure(state="normal" if busy else "disabled")

    def on_progress(self, current, total, name):
        pct = int(100 * current / total) if total else 0
        self.progress["value"] = pct
        self.status_var.set(f"File {current} of {total}: {name}")

    def _validate_output_safety(self, inp, out, exts):
        targets = repair_all.find_candidates(inp, exts)
        if not targets:
            return None, "No matching video files found."
        try:
            repair_all.validate_output_plan(inp, out, targets, self.suffix_var.get().strip())
        except repair_all.OutputSafetyError as e:
            return None, str(e)
        return targets, None

    def start_repair(self):
        inp = self.input_var.get().strip()
        out = self.output_var.get().strip()
        if not inp or not os.path.isdir(inp):
            messagebox.showerror("Input folder", "Choose a valid input folder.")
            return
        if not out:
            messagebox.showerror("Output folder", "Choose or set an output folder.")
            return

        exts = self.selected_extensions()
        targets, err = self._validate_output_safety(inp, out, exts)
        if err:
            messagebox.showerror("Unsafe output", err)
            return

        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Output folder", str(e))
            return

        free = shutil.disk_usage(os.path.splitdrive(out)[0] or out).free
        need = sum(os.path.getsize(p) for p in targets)
        if free < need:
            if not messagebox.askyesno(
                "Low disk space",
                f"Output drive may not have enough free space.\n"
                f"Need ~{need // (1024**3)} GB, have ~{free // (1024**3)} GB.\n\nContinue anyway?",
            ):
                return

        self.cancel_event.clear()
        self.set_busy(True)
        self.open_btn.configure(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("Starting...")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        suffix = self.suffix_var.get().strip()
        try:
            workers = max(1, int(self.workers_var.get()))
        except (tk.TclError, ValueError):
            workers = repair_all.default_workers()
        self.worker = threading.Thread(
            target=self.run_repair,
            args=(inp, out, exts, suffix, workers),
            daemon=True,
        )
        self.worker.start()

    def stop_repair(self):
        if self.busy:
            self.cancel_event.set()
            self.status_var.set("Stopping after current file...")
            self.write_log("\nStop requested. Finishing current file, then stopping.")

    def run_repair(self, inp, out, exts, suffix, workers):
        try:
            out_dir, results, cancelled = repair_all.run_repair_batch(
                inp,
                out_dir=out,
                extensions=exts,
                name_suffix=suffix,
                workers=workers,
                cancel_event=self.cancel_event,
                log=self.thread_log,
                on_progress=lambda c, t, n: self.after(0, lambda: self.on_progress(c, t, n)),
            )
            self.out_dir = out_dir
            self._save_settings()

            partial = sum(1 for _, ok, n, st in results if st == "partial")
            failed = sum(1 for _, ok, n, st in results if st not in ("ok", "partial"))
            ok = len(results) - failed

            if cancelled:
                title, msg = "Stopped", f"Repair stopped by user.\n\n{ok} file(s) saved to:\n{out_dir}"
            else:
                title = "Done"
                msg = f"Repair finished.\n\n{ok} file(s) saved to:\n{out_dir}"
                if partial:
                    msg += f"\n\n{partial} file(s) only partially recovered."
                if failed:
                    msg += f"\n\n{failed} file(s) failed. See log for details."

            self.after(0, lambda: self.open_btn.configure(state="normal"))
            self.after(0, lambda: messagebox.showinfo(title, msg))
            self.after(0, lambda: self.status_var.set("Stopped" if cancelled else "Done"))
        except repair_all.OutputSafetyError as e:
            self.after(0, lambda: messagebox.showerror("Unsafe output", str(e)))
            self.after(0, lambda: self.status_var.set("Blocked"))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.after(0, lambda: self.status_var.set("Error"))
        finally:
            self.after(0, lambda: self.set_busy(False))

    def thread_log(self, msg):
        self.after(0, lambda: self.write_log(msg))

    def open_output(self):
        path = self.out_dir or self.output_var.get().strip()
        if path and os.path.isdir(path):
            os.startfile(path)

    def _load_settings(self):
        if not os.path.isfile(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            self.input_var.set(data.get("input", ""))
            self.output_var.set(data.get("output", ""))
            self.suffix_var.set(data.get("suffix", ""))
            if "workers" in data:
                self.workers_var.set(data["workers"])
            for ext, var in self.ext_vars.items():
                if ext in data.get("extensions", {}):
                    var.set(data["extensions"][ext])
        except (OSError, json.JSONDecodeError):
            pass

    def _save_settings(self):
        data = {
            "input": self.input_var.get().strip(),
            "output": self.output_var.get().strip(),
            "suffix": self.suffix_var.get().strip(),
            "workers": int(self.workers_var.get()),
            "extensions": {ext: var.get() for ext, var in self.ext_vars.items()},
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def on_close(self):
        if self.busy:
            if not messagebox.askyesno("Repair running", "Stop repair and close?"):
                return
            self.cancel_event.set()
        self._save_settings()
        self.destroy()


def main():
    app = RepairApp()
    app.mainloop()


if __name__ == "__main__":
    main()
