from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import os
import re
import requests
import time

app = Flask(__name__)
CORS(app)

# ─── Groq API ─────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

# Primary: maverick = most accurate vision model on Groq
# Fallback: scout   = always works, slightly less accurate
PRIMARY_MODEL  = "meta-llama/llama-4-maverick-17b-128e-instruct"
FALLBACK_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

MCQ_PROMPT = (
    "Look at this screenshot carefully.\n"
    "Find the MCQ question and all its options.\n"
    "Reply ONLY in this exact format:\n"
    "ANSWER: [option letter or number]\n"
    "REASON: [one sentence explanation]\n\n"
    "If there is no MCQ, just answer whatever question is visible.\n"
    "Be accurate — this may be about coding, database, networking, or linear algebra."
)
# ─────────────────────────────────────────────────────────────────────────────


def call_groq(model: str, image_b64: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{
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
                    "text": MCQ_PROMPT
                }
            ]
        }],
        "max_tokens": 200,
        "temperature": 0,
        "stream": False,
    }

    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)

    # Rate limited — wait and retry
    if resp.status_code == 429:
        time.sleep(3)
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)

    # Raise for any other HTTP error
    resp.raise_for_status()

    data = resp.json()

    # Safe extraction with full debug on failure
    if "choices" not in data:
        raise Exception(f"Unexpected response: {str(data)[:300]}")

    content = data["choices"][0]["message"]["content"]
    if not content or not content.strip():
        raise Exception("Model returned empty response")

    return content.strip()


def get_answer(image_b64: str) -> tuple:
    # Try primary model first
    try:
        answer = call_groq(PRIMARY_MODEL, image_b64)
        return answer, PRIMARY_MODEL
    except Exception as e:
        primary_err = str(e)

    # Fallback to scout
    try:
        answer = call_groq(FALLBACK_MODEL, image_b64)
        return answer, FALLBACK_MODEL
    except Exception as e:
        raise Exception(
            f"Both models failed.\n"
            f"Maverick: {primary_err}\n"
            f"Scout: {str(e)}"
        )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "primary_model": PRIMARY_MODEL,
        "fallback_model": FALLBACK_MODEL,
        "groq_key_set": bool(GROQ_API_KEY),
    })


@app.route("/process", methods=["POST"])
def process():
    if not GROQ_API_KEY:
        return jsonify({"error": "GROQ_API_KEY not set in Render environment variables"}), 500

    data = request.get_json(force=True)
    if not data or "image" not in data:
        return jsonify({"error": "Missing 'image' field"}), 400

    try:
        base64.b64decode(data["image"])
    except Exception:
        return jsonify({"error": "Invalid base64 image"}), 400

    try:
        answer, model_used = get_answer(data["image"])
    except requests.exceptions.Timeout:
        return jsonify({"error": "Groq API timed out. Try again."}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    # Parse ANSWER line
    quick = answer
    match = re.search(r"ANSWER:\s*([^\n]+)", answer, re.IGNORECASE)
    if match:
        quick = f"✅ {match.group(1).strip()}"

    return jsonify({
        "answer": quick,
        "full_response": answer,
        "model_used": model_used,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)