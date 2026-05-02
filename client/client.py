"""
GrokMCQ Client
--------------
A draggable floating button that lives anywhere on screen.
- Ctrl+G  → show / hide the floating button
- Click button → capture screen, send to backend, show answer

Build to EXE:
    pip install pyinstaller pyautogui Pillow requests keyboard
    pyinstaller --onefile --windowed --name GrokMCQ client.py
"""

import base64
import io
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox

import keyboard
import pyautogui
import requests
from PIL import Image

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BACKEND_URL = os.environ.get(
    "GROK_MCQ_BACKEND",
    "https://grok-mcq-backend.onrender.com/"   # <-- replace with your Render URL
)
ANSWER_DISPLAY_SECONDS = 10
HOTKEY = "ctrl+g"
# ─────────────────────────────────────────────────────────────────────────────


# ── Answer popup ─────────────────────────────────────────────────────────────
class AnswerPopup:
    def __init__(self, parent_x: int, parent_y: int, answer: str, full_response: str):
        self.win = tk.Toplevel()
        self.win.title("")
        self.win.attributes("-topmost", True)
        self.win.overrideredirect(True)
        self.win.configure(bg="#1a1a2e")

        sw = self.win.winfo_screenwidth()
        # Open to the right of the button; flip left if near edge
        wx = parent_x + 70
        if wx + 400 > sw:
            wx = parent_x - 420
        self.win.geometry(f"400x220+{wx}+{parent_y}")

        # Header bar
        hdr = tk.Frame(self.win, bg="#1e90ff", pady=4)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  🤖 GrokMCQ Answer", font=("Arial", 11, "bold"),
                 bg="#1e90ff", fg="white").pack(side="left")
        tk.Button(hdr, text="✕", command=self.win.destroy,
                  bg="#1e90ff", fg="white", relief="flat",
                  font=("Arial", 11, "bold"), cursor="hand2").pack(side="right", padx=4)

        # Answer line
        tk.Label(self.win, text=answer, font=("Arial", 13, "bold"),
                 fg="#00ff88", bg="#1a1a2e", wraplength=380,
                 justify="left", padx=10, pady=6).pack(fill="x")

        # Separator
        tk.Frame(self.win, bg="#333", height=1).pack(fill="x", padx=8)

        # Full response (scrollable)
        frame = tk.Frame(self.win, bg="#1a1a2e")
        frame.pack(fill="both", expand=True, padx=6, pady=4)
        text = tk.Text(frame, wrap="word", height=5, font=("Arial", 9),
                       bg="#0f0f1e", fg="#cccccc", relief="flat", bd=0)
        scroll = tk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", full_response)
        text.configure(state="disabled")
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)

        # Auto-close
        self.win.after(ANSWER_DISPLAY_SECONDS * 1000, self._safe_destroy)

    def _safe_destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass


# ── Floating draggable button ─────────────────────────────────────────────────
class FloatingButton:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("")
        self.root.overrideredirect(True)           # no title bar
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg="#1e90ff")
        self.root.resizable(False, False)

        # Start position: centre-right of screen
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"60x60+{sw - 80}+{sh // 2 - 30}")

        # The clickable button
        self.btn = tk.Label(
            self.root, text="G", font=("Arial", 22, "bold"),
            bg="#1e90ff", fg="white", cursor="hand2",
            width=2, height=1
        )
        self.btn.pack(expand=True, fill="both")

        # Drag logic
        self._drag_x = 0
        self._drag_y = 0
        self.btn.bind("<ButtonPress-1>",   self._on_press)
        self.btn.bind("<B1-Motion>",       self._on_drag)
        self.btn.bind("<ButtonRelease-1>", self._on_release)
        self._dragged = False

        # Status colours
        self._idle_color   = "#1e90ff"
        self._busy_color   = "#ff8c00"
        self._answer_popup = None

        # Ctrl+G hotkey — runs in background thread
        keyboard.add_hotkey(HOTKEY, self._toggle_visibility, suppress=False)

        self.root.mainloop()

    # ── drag ──────────────────────────────────────────────────────────────
    def _on_press(self, event):
        self._drag_x = event.x
        self._drag_y = event.y
        self._dragged = False

    def _on_drag(self, event):
        dx = event.x - self._drag_x
        dy = event.y - self._drag_y
        if abs(dx) > 3 or abs(dy) > 3:
            self._dragged = True
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, event):
        # Only fire capture if it was a click, not a drag
        if not self._dragged:
            threading.Thread(target=self._capture_and_ask, daemon=True).start()

    # ── show / hide ───────────────────────────────────────────────────────
    def _toggle_visibility(self):
        # Must run on the Tk main thread
        self.root.after(0, self._do_toggle)

    def _do_toggle(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()
        else:
            self.root.withdraw()

    # ── capture & ask ─────────────────────────────────────────────────────
    def _set_busy(self, busy: bool):
        color = self._busy_color if busy else self._idle_color
        self.root.after(0, lambda: (
            self.btn.configure(bg=color, text="…" if busy else "G"),
            self.root.configure(bg=color)
        ))

    def _capture_and_ask(self):
        self._set_busy(True)
        try:
            # Brief pause so button click isn't captured
            time.sleep(0.35)
            screenshot = pyautogui.screenshot()
            buf = io.BytesIO()
            screenshot.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()

            resp = requests.post(
                f"{BACKEND_URL}/process",
                json={"image": b64},
                timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()

            self._set_busy(False)

            if "error" in result:
                self.root.after(0, lambda: messagebox.showerror("GrokMCQ", result["error"]))
            else:
                bx = self.root.winfo_x()
                by = self.root.winfo_y()
                self.root.after(0, lambda: AnswerPopup(
                    bx, by,
                    result.get("answer", "No answer"),
                    result.get("full_response", "")
                ))

        except requests.exceptions.ConnectionError:
            self._set_busy(False)
            self.root.after(0, lambda: messagebox.showerror(
                "Connection Error",
                f"Cannot reach backend:\n{BACKEND_URL}"
            ))
        except Exception as e:
            self._set_busy(False)
            self.root.after(0, lambda: messagebox.showerror("GrokMCQ Error", str(e)))


def main():
    FloatingButton()


if __name__ == "__main__":
    main()