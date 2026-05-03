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

# ─── Hugging Face Inference API (FREE, no credit card) ───────────────────────
# Get your free token at: https://huggingface.co/settings/tokens
# Free tier: unlimited requests, rate limited but reliable
HF_API_KEY  = os.environ.get("HF_API_KEY", "")

# Model options (all free, uncomment the one you want):
# Fast + accurate for Q&A:
HF_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
# Lighter/faster fallback:
# HF_MODEL = "microsoft/Phi-3-mini-4k-instruct"
# Very fast, smaller:
# HF_MODEL = "HuggingFaceH4/zephyr-7b-beta"

HF_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
# ─────────────────────────────────────────────────────────────────────────────

OCR_MAX_WIDTH = 1280


def extract_text_from_image(image_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(image_bytes))

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    # Downscale large screenshots so Tesseract doesn't time out
    if image.width > OCR_MAX_WIDTH:
        ratio = OCR_MAX_WIDTH / image.width
        new_size = (OCR_MAX_WIDTH, int(image.height * ratio))
        image = image.resize(new_size, Image.LANCZOS)

    # Greyscale = faster OCR
    image = image.convert("L")

    text = pytesseract.image_to_string(image, timeout=25)
    return text.strip()


def ask_hf(question_text: str) -> str:
    prompt = f"""<s>[INST] You are an expert at answering MCQ (Multiple Choice Questions).
Analyze the text below extracted from a screenshot.

TEXT:
{question_text}

Instructions:
1. Identify the question and all options (A, B, C, D or 1, 2, 3, 4 etc.)
2. Determine the correct answer.
3. Reply ONLY in this exact format:
   ANSWER: [option letter/number]
   REASON: [one sentence explanation]

If it is not an MCQ, answer it directly and concisely. [/INST]"""

    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 200,
            "temperature": 0.1,
            "return_full_text": False,
            "stop": ["</s>", "[INST]"]
        },
        "options": {
            "wait_for_model": True,   # wait if model is loading instead of error
            "use_cache": False
        }
    }

    response = requests.post(HF_URL, headers=headers, json=payload, timeout=60)

    # If model is loading, HF returns 503 — wait_for_model handles this
    response.raise_for_status()
    data = response.json()

    # HF returns a list
    if isinstance(data, list) and len(data) > 0:
        return data[0].get("generated_text", "").strip()
    elif isinstance(data, dict) and "error" in data:
        raise Exception(f"HF model error: {data['error']}")
    else:
        return str(data).strip()


@app.route("/health", methods=["GET"])
def health():
    tess_ok = False
    try:
        tess_ok = bool(pytesseract.get_tesseract_version())
    except Exception:
        pass
    return jsonify({"status": "ok", "tesseract": tess_ok, "model": HF_MODEL})


@app.route("/process", methods=["POST"])
def process():
    if not HF_API_KEY:
        return jsonify({"error": "HF_API_KEY not configured on server"}), 500

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
        return jsonify({"error": f"OCR timed out: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"OCR failed: {str(e)}"}), 500

    if not ocr_text:
        return jsonify({"error": "No text found in image"}), 422

    # Hugging Face
    try:
        answer = ask_hf(ocr_text)
    except Exception as e:
        return jsonify({"error": f"HuggingFace API error: {str(e)}"}), 502

    if not answer:
        return jsonify({"error": "Model returned empty response"}), 502

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