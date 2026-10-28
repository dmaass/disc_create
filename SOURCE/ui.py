#!/usr/bin/env python3
"""Little desktop UI for disc_create (floppy + ISO images).

tkinter only, no dependencies. Run with::

    python ui.py [source_dir]
    python ui.py --register-context | --unregister-context
    python ui.py --context-floppy DIR | --context-iso DIR

Pick a source folder, choose floppy / multi-volume / ISO, create.
The "List image" button shows any existing .img/.iso contents, and
the context-menu row installs Explorer verbs for one-click builds.
Builds run on a worker thread; results return via a polled queue.
All texts are bilingual (German/English, see lang.py) and switchable
in the UI; the choice persists in the config. Folders can be dropped
onto the window (Windows, see dnd.py); dropped images get listed.
"""

from __future__ import annotations

import contextlib
import io
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog, messagebox, ttk

import config
import contextmenu
import dnd
import lang
import make_floppy
import make_iso

#: Format ids with their lang.py label keys.
FORMATS = (
    ("floppy", "fmt_floppy"),
    ("span", "fmt_span"),
    ("iso", "fmt_iso"),
)

#: Project homepage, linked from the status bar.
HOMEPAGE = "https://www.good-old-stuff.de/downloads-software/disc_create/"


# ---------------------------------------------------------------------------
# Non-GUI logic (also used by tests)
# ---------------------------------------------------------------------------

def suggest_output(source: str, fmt: str, parent: str | None = None) -> str:
    """Suggest an output path for format id *fmt*.

    Placed into *parent*, or next to *source* when *parent* is None.
    """
    if not parent:
        parent = os.path.dirname(os.path.abspath(source))
    base = os.path.basename(os.path.abspath(source)) or "disk"
    ext = ".iso" if fmt == "iso" else ".img"
    return os.path.join(parent, base + ext)


def effective_output(source: str, output_text: str, fmt: str,
                     default_dir: str) -> str:
    """Resolve the output path: explicit text wins, else suggest a name.

    The suggestion goes into *default_dir* when set, else next to *source*.
    """
    if output_text.strip():
        return output_text.strip()
    return suggest_output(source, fmt, default_dir.strip() or None)


def prepare_default_dir(default_dir: str) -> None:
    """Create the configured output dir (no-op when empty)."""
    if default_dir.strip():
        os.makedirs(default_dir, exist_ok=True)


def parse_startup_args(argv: list[str]) -> tuple[str, object]:
    """Parse UI startup args (without program name).

    Returns (action, payload): ("gui", preselect|None),
    ("register", None), ("unregister", None),
    ("context", (fmt, srcdir)). Raises ValueError on bad usage.
    """
    if not argv:
        return ("gui", None)
    if argv == ["--register-context"]:
        return ("register", None)
    if argv == ["--unregister-context"]:
        return ("unregister", None)
    if len(argv) == 2 and argv[0] in ("--context-floppy", "--context-iso"):
        fmt = "iso" if argv[0] == "--context-iso" else "floppy"
        if not os.path.isdir(argv[1]):
            raise ValueError(lang.t("err_not_a_dir", path=argv[1]))
        return ("context", (fmt, argv[1]))
    if len(argv) == 1 and not argv[0].startswith("-"):
        if not os.path.isdir(argv[0]):
            raise ValueError(lang.t("err_not_a_dir", path=argv[0]))
        return ("gui", argv[0])
    raise ValueError(lang.t("err_usage", args=" ".join(argv)))


def run_context_action(fmt: str, srcdir: str) -> list[str]:
    """Build one image for an Explorer context-menu invocation.

    Never overwrites: an existing target raises FileExistsError.
    """
    if not os.path.isdir(srcdir):
        raise ValueError(lang.t("err_not_a_dir", path=srcdir))
    default_dir = config.load_output_dir()
    prepare_default_dir(default_dir)
    output = effective_output(srcdir, "", fmt, default_dir)
    return build_image(srcdir, output, fmt, label="", force=False)


def build_image(source: str, output: str, fmt: str,
                label: str, force: bool, progress=None) -> list[str]:
    """Build the image(s); return written paths. Raises on any error.

    *progress*, when given, is called as progress(done, total): bytes
    for ISO, volumes for floppy/span.
    """
    report = progress or (lambda _d, _t: None)
    if not os.path.isdir(source):
        raise make_floppy.FloppyError(
            lang.t("err_not_a_dir", path=source))
    label = label.strip() or None  # type: ignore[assignment]
    if fmt == "iso":
        if os.path.exists(output) and not force:
            raise FileExistsError(lang.t("err_output_exists", path=output))
        make_iso.create_iso_image(source, output, label, progress=report)
        return [output]
    builders = make_floppy.build_floppy_images(
        source, label, span=(fmt == "span"))
    paths = make_floppy._volume_paths(output, len(builders))
    if not force:
        existing = [p for p in paths if os.path.exists(p)]
        if existing:
            raise FileExistsError(
                lang.t("err_output_exists", path=", ".join(existing)))
    for i, (p, b) in enumerate(zip(paths, builders)):
        with open(p, "wb") as f:
            f.write(b.image)
        report(i + 1, len(paths))
    return paths


def route_dropped(paths: list[str]) -> tuple[str | None, str | None, list]:
    """Split dropped paths into (source_dir, image, ignored).

    First folder wins as source, first .img/.iso wins for listing;
    anything else lands in *ignored*.
    """
    source = image = None
    ignored = []
    for p in paths:
        if os.path.isdir(p):
            if source is None:
                source = p
            else:
                ignored.append(p)
        elif os.path.isfile(p) and p.lower().endswith((".img", ".iso")):
            if image is None:
                image = p
            else:
                ignored.append(p)
        else:
            ignored.append(p)
    return source, image, ignored


def list_image_text(path: str) -> str:
    """One-line-per-entry listing of a floppy or ISO image (auto-detected)."""
    if make_iso.is_iso_image(path):
        entries = make_iso.list_iso_contents(path)
    else:
        entries = make_floppy.list_image_contents(path)
    lines = [f"{lang.t('list_dir') if d else lang.t('list_file')}"
             f" {s:>8}  {p}" for p, s, d in entries]
    return "\n".join(lines) if lines else lang.t("list_empty")


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    """Main window. All widget access happens on the UI thread; the worker
    thread only builds images and posts ("done"/"error", ...) job tuples."""

    def __init__(self, preselect: str | None = None) -> None:
        super().__init__()
        self.title("disc_create")
        self.minsize(560, 480)

        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.outdir_var = tk.StringVar(value=config.load_output_dir())
        self.label_var = tk.StringVar()
        self.format_var = tk.StringVar(value="floppy")
        self.force_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar()
        self.ctx_var = tk.StringVar()
        self.lang_var = tk.StringVar(
            value=lang.LANGS[lang.get_language()])
        self._fmt_buttons: list = []

        self.jobs: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_widgets()
        self._apply_language()
        dnd.enable(self, self._on_drop)
        if preselect:
            self.source_var.set(preselect)
            self.output_var.set(
                suggest_output(preselect, self.format_var.get(),
                               self.outdir_var.get().strip() or None))
        self._refresh_ctx_status()
        self.after(100, self._poll_jobs)

    # -- layout ---------------------------------------------------------
    def _build_widgets(self) -> None:
        """Lay out form rows, action buttons, log view and status bar."""
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(1, weight=1)

        # Texts are set by _apply_language; widgets are only stored here.
        self._lbl_source = ttk.Label(frm)
        self._lbl_source.grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.source_var).grid(
            row=0, column=1, sticky="ew", **pad)
        self._btn_browse_source = ttk.Button(frm, command=self._browse_source)
        self._btn_browse_source.grid(row=0, column=2, **pad)

        self._lbl_output = ttk.Label(frm)
        self._lbl_output.grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.output_var).grid(
            row=1, column=1, sticky="ew", **pad)
        self._btn_browse_output = ttk.Button(frm, command=self._browse_output)
        self._btn_browse_output.grid(row=1, column=2, **pad)

        self._lbl_outdir = ttk.Label(frm)
        self._lbl_outdir.grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.outdir_var).grid(
            row=2, column=1, sticky="ew", **pad)
        outdir_btns = ttk.Frame(frm)
        outdir_btns.grid(row=2, column=2, sticky="w", **pad)
        self._btn_browse_outdir = ttk.Button(outdir_btns,
                                             command=self._browse_outdir)
        self._btn_browse_outdir.pack(side=tk.LEFT)
        self._btn_clear = ttk.Button(outdir_btns, command=self._clear_outdir)
        self._btn_clear.pack(side=tk.LEFT, padx=(4, 0))

        self._lbl_format = ttk.Label(frm)
        self._lbl_format.grid(row=3, column=0, sticky="nw", **pad)
        fmt_frm = ttk.Frame(frm)
        fmt_frm.grid(row=3, column=1, columnspan=2, sticky="w", **pad)
        for value, key in FORMATS:
            btn = ttk.Radiobutton(fmt_frm, value=value,
                                  variable=self.format_var,
                                  command=self._on_format_change)
            btn.pack(anchor="w")
            self._fmt_buttons.append((btn, key))

        self._lbl_label = ttk.Label(frm)
        self._lbl_label.grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.label_var, width=16).grid(
            row=4, column=1, sticky="w", **pad)
        self._chk_force = ttk.Checkbutton(frm, variable=self.force_var)
        self._chk_force.grid(row=5, column=1, columnspan=2, sticky="w",
                             **pad)

        self._lbl_context = ttk.Label(frm)
        self._lbl_context.grid(row=6, column=0, sticky="w", **pad)
        ctx_frm = ttk.Frame(frm)
        ctx_frm.grid(row=6, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(ctx_frm, textvariable=self.ctx_var).pack(side=tk.LEFT)
        self.ctx_install_btn = ttk.Button(ctx_frm, command=self._on_register)
        self.ctx_install_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.ctx_remove_btn = ttk.Button(ctx_frm, command=self._on_unregister)
        self.ctx_remove_btn.pack(side=tk.LEFT, padx=(4, 0))

        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=7, column=0, columnspan=3, sticky="ew",
                     pady=(8, 4))
        self.create_btn = ttk.Button(btn_frm, command=self._on_create)
        self.create_btn.pack(side=tk.LEFT, padx=(8, 4))
        self._btn_list = ttk.Button(btn_frm, command=self._on_list)
        self._btn_list.pack(side=tk.LEFT, padx=4)
        self._lang_box = ttk.Combobox(btn_frm, textvariable=self.lang_var,
                                      values=list(lang.LANGS.values()),
                                      state="readonly", width=10)
        self._lang_box.pack(side=tk.RIGHT, padx=8)
        self._lang_box.bind("<<ComboboxSelected>>",
                            self._on_language_change)
        self._lbl_language = ttk.Label(btn_frm)
        self._lbl_language.pack(side=tk.RIGHT)

        log_frm = ttk.LabelFrame(frm, padding=4)
        self._log_frame = log_frm
        log_frm.grid(row=8, column=0, columnspan=3, sticky="nsew",
                     padx=8, pady=4)
        frm.rowconfigure(8, weight=1)
        log_frm.rowconfigure(0, weight=1)
        log_frm.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frm, height=10, width=70, wrap="none",
                           state=tk.DISABLED)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frm, orient=tk.VERTICAL,
                               command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        bottom = ttk.Frame(self)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bottom, textvariable=self.status_var,
                  relief=tk.SUNKEN, anchor="w").pack(side=tk.LEFT,
                                                    fill=tk.X, expand=True)
        self._homepage = tk.Label(bottom, text=HOMEPAGE, fg="blue",
                                  cursor="hand2",
                                  font=("TkDefaultFont", 8, "underline"))
        self._homepage.pack(side=tk.RIGHT, padx=6)
        self._homepage.bind("<Button-1>", self._open_homepage)
        self._progress = ttk.Progressbar(bottom, mode="determinate",
                                        maximum=100, value=0, length=140)
        self._progress.pack(side=tk.RIGHT, padx=(0, 6))

    # -- language ---------------------------------------------------------
    def _apply_language(self) -> None:
        """Retranslate every static widget; keeps the busy state."""
        self._lbl_source.configure(text=lang.t("lbl_source"))
        self._lbl_output.configure(text=lang.t("lbl_output"))
        self._lbl_outdir.configure(text=lang.t("lbl_outdir"))
        self._lbl_format.configure(text=lang.t("lbl_format"))
        self._lbl_label.configure(text=lang.t("lbl_label"))
        self._lbl_context.configure(text=lang.t("lbl_context"))
        self._lbl_language.configure(text=lang.t("lbl_language"))
        browse = lang.t("btn_browse")
        self._btn_browse_source.configure(text=browse)
        self._btn_browse_output.configure(text=browse)
        self._btn_browse_outdir.configure(text=browse)
        self._btn_clear.configure(text=lang.t("btn_clear"))
        for btn, key in self._fmt_buttons:
            btn.configure(text=lang.t(key))
        self._chk_force.configure(text=lang.t("chk_overwrite"))
        self.ctx_install_btn.configure(text=lang.t("btn_install"))
        self.ctx_remove_btn.configure(text=lang.t("btn_remove"))
        self.create_btn.configure(text=lang.t("btn_create"))
        self._btn_list.configure(text=lang.t("btn_list"))
        self._log_frame.configure(text=lang.t("log_frame"))
        busy = self.worker is not None and self.worker.is_alive()
        self.status_var.set(lang.t("status_working" if busy
                                   else "status_ready"))
        self._refresh_ctx_status()

    def _on_language_change(self, _event=None) -> None:
        """Switch language from the dropdown; persist and retranslate."""
        want = self.lang_var.get()
        code = next((c for c, name in lang.LANGS.items() if name == want),
                    lang.DEFAULT)
        lang.set_language(code)
        try:
            config.save_language(code)
        except OSError as e:
            messagebox.showerror(lang.t("err_failed"),
                                lang.t("err_cannot_save", detail=e))
        self._apply_language()

    # -- helpers ----------------------------------------------------------
    def _log(self, text: str) -> None:
        """Append a line to the read-only log view. UI thread only."""
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        """Empty the log view (used before a fresh listing)."""
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def _set_busy(self, busy: bool) -> None:
        """Toggle working state: Create button, status text, watch cursor."""
        state = tk.DISABLED if busy else tk.NORMAL
        self.create_btn.configure(state=state)
        self.status_var.set(lang.t("status_working" if busy
                                    else "status_ready"))
        if busy:
            self._progress["value"] = 0
        self.configure(cursor="watch" if busy else "")

    # -- file dialogs ------------------------------------------------------
    def _browse_source(self) -> None:
        """Pick the source folder; suggest an output name when empty."""
        path = filedialog.askdirectory(title=lang.t("dlg_source_title"))
        if not path:
            return
        self.source_var.set(path)
        if not self.output_var.get().strip():
            self.output_var.set(
                suggest_output(path, self.format_var.get(),
                               self.outdir_var.get().strip() or None))

    def _browse_output(self) -> None:
        """Pick an explicit output file (overrides any suggestion)."""
        if self.format_var.get() == "iso":
            types = [(lang.t("ftype_iso"), "*.iso"),
                     (lang.t("ftype_all"), "*.*")]
            ext = ".iso"
        else:
            types = [(lang.t("ftype_floppy"), "*.img"),
                     (lang.t("ftype_all"), "*.*")]
            ext = ".img"
        path = filedialog.asksaveasfilename(
            title=lang.t("dlg_output_title"), defaultextension=ext,
            filetypes=types)
        if path:
            self.output_var.set(path)

    def _on_format_change(self) -> None:
        """Swap a suggested .img/.iso extension when the format changes."""
        out = self.output_var.get()
        root, ext = os.path.splitext(out)
        if ext.lower() in (".img", ".iso"):
            want = ".iso" if self.format_var.get() == "iso" else ".img"
            if ext != want:
                self.output_var.set(root + want)

    # -- actions -------------------------------------------------------------
    def _browse_outdir(self) -> None:
        """Pick the default output folder and persist it in the config."""
        path = filedialog.askdirectory(title=lang.t("dlg_outdir_title"))
        if not path:
            return
        self.outdir_var.set(path)
        try:
            config.save_output_dir(path)
        except OSError as e:
            messagebox.showerror(lang.t("err_failed"),
                                lang.t("err_cannot_save", detail=e))

    def _clear_outdir(self) -> None:
        """Clear the default output folder (outputs go next to source)."""
        self.outdir_var.set("")
        try:
            config.save_output_dir("")
        except OSError as e:
            messagebox.showerror(lang.t("err_failed"),
                                lang.t("err_cannot_save", detail=e))

    def _refresh_ctx_status(self) -> None:
        """Update the context-menu row (installed/state, button enablement)."""
        if sys.platform != "win32":
            self.ctx_var.set(lang.t("ctx_windows_only"))
            self.ctx_install_btn.configure(state=tk.DISABLED)
            self.ctx_remove_btn.configure(state=tk.DISABLED)
            return
        try:
            installed = contextmenu.is_registered()
        except contextmenu.ContextMenuError:
            self.ctx_var.set(lang.t("ctx_unavailable"))
            self.ctx_install_btn.configure(state=tk.DISABLED)
            self.ctx_remove_btn.configure(state=tk.DISABLED)
            return
        self.ctx_var.set(lang.t("ctx_installed" if installed
                                 else "ctx_not_installed"))

    def _on_register(self) -> None:
        """Install the Explorer verbs and report the outcome."""
        code = lang.get_language()
        try:
            contextmenu.register(lang=code)
        except Exception as e:  # noqa: BLE001 - show anything
            detail = "".join(traceback.format_exception_only(e)).strip()
            messagebox.showerror(lang.t("err_failed"), detail)
        else:
            messagebox.showinfo(
                lang.t("ctx_title"),
                lang.t("ctx_installed_msg",
                       floppy=contextmenu.verb_label("DiscCreateFloppy",
                                                     code),
                       iso=contextmenu.verb_label("DiscCreateIso", code)))
        self._refresh_ctx_status()

    def _on_unregister(self) -> None:
        """Remove the Explorer verbs and report the outcome."""
        try:
            contextmenu.unregister()
        except Exception as e:  # noqa: BLE001 - show anything
            detail = "".join(traceback.format_exception_only(e)).strip()
            messagebox.showerror(lang.t("err_failed"), detail)
        else:
            messagebox.showinfo(lang.t("ctx_title"),
                                lang.t("ctx_removed_msg"))
        self._refresh_ctx_status()

    def _on_create(self) -> None:
        """Validate inputs, resolve the output, start a daemon build thread.

        Does nothing when already busy or no source is chosen. Creating
        the default output folder and the overwrite guard (force flag)
        both happen inside the job/build path.
        """
        if self.worker is not None and self.worker.is_alive():
            return
        source = self.source_var.get().strip()
        if not source:
            messagebox.showerror(lang.t("err_missing_input"),
                                 lang.t("err_choose_source"))
            return
        outdir = self.outdir_var.get().strip()
        try:
            prepare_default_dir(outdir)
            config.save_output_dir(outdir)
        except OSError as e:
            messagebox.showerror(lang.t("err_failed"),
                                lang.t("err_bad_outdir", detail=e))
            return
        output = effective_output(source, self.output_var.get(),
                                  self.format_var.get(), outdir)
        self.output_var.set(output)
        self._set_busy(True)
        self._log(lang.t("log_creating", output=output, source=source))
        args = (source, output, self.format_var.get(),
                self.label_var.get(), self.force_var.get())
        self.worker = threading.Thread(target=self._build_thread,
                                       args=args, daemon=True)
        self.worker.start()

    def _build_thread(self, source: str, output: str, fmt: str,
                      label: str, force: bool) -> None:
        """Worker thread: build the image, post ("done"/"error", ...) job.

        No widget access here; stdout/stderr are captured and replayed
        into the log by _finish_job.
        """
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(out_buf), \
                    contextlib.redirect_stderr(err_buf):
                paths = build_image(
                    source, output, fmt, label, force,
                    progress=lambda d, t: self.jobs.put(("progress",
                                                         d, t)))
            self.jobs.put(("done", paths, out_buf.getvalue(),
                           err_buf.getvalue()))
        except Exception as e:  # noqa: BLE001 - report anything to the log
            self.jobs.put(("error", e, out_buf.getvalue(),
                           err_buf.getvalue()))

    def _poll_jobs(self) -> None:
        """Drain finished jobs every 100ms via _finish_job (self-rescheduling)."""
        try:
            while True:
                job = self.jobs.get_nowait()
                self._finish_job(job)
        except queue.Empty:
            pass
        self.after(100, self._poll_jobs)

    def _finish_job(self, job: tuple) -> None:
        """UI-thread job completion: replay output, log, show dialog."""
        kind = job[0]
        if kind == "progress":
            _, done, total = job
            self._progress["value"] = (100 if total <= 0 else
                                       100 * done / total)
            return
        self._set_busy(False)
        for stream in (job[-2], job[-1]):
            if stream.strip():
                self._log(stream.strip())
        if kind == "done":
            paths = job[1]
            for p in paths:
                self._log(lang.t("log_wrote", path=p,
                                 size=os.path.getsize(p)))
            messagebox.showinfo(lang.t("done_title"),
                                lang.t("done_created",
                                       paths="\n".join(paths)))
        else:
            err = job[1]
            detail = "".join(traceback.format_exception_only(err)).strip()
            self._log(lang.t("log_error", detail=detail))
            messagebox.showerror(lang.t("err_failed"), detail)

    def _on_list(self) -> None:
        """Pick an image and print its contents, clearing the log first."""
        path = filedialog.askopenfilename(
            title=lang.t("dlg_list_title"),
            filetypes=[(lang.t("ftype_images"), "*.img *.iso"),
                       (lang.t("ftype_all"), "*.*")])
        if not path:
            return
        self._show_listing(path)

    def _show_listing(self, path: str) -> None:
        """Clear the log and print the image listing (or the error)."""
        self._clear_log()
        try:
            text = list_image_text(path)
        except Exception as e:  # noqa: BLE001 - show anything
            detail = "".join(traceback.format_exception_only(e)).strip()
            self._log(lang.t("log_error", detail=detail))
            messagebox.showerror(lang.t("err_failed"), detail)
            return
        self._log(f"--- {path} ---")
        self._log(text)

    def _open_homepage(self, _event=None) -> None:
        """Open the project homepage in the default browser."""
        webbrowser.open(HOMEPAGE)

    def _on_drop(self, paths: list[str]) -> None:
        """Handle dropped files: folder -> source, image -> listing."""
        source, image, ignored = route_dropped(paths)
        if source is not None:
            self.source_var.set(source)
            self.output_var.set(
                suggest_output(source, self.format_var.get(),
                               self.outdir_var.get().strip() or None))
        if image is not None:
            self._show_listing(image)
        for p in ignored:
            self._log(lang.t("log_drop_ignored", path=p))


def _report(frozen: bool, ok: bool, title: str, message: str) -> None:
    """Report a console-verb result: dialog when frozen (no console), else print."""
    if frozen:
        (messagebox.showinfo if ok else messagebox.showerror)(title, message)
    elif ok:
        print(message)
    else:
        print(lang.t("log_error", detail=message), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Dispatch console verbs (register/unregister/context) or run the GUI.

    Importable and testable; returns a process exit code (0 ok, 1 error,
    2 usage). Console verbs stay headless (a hidden root only feeds the
    result dialog in the frozen exe).
    """
    args = sys.argv[1:] if argv is None else argv
    frozen = getattr(sys, "frozen", False)
    lang.set_language(config.load_language())
    try:
        action, payload = parse_startup_args(args)
    except ValueError as e:
        _report(frozen, False, lang.t("usage_title"), str(e))
        return 2
    if action == "gui":
        App(preselect=payload).mainloop()  # type: ignore[arg-type]
        return 0

    root = None
    if frozen:
        root = tk.Tk()
        root.withdraw()
    try:
        if action == "register":
            contextmenu.register(lang=lang.get_language())
            _report(frozen, True, lang.t("ctx_title"),
                    lang.t("ctx_cli_installed"))
        elif action == "unregister":
            contextmenu.unregister()
            _report(frozen, True, lang.t("ctx_title"),
                    lang.t("ctx_cli_removed"))
        elif action == "context":
            fmt, srcdir = payload  # type: ignore[misc]
            paths = run_context_action(fmt, srcdir)
            _report(frozen, True, lang.t("done_title"),
                    lang.t("done_created", paths="\n".join(paths)))
        return 0
    except Exception as e:  # noqa: BLE001 - report anything
        detail = "".join(traceback.format_exception_only(e)).strip()
        _report(frozen, False, lang.t("err_failed"), detail)
        return 1
    finally:
        if root is not None:
            root.destroy()


if __name__ == "__main__":
    sys.exit(main())
