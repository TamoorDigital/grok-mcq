from flask import Flask, request, jsonify
from flask_cors import CORS
import pytesseract
from PIL import Image
import base64
import io
import os
import re
import requests

app = Flask(__name__)
CORS(app)

# ─── Groq API (FREE — 1-3 second responses) ──────────────────────────────────
# Get free key at: https://console.groq.com  (no credit card)
# Free limits: 30 requests/min, 14,400/day — more than enough
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

# Models available on Groq (all free, ultra fast):
# "llama-3.1-8b-instant"   — fastest, great for MCQs  ← DEFAULT
# "llama-3.3-70b-versatile" — more accurate, still fast
# "mixtral-8x7b-32768"     — good balance
GROQ_MODEL = "llama-3.3-70b-versatile"

OCR_MAX_WIDTH = 1280


def extract_text_from_image(image_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if image.width > OCR_MAX_WIDTH:
        ratio = OCR_MAX_WIDTH / image.width
        new_size = (OCR_MAX_WIDTH, int(image.height * ratio))
        image = image.resize(new_size, Image.LANCZOS)
    image = image.convert("L")
    text = pytesseract.image_to_string(image, timeout=25)
    return text.strip()


def ask_groq(question_text: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert at answering MCQ questions. "
                    "Always reply in this exact format:\n"
                    "ANSWER: [option letter or number]\n"
                    "REASON: [one sentence explanation]\n"
                    "Be fast and concise."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Answer this MCQ from the screenshot text below:\n\n"
                    f"{question_text[:2000]}"
                )
            }
        ],
        "max_tokens": 150,
        "temperature": 0,
        "stream": False,
    }

    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=15)

    if resp.status_code == 429:
        # Rate limited — retry once after 2 seconds
        import time
        time.sleep(2)
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=15)

    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


@app.route("/health", methods=["GET"])
def health():
    tess_ok = False
    try:
        tess_ok = bool(pytesseract.get_tesseract_version())
    except Exception:
        pass
    return jsonify({
        "status": "ok",
        "tesseract": tess_ok,
        "model": GROQ_MODEL,
        "groq_key_set": bool(GROQ_API_KEY),
    })


@app.route("/process", methods=["POST"])
def process():
    if not GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY not set in Render environment variables"}), 500

    data = request.get_json(force=True)
    if not data or "image" not in data:
        return jsonify({"error": "Missing 'image' field"}), 400

    # Decode image
    try:
        image_data = base64.b64decode(data["image"])
    except Exception:
        return jsonify({"error": "Invalid base64 image"}), 400

    # OCR
    try:
        ocr_text = extract_text_from_image(image_data)
    except RuntimeError as e:
        return jsonify({"error": f"OCR timed out: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"OCR failed: {str(e)}"}), 500

    if not ocr_text:
        return jsonify({"error": "No text found in screenshot."}), 422

    # Groq
    try:
        answer = ask_groq(ocr_text)
    except Exception as e:
        return jsonify({"error": f"Groq API error: {str(e)}"}), 502

    # Parse ANSWER line
    quick = answer
    match = re.search(r"ANSWER:\s*([^\n]+)", answer, re.IGNORECASE)
    if match:
        quick = f"✅ {match.group(1).strip()}"

    return jsonify({
        "ocr_text": ocr_text,
        "answer": quick,
        "full_response": answer,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)