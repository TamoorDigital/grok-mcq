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

# Google Gemini (FREE tier: 1,500 requests/day, no credit card needed)
# Get your key at: https://aistudio.google.com/apikey
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-1.5-flash"
GEMINI_URL     = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

# Max width for OCR — resize large screenshots to speed up Tesseract
OCR_MAX_WIDTH = 1280


def extract_text_from_image(image_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(image_bytes))

    # Convert mode
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    # Downscale large screenshots so Tesseract doesn't time out
    if image.width > OCR_MAX_WIDTH:
        ratio = OCR_MAX_WIDTH / image.width
        new_size = (OCR_MAX_WIDTH, int(image.height * ratio))
        image = image.resize(new_size, Image.LANCZOS)

    # Convert to greyscale — faster OCR, same accuracy
    image = image.convert("L")

    # Run OCR without lang param to avoid missing language pack errors
    text = pytesseract.image_to_string(image, timeout=25)
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

If it is not an MCQ, answer it directly and concisely."""

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
    tess_ok = False
    try:
        tess_ok = bool(pytesseract.get_tesseract_version())
    except Exception:
        pass
    return jsonify({"status": "ok", "tesseract": tess_ok})


@app.route("/process", methods=["POST"])
def process():
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
    except RuntimeError as e:
        # Tesseract timeout
        return jsonify({"error": f"OCR timed out — screenshot may be too large: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"OCR failed: {str(e)}"}), 500

    if not ocr_text:
        return jsonify({"error": "No text found in image"}), 422

    # Gemini
    try:
        answer = ask_gemini(ocr_text)
    except Exception as e:
        return jsonify({"error": f"Gemini API error: {str(e)}"}), 502

    # Parse quick answer line
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