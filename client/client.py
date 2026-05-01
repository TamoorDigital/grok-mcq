"""
GrokMCQ Client
--------------
A small floating icon on your screen. Click it to:
1. Capture the screen
2. Send to the hosted backend for OCR + Grok analysis
3. Display the answer next to the icon

Build to EXE:
    pip install pyinstaller pyautogui Pillow requests pystray
    pyinstaller --onefile --windowed --icon=icon.ico client.py
"""

import base64
import io
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

import pystray
from PIL import Image, ImageDraw, ImageFont
import pyautogui
import requests

# ─── CONFIG ───────────────────────────────────────────────────────────────────
# Replace with your Render backend URL after deploying
BACKEND_URL = os.environ.get(
    "GROK_MCQ_BACKEND",
    "https://grok-mcq-backend.onrender.com"  # <-- update this after deploy
)
CAPTURE_HOTKEY = None          # optional future hotkey support
ANSWER_DISPLAY_SECONDS = 15    # how long to show the answer popup
# ──────────────────────────────────────────────────────────────────────────────


def make_icon_image(label: str = "G") -> Image.Image:
    """Create a simple circular icon with a letter."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Circle background
    draw.ellipse([2, 2, size - 2, size - 2], fill=(30, 144, 255, 230))
    # Letter
    try:
        font = ImageFont.truetype("arial.ttf", 30)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 2), label, fill="white", font=font)
    return img


class AnswerPopup:
    """A small always-on-top window that shows the answer."""

    def __init__(self, answer: str, full_response: str):
        self.root = tk.Tk()
        self.root.title("GrokMCQ Answer")
        self.root.attributes("-topmost", True)
        self.root.resizable(True, True)

        # Position near bottom-right
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"420x200+{sw - 440}+{sh - 240}")

        # Header
        tk.Label(
            self.root, text="🤖 GrokMCQ Answer",
            font=("Arial", 12, "bold"), bg="#1e90ff", fg="white",
            padx=8, pady=4
        ).pack(fill="x")

        # Answer
        tk.Label(
            self.root, text=answer,
            font=("Arial", 14, "bold"), fg="#1e7e34",
            wraplength=400, justify="left", padx=10, pady=6
        ).pack(fill="x")

        # Full response (scrollable)
        frame = tk.Frame(self.root)
        frame.pack(fill="both", expand=True, padx=6, pady=4)
        text = tk.Text(frame, wrap="word", height=5, font=("Arial", 9))
        scroll = tk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", full_response)
        text.configure(state="disabled")
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)

        tk.Button(
            self.root, text="Close", command=self.root.destroy,
            bg="#dc3545", fg="white", font=("Arial", 10, "bold")
        ).pack(pady=4)

        # Auto-close
        self.root.after(ANSWER_DISPLAY_SECONDS * 1000, self.root.destroy)
        self.root.mainloop()


class LoadingPopup:
    """Tiny 'Processing…' popup while waiting for the backend."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"200x50+{sw - 220}+{sh - 80}")
        tk.Label(
            self.root, text="⏳ Processing screenshot…",
            font=("Arial", 10), bg="#333", fg="white", padx=10, pady=10
        ).pack()
        self.root.update()

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass


def capture_screen() -> bytes:
    """Capture the entire screen and return PNG bytes."""
    screenshot = pyautogui.screenshot()
    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    return buf.getvalue()


def send_to_backend(image_bytes: bytes) -> dict:
    """POST image to backend, return JSON response."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    resp = requests.post(
        f"{BACKEND_URL}/process",
        json={"image": b64},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def on_click(icon, item=None):
    """Called when the tray icon is clicked."""
    def run():
        loading = LoadingPopup()
        try:
            # Small delay so the tray click doesn't appear in screenshot
            time.sleep(0.4)
            image_bytes = capture_screen()
            result = send_to_backend(image_bytes)
            loading.close()
            if "error" in result:
                messagebox.showerror("GrokMCQ Error", result["error"])
            else:
                AnswerPopup(result.get("answer", "No answer"), result.get("full_response", ""))
        except requests.exceptions.ConnectionError:
            loading.close()
            messagebox.showerror(
                "Connection Error",
                f"Cannot reach backend:\n{BACKEND_URL}\n\nMake sure it is deployed and running."
            )
        except Exception as e:
            loading.close()
            messagebox.showerror("GrokMCQ Error", str(e))

    threading.Thread(target=run, daemon=True).start()


def main():
    icon_image = make_icon_image("G")
    menu = pystray.Menu(
        pystray.MenuItem("📸 Capture & Ask Grok", on_click, default=True),
        pystray.MenuItem("❌ Quit", lambda icon, item: icon.stop()),
    )
    icon = pystray.Icon("GrokMCQ", icon_image, "GrokMCQ – Click to capture", menu)
    icon.run()


if __name__ == "__main__":
    main()
