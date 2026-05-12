from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import io
import os
import re
import requests
import time

app = Flask(__name__)
CORS(app)

# ─── API KEYS ─────────────────────────────────────────────────────────────────
# Primary:  Gemini 2.5 Flash — best accuracy for coding/db/networking MCQs
# Fallback: Groq             — fastest, kicks in if Gemini hits rate limit
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")

GEMINI_URL  = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent"
GROQ_URL    = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL  = "meta-llama/llama-4-scout-17b-16e-instruct"

# Rate limit tracker — ensures minimum 6s gap between Gemini calls (= max 10/min safe)
_last_gemini_call = 0.0
GEMINI_MIN_INTERVAL = 6.0   # seconds between calls — stays under 10 RPM safely

MCQ_PROMPT = (
    "Look at this screenshot carefully.\n"
    "Find the MCQ question and all its options.\n"
    "Reply ONLY in this exact format:\n"
    "ANSWER: [option letter or number]\n"
    "REASON: [one sentence explanation]\n\n"
    "If there is no MCQ, just answer whatever question is visible. "
    "Be accurate — this is a technical subject (coding, database, networking)."
)
# ─────────────────────────────────────────────────────────────────────────────


def ask_gemini(image_b64: str) -> str:
    """Gemini 2.0 Flash Lite — primary, 30 RPM free tier."""
    global _last_gemini_call
    # Enforce minimum interval to avoid rate limit
    elapsed = time.time() - _last_gemini_call
    if elapsed < GEMINI_MIN_INTERVAL:
        time.sleep(GEMINI_MIN_INTERVAL - elapsed)
    _last_gemini_call = time.time()

    payload = {
        "contents": [{
            "parts": [
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": image_b64
                    }
                },
                {
                    "text": MCQ_PROMPT
                }
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 300,
        }
    }

    resp = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=30,
    )

    # 429 = rate limited — raise so fallback kicks in
    if resp.status_code == 429:
        raise Exception("RATE_LIMIT")

    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def ask_groq(image_b64: str) -> str:
    """Groq Llama 4 Scout — fallback, ultra fast."""
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

    if resp.status_code == 429:
        time.sleep(2)
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)

    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def get_answer(image_b64: str) -> tuple[str, str, str]:
    """
    Try Gemini first (accuracy), fall back to Groq (speed).
    Returns (answer, model_used, fallback_reason)
    """
    fallback_reason = ""

    # Try Gemini if key is set
    if GEMINI_API_KEY:
        try:
            answer = ask_gemini(image_b64)
            return answer, "gemini-2.0-flash-lite", ""
        except Exception as e:
            err = str(e)
            if "RATE_LIMIT" in err:
                fallback_reason = "Gemini rate limit hit (10 RPM) — switched to Groq"
            else:
                fallback_reason = f"Gemini failed ({err[:80]}) — switched to Groq"

    # Fallback to Groq
    if GROQ_API_KEY:
        answer = ask_groq(image_b64)
        return answer, "groq-llama4-scout", fallback_reason

    raise Exception("No API keys configured. Set GEMINI_API_KEY and/or GROQ_API_KEY in Render.")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "primary": "Gemini 2.5 Flash" if GEMINI_API_KEY else "NOT SET",
        "fallback": "Groq Llama 4 Scout" if GROQ_API_KEY else "NOT SET",
        "gemini_key_set": bool(GEMINI_API_KEY),
        "groq_key_set": bool(GROQ_API_KEY),
    })


@app.route("/process", methods=["POST"])
def process():
    if not GEMINI_API_KEY and not GROQ_API_KEY:
        return jsonify({"error": "No API keys set. Add GEMINI_API_KEY and GROQ_API_KEY in Render environment."}), 500

    data = request.get_json(force=True)
    if not data or "image" not in data:
        return jsonify({"error": "Missing 'image' field"}), 400

    try:
        base64.b64decode(data["image"])
    except Exception:
        return jsonify({"error": "Invalid base64 image"}), 400

    try:
        answer, model_used, fallback_reason = get_answer(data["image"])
    except requests.exceptions.Timeout:
        return jsonify({"error": "API timed out. Try again."}), 504
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
        "fallback_reason": fallback_reason,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)