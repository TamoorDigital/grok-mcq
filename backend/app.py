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

# ─── Google Gemini (FREE tier: 1,500 requests/day, no credit card needed) ────
# Get your key at: https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-1.5-flash"   # fastest free model
GEMINI_URL     = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
# ─────────────────────────────────────────────────────────────────────────────


def extract_text_from_image(image_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(image_bytes))
    # Convert to RGB if needed (handles RGBA, palette modes)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    text = pytesseract.image_to_string(image)
    return text.strip()


def ask_gemini(question_text: str) -> str:
    prompt = f"""You are an expert answering MCQ (Multiple Choice Questions).
Analyze the following text extracted from a screenshot. It may contain an MCQ question with options.

TEXT:
{question_text}

Instructions:
1. Identify the question and all options (A, B, C, D or 1, 2, 3, 4 etc.)
2. Determine the correct answer.
3. Reply ONLY in this exact format:
   ANSWER: [option letter/number]
   REASON: [one sentence explanation]

If it's not an MCQ, answer it directly and concisely."""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 300},
    }

    response = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "tesseract": bool(pytesseract.get_tesseract_version())})


@app.route("/process", methods=["POST"])
def process():
    """
    Accepts JSON: { "image": "<base64-encoded PNG/JPG>" }
    Returns:      { "ocr_text": "...", "answer": "...", "full_response": "..." }
    """
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not configured on server"}), 500

    data = request.get_json(force=True)
    if not data or "image" not in data:
        return jsonify({"error": "Missing 'image' field in request body"}), 400

    # Decode base64 image
    try:
        image_data = base64.b64decode(data["image"])
    except Exception:
        return jsonify({"error": "Invalid base64 image data"}), 400

    # OCR
    try:
        ocr_text = extract_text_from_image(image_data)
    except Exception as e:
        return jsonify({"error": f"OCR failed: {str(e)}"}), 500

    if not ocr_text:
        return jsonify({"error": "No text found in image"}), 422

    # Gemini
    try:
        answer = ask_gemini(ocr_text)
    except Exception as e:
        return jsonify({"error": f"Gemini API error: {str(e)}"}), 502

    # Parse answer line for quick display
    quick = answer
    match = re.search(r"ANSWER:\s*([^\n]+)", answer)
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
