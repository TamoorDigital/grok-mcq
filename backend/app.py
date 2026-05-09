from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import io
import os
import re
import requests

app = Flask(__name__)
CORS(app)

# ─── Groq API with Vision — NO Tesseract needed ───────────────────────────────
# Get free key at: https://console.groq.com  (no credit card)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

# Vision model — reads image AND answers MCQ in one call, 1-3 seconds
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
# ─────────────────────────────────────────────────────────────────────────────


def ask_groq_vision(image_b64: str) -> str:
    """Send image directly to Groq Vision — no OCR step needed."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "Look at this screenshot carefully.\n"
                            "Find the MCQ question and all its options.\n"
                            "Reply ONLY in this exact format:\n"
                            "ANSWER: [option letter or number]\n"
                            "REASON: [one sentence explanation]\n\n"
                            "If there is no MCQ, just answer whatever question is visible."
                        )
                    }
                ]
            }
        ],
        "max_tokens": 200,
        "temperature": 0,
        "stream": False,
    }

    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)

    if resp.status_code == 429:
        import time
        time.sleep(2)
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)

    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "model": GROQ_MODEL,
        "groq_key_set": bool(GROQ_API_KEY),
        "ocr": "disabled — using vision model directly",
    })


@app.route("/process", methods=["POST"])
def process():
    if not GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY not set in Render environment variables"}), 500

    data = request.get_json(force=True)
    if not data or "image" not in data:
        return jsonify({"error": "Missing 'image' field"}), 400

    # Validate base64
    try:
        base64.b64decode(data["image"])
    except Exception:
        return jsonify({"error": "Invalid base64 image"}), 400

    # Send image directly to Groq Vision — no OCR at all
    try:
        answer = ask_groq_vision(data["image"])
    except requests.exceptions.Timeout:
        return jsonify({"error": "Groq API timed out. Try again."}), 504
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"Groq API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

    # Parse ANSWER line for quick display
    quick = answer
    match = re.search(r"ANSWER:\s*([^\n]+)", answer, re.IGNORECASE)
    if match:
        quick = f"✅ {match.group(1).strip()}"

    return jsonify({
        "answer": quick,
        "full_response": answer,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)