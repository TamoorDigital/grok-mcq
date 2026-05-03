from flask import Flask, request, jsonify
from flask_cors import CORS
import pytesseract
from PIL import Image
import base64
import io
import os
import re
import requests
import time

app = Flask(__name__)
CORS(app)

# ─── Hugging Face Inference API ───────────────────────────────────────────────
HF_API_KEY = os.environ.get("HF_API_KEY", "")

# Primary model — fast and reliable for MCQs
PRIMARY_MODEL  = "mistralai/Mistral-7B-Instruct-v0.3"
# Fallback model — much lighter, almost always available
FALLBACK_MODEL = "microsoft/Phi-3-mini-4k-instruct"

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


def call_hf_model(model: str, prompt: str, timeout: int = 45) -> str:
    """Call a single HF model. Raises on failure."""
    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 150,
            "temperature": 0.1,
            "return_full_text": False,
            "do_sample": False,
        },
        "options": {
            "wait_for_model": True,
            "use_cache": False,
        }
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

    # 503 = model still loading — wait_for_model should handle it
    # but if it still 503s, raise clearly
    if resp.status_code == 503:
        raise Exception(f"Model {model} is loading, try again in 20 seconds")

    if resp.status_code != 200:
        raise Exception(f"HF returned {resp.status_code}: {resp.text[:200]}")

    data = resp.json()

    if isinstance(data, list) and len(data) > 0:
        text = data[0].get("generated_text", "").strip()
        if text:
            return text
        raise Exception("Model returned empty text")

    if isinstance(data, dict):
        if "error" in data:
            raise Exception(f"Model error: {data['error']}")
        if "generated_text" in data:
            return data["generated_text"].strip()

    raise Exception(f"Unexpected response format: {str(data)[:200]}")


def ask_hf(question_text: str) -> str:
    """Try primary model, fall back to secondary on failure."""
    prompt = (
        f"[INST] You answer MCQ questions.\n\n"
        f"TEXT FROM SCREENSHOT:\n{question_text[:1500]}\n\n"
        f"Find the question and options. Reply in EXACTLY this format:\n"
        f"ANSWER: [letter]\n"
        f"REASON: [one sentence]\n\n"
        f"If no MCQ found, just answer the question directly. [/INST]"
    )

    # Try primary model first
    try:
        return call_hf_model(PRIMARY_MODEL, prompt, timeout=50)
    except Exception as e1:
        primary_error = str(e1)

    # Try fallback model
    try:
        return call_hf_model(FALLBACK_MODEL, prompt, timeout=50)
    except Exception as e2:
        raise Exception(
            f"Both models failed.\n"
            f"Primary ({PRIMARY_MODEL}): {primary_error}\n"
            f"Fallback ({FALLBACK_MODEL}): {str(e2)}"
        )


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
        "primary_model": PRIMARY_MODEL,
        "fallback_model": FALLBACK_MODEL,
        "hf_key_set": bool(HF_API_KEY),
    })


@app.route("/process", methods=["POST"])
def process():
    if not HF_API_KEY:
        return jsonify({"error": "HF_API_KEY not set in Render environment variables"}), 500

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
        return jsonify({"error": "No text found in screenshot. Make sure text is visible on screen."}), 422

    # Ask HF
    try:
        answer = ask_hf(ocr_text)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    # Parse the ANSWER line for quick display
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