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

# ─── FIX: Set Tesseract path (required on Render) ───
pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

# ─── Gemini Config ───
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


# ─── OCR Function ───
def extract_text_from_image(image_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(image_bytes))

    # Ensure proper format
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    text = pytesseract.image_to_string(image, lang="eng")
    return text.strip()


# ─── Gemini Function ───
def ask_gemini(question_text: str) -> str:
    prompt = f"""You are an expert answering MCQ (Multiple Choice Questions).
Analyze the following text extracted from a screenshot.

TEXT:
{question_text}

Instructions:
1. Identify the question and options.
2. Select the correct answer.
3. Reply ONLY in this format:
   ANSWER: [option]
   REASON: [short explanation]

If it's not MCQ, answer directly."""

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


# ─── Root Route ───
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Grok MCQ Backend Running 🚀",
        "endpoints": ["/health", "/process"]
    })


# ─── Health Check (SAFE) ───
@app.route("/health", methods=["GET"])
def health():
    try:
        version = str(pytesseract.get_tesseract_version())
        tesseract_status = True
    except Exception as e:
        version = str(e)
        tesseract_status = False

    return jsonify({
        "status": "ok",
        "tesseract": tesseract_status,
        "version": version
    })


# ─── Main API ───
@app.route("/process", methods=["POST"])
def process():
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not configured"}), 500

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
    except Exception as e:
        return jsonify({"error": f"OCR failed: {str(e)}"}), 500

    if not ocr_text:
        return jsonify({"error": "No text found"}), 422

    # Gemini
    try:
        answer = ask_gemini(ocr_text)
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Gemini request failed: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": f"Gemini error: {str(e)}"}), 500

    # Extract quick answer
    quick = answer
    match = re.search(r"ANSWER:\s*([^\n]+)", answer)
    if match:
        quick = f"✅ {match.group(1).strip()}"

    return jsonify({
        "ocr_text": ocr_text,
        "answer": quick,
        "full_response": answer
    })


# ─── Run (local only) ───
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)