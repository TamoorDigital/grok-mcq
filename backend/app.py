from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import os
import re
import requests
import time

app = Flask(__name__)
CORS(app)

# ─── Groq API — Primary (fast + accurate with 70B model) ─────────────────────
# Free: 14,400 requests/day, 30 RPM, no rate limit issues
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

# llama-3.3-70b — much more accurate than 8B for coding/db/networking
# still very fast on Groq LPU hardware (2-4 seconds)
GROQ_MODEL = "llama-3.3-70b-versatile"

MCQ_PROMPT = (
    "Look at this screenshot carefully.\n"
    "Find the MCQ question and all its options.\n"
    "Reply ONLY in this exact format:\n"
    "ANSWER: [option letter or number]\n"
    "REASON: [one sentence explanation]\n\n"
    "If there is no MCQ, just answer whatever question is visible.\n"
    "Be accurate — this may be about coding, database, networking, or OS."
)
# ─────────────────────────────────────────────────────────────────────────────


def ask_groq(image_b64: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"}
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

    # Rate limited — wait and retry once
    if resp.status_code == 429:
        time.sleep(3)
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
        "daily_limit": "14,400 requests",
        "rpm_limit": "30 RPM",
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
        answer = ask_groq(data["image"])
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
        "model_used": GROQ_MODEL,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)