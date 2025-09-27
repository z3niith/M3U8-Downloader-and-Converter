import os
import sys
import subprocess
import requests
from pathlib import Path
from urllib.parse import urljoin
import tkinter as tk
from tkinter import messagebox, filedialog, ttk
from tkinter.scrolledtext import ScrolledText

THEME = "dark"  # options: "dark", "light"

if THEME == "dark":
    BG = "#1e1e1e"
    FG = "#ffffff"
    ACCENT = "#1793d1"
    ENTRY_BG = "#111111"
    ENTRY_FG = "#00ff00"
    LOG_FG = "#00ff00"
    BUTTON_BG = "#333333"
    CREDIT = "#777777"
else:
    BG = "#f0f0f0"
    FG = "#000000"
    ACCENT = "#0066cc"
    ENTRY_BG = "#ffffff"
    ENTRY_FG = "#000000"
    LOG_FG = "#003300"
    BUTTON_BG = "#dddddd"
    CREDIT = "#555555"

ARCH_ASCII = r"""
                -`
               .o+`
              `ooo/
             `+oooo:
            `+oooooo:
            -+oooooo+:
          `/:-:++oooo+:
         `/++++/+++++++:
        `/++++++++++++++:
       `/+++ooooooooooooo/`
      ./ooosssso++osssssso+`
     .oossssso-````/ossssss+`
    -osssssso.      :ssssssso.
   :osssssss/        osssso+++.
  /ossssssss/        +ssssooo/-
 /ossssso+/:-        -:/+osssso+-
`+sso+:-`                 `.-/+oso:
`:/`                           `.///
"""

def require_ffmpeg():
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError
    except Exception:
        raise RuntimeError("ffmpeg not found. Install ffmpeg and ensure it’s in PATH.")

def parse_m3u8(url, log):
    log("Parsing M3U8 playlist...")
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Failed to download .m3u8 playlist: {e}")

    lines = [ln.strip() for ln in resp.text.splitlines() if ln.strip()]
    segments = [ln for ln in lines if not ln.startswith("#")]
    if not segments:
        raise RuntimeError("No media segments found in playlist.")
    log(f"Found {len(segments)} segments.")
    return segments

def download_segments(segments, playlist_url, output_dir, log, progress_callback=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(segments)
    local_names = []
    for i, seg in enumerate(segments):
        seg_url = urljoin(playlist_url, seg)
        filename = Path(seg).name
        local_path = output_dir / filename
        if not local_path.exists():
            try:
                r = requests.get(seg_url, timeout=30)
                r.raise_for_status()
                local_path.write_bytes(r.content)
                log(f"Downloaded {filename}")
            except Exception as e:
                raise RuntimeError(f"Failed to download segment {seg}: {e}")
        local_names.append(filename)
        if progress_callback:
            progress_callback(i + 1, total)
    return local_names

def build_input_txt(local_segment_names, output_dir, log):
    input_txt = output_dir / "input.txt"
    log("Building ffmpeg input file (no manual durations)...")
    with open(input_txt, "w", encoding="utf-8") as f:
        for name in local_segment_names:
            f.write(f"file '{name}'\n")
    return input_txt

def run_ffmpeg(input_txt_path, output_path, output_format, log):
    if output_format == "mp4":
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(input_txt_path),
            "-vsync", "vfr",
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            "-c:a", "aac",
            str(output_path) + ".mp4"
        ]
    elif output_format == "webm":
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(input_txt_path),
            "-vsync", "vfr",
            "-pix_fmt", "yuv420p",
            "-c:v", "libvpx-vp9",
            "-c:a", "libopus",
            str(output_path) + ".webm"
        ]
    elif output_format == "gif":
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(input_txt_path),
            "-vf", "fps=10,scale=320:-1:flags=lanczos",
            "-loop", "0",
            str(output_path) + ".gif"
        ]
    else:
        raise ValueError("Unsupported output format")

    log("Running ffmpeg...")
    log("> " + ' '.join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    log(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error:\n{result.stderr}")
    return output_path.with_suffix(f".{output_format}")

def cleanup_files(local_segment_names, output_dir, log):
    log("Cleaning up downloaded segments...")
    for name in local_segment_names:
        try:
            (output_dir / name).unlink()
        except Exception as e:
            log(f"Could not delete {name}: {e}")
    try:
        (output_dir / "input.txt").unlink()
    except Exception:
        pass
    try:
        output_dir.rmdir()
    except Exception:
        pass

def sanitize_filename(name: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = ''.join(ch for ch in name if ch not in bad)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "export"

def show_gui():
    def log(msg):
        log_box.config(state=tk.NORMAL)
        log_box.insert(tk.END, msg.strip() + "\n")
        log_box.see(tk.END)
        log_box.config(state=tk.DISABLED)

    def update_progress(text="", current=0, total=100):
        if text:
            progress_label.config(text=text)
        progress_bar["value"] = (current / total) * 100 if total else 0
        root.update_idletasks()

    def on_browse():
        folder = filedialog.askdirectory()
        if folder:
            folder_entry.delete(0, tk.END)
            folder_entry.insert(0, folder)

    def on_submit():
        url = url_entry.get().strip()
        fmt = format_var.get().strip().lower()
        folder = folder_entry.get().strip()
        outname = sanitize_filename(name_entry.get().strip())

        # allow querystrings or extension-less HLS by relaxing the strict check
        if ".m3u8" not in url.lower():
            if not messagebox.askyesno("Confirm", "URL does not contain '.m3u8'. Continue anyway?"):
                return
        if fmt not in ("mp4", "webm", "gif"):
            messagebox.showerror("Error", "Choose mp4, webm, or gif")
            return
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("Error", "Choose valid folder")
            return
        if not outname:
            messagebox.showerror("Error", "Provide a valid output name")
            return

        try:
            require_ffmpeg()
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        submit_btn.config(state=tk.DISABLED)
        log_box.config(state=tk.NORMAL)
        log_box.delete(1.0, tk.END)
        log_box.config(state=tk.DISABLED)
        update_progress("Starting...", 0)

        def progress_callback(i, total):
            update_progress(f"Downloading {i}/{total}", i, total)

        try:
            playlist_url = url
            output_dir = Path(folder) / "slideshow_temp"
            output_dir.mkdir(parents=True, exist_ok=True)

            segments = parse_m3u8(playlist_url, log)
            local_names = download_segments(segments, playlist_url, output_dir, log, progress_callback)
            input_txt = build_input_txt(local_names, output_dir, log)
            output_video = run_ffmpeg(input_txt, Path(folder) / outname, fmt, log)
            cleanup_files(local_names, output_dir, log)

            update_progress("Done!", 100)
            messagebox.showinfo("Done", f"Video created:\n{output_video}")
        except Exception as e:
            update_progress("Error", 0)
            log(f"[ERROR] {e}")
            messagebox.showerror("Error", str(e))
        finally:
            submit_btn.config(state=tk.NORMAL)

    # ---- Root window ----
    root = tk.Tk()
    root.title("M3U8 Creator and Exporter")
    root.configure(bg=BG)
    root.geometry("900x720")          # initial size
    root.minsize(720, 560)            # reasonable minimum
    root.resizable(True, True)

    # Global grid weights: one column, many rows — log area grows
    root.columnconfigure(0, weight=1)
    for r in range(0, 8):
        root.rowconfigure(r, weight=0)
    root.rowconfigure(7, weight=1)  # make the log section stretch vertically

    mono = ("Consolas", 11)
    header = ("Consolas", 16, "bold")
    credit = ("Consolas", 9, "italic")

    # ---- Header / ASCII area ----
    header_frame = tk.Frame(root, bg=BG)
    header_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 8))
    header_frame.columnconfigure(0, weight=0)
    header_frame.columnconfigure(1, weight=1)

    ascii_label = tk.Label(header_frame, text=ARCH_ASCII, font=("Courier New", 8),
                           fg=ACCENT, bg=BG, justify="left", anchor="nw")
    ascii_label.grid(row=0, column=0, rowspan=3, sticky="w")

    title_label = tk.Label(header_frame, text="M3U8 Creator and Exporter", font=header, fg=FG, bg=BG)
    title_label.grid(row=0, column=1, sticky="w", padx=(16, 0), pady=(8, 0))

    version_label = tk.Label(header_frame, text="Alpha version 1.4 (resizable)", font=credit, fg=CREDIT, bg=BG)
    version_label.grid(row=1, column=1, sticky="w", padx=(16, 0))

    # ---- Form area ----
    form = tk.Frame(root, bg=BG)
    form.grid(row=1, column=0, sticky="ew", padx=16)
    for c in range(0, 4):
        form.columnconfigure(c, weight=1 if c in (1, 3) else 0)

    # URL
    tk.Label(form, text="Playlist URL (.m3u8):", font=mono, fg=FG, bg=BG)\
        .grid(row=0, column=0, sticky="w", pady=(4, 2), padx=(0, 8))
    url_entry = tk.Entry(form, font=mono, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground=FG)
    url_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=(4, 2))
    url_entry.bind("<Return>", lambda e: on_submit())

    # Format
    tk.Label(form, text="Output Format:", font=mono, fg=FG, bg=BG)\
        .grid(row=1, column=0, sticky="w", pady=2, padx=(0, 8))
    format_var = tk.StringVar(value="mp4")
    format_menu = ttk.OptionMenu(form, format_var, "mp4", "mp4", "webm", "gif")
    format_menu.grid(row=1, column=1, sticky="w", pady=2)

    # Folder
    tk.Label(form, text="Output Folder:", font=mono, fg=FG, bg=BG)\
        .grid(row=2, column=0, sticky="w", pady=2, padx=(0, 8))
    folder_entry = tk.Entry(form, font=mono, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground=FG)
    folder_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=2)
    browse_btn = tk.Button(form, text="Browse", command=on_browse, font=("Consolas", 10),
                           bg=BUTTON_BG, fg=FG, relief="flat", padx=10)
    browse_btn.grid(row=2, column=3, sticky="w", pady=2, padx=(8, 0))

    # Name
    tk.Label(form, text="Output Name (no extension):", font=mono, fg=FG, bg=BG)\
        .grid(row=3, column=0, sticky="w", pady=2, padx=(0, 8))
    name_entry = tk.Entry(form, font=mono, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground=FG)
    name_entry.insert(0, "export")
    name_entry.grid(row=3, column=1, columnspan=3, sticky="ew", pady=2)

    # Generate button
    submit_btn = tk.Button(root, text="Generate Video", command=on_submit,
                           font=("Consolas", 11, "bold"), bg=ACCENT, fg="white", padx=10, pady=6)
    submit_btn.grid(row=2, column=0, sticky="n", pady=(12, 6))

    # Progress
    progress_frame = tk.Frame(root, bg=BG)
    progress_frame.grid(row=3, column=0, sticky="ew", padx=16)
    progress_frame.columnconfigure(0, weight=1)
    progress_label = tk.Label(progress_frame, text="", font=mono, fg=CREDIT, bg=BG)
    progress_label.grid(row=0, column=0, sticky="w", pady=(2, 4))
    progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
    progress_bar.grid(row=1, column=0, sticky="ew")

    # Log area (expands)
    log_frame = tk.Frame(root, bg=BG)
    log_frame.grid(row=4, column=0, sticky="nsew", padx=16, pady=(8, 0))
    log_frame.rowconfigure(0, weight=1)
    log_frame.columnconfigure(0, weight=1)

    tk.Label(log_frame, text="Log Output:", font=mono, fg=FG, bg=BG)\
        .grid(row=0, column=0, sticky="w", pady=(0, 4))
    log_box = ScrolledText(log_frame, font=mono, bg=ENTRY_BG, fg=LOG_FG, insertbackground=FG)
    log_box.grid(row=1, column=0, sticky="nsew")
    log_box.config(state=tk.DISABLED)

    # Credit (stays at bottom)
    credit_label = tk.Label(root, text="z3niith", font=credit, fg=CREDIT, bg=BG)
    credit_label.grid(row=6, column=0, sticky="w", padx=16, pady=(6, 10))

    # Spacer row to push credit to the bottom (row 5 unused, row 7 carries weight for stretch)
    root.rowconfigure(5, weight=0)
    root.rowconfigure(6, weight=0)
    # row 7 already set to weight=1 above to make the log area expand

    root.mainloop()

def main():
    try:
        show_gui()
    except Exception as e:
        print(f"[Fatal Error] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
