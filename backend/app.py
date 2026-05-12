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

# Step 1: Scout reads the image and extracts text/question
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Step 2: gpt-oss-120b reasons over extracted text and gives accurate answer
REASONING_MODEL = "openai/gpt-oss-120b"
# ─────────────────────────────────────────────────────────────────────────────


def step1_extract(image_b64: str) -> str:
    """
    Step 1 — Scout reads the screenshot and extracts the question + options as clean text.
    No answering here — just extraction.
    """
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": VISION_MODEL,
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
                    "text": (
                        "Look at this screenshot carefully.\n"
                        "Extract and write out:\n"
                        "1. The full question text\n"
                        "2. All answer options exactly as shown (A, B, C, D etc.)\n"
                        "3. Any relevant context, code, diagram description, or table visible\n\n"
                        "Write it all out as plain text. Do NOT answer the question yet.\n"
                        "Just extract everything you see accurately."
                    )
                }
            ]
        }],
        "max_tokens": 800,
        "temperature": 0,
        "stream": False,
    }

    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)

    if resp.status_code == 429:
        time.sleep(3)
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)

    resp.raise_for_status()
    data = resp.json()

    if "choices" not in data:
        raise Exception(f"Scout unexpected response: {str(data)[:300]}")

    content = data["choices"][0]["message"]["content"]
    if not content or not content.strip():
        raise Exception("Scout returned empty extraction")

    return content.strip()


def step2_answer(extracted_text: str) -> str:
    """
    Step 2 — gpt-oss-120b receives the clean extracted text and gives the accurate answer.
    Pure text reasoning — no image needed here.
    """
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": REASONING_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert in computer science, networking, databases, "
                    "linear algebra, coding, and operating systems. "
                    "You answer MCQ questions with high accuracy. "
                    "Always reply in EXACTLY this format:\n"
                    "ANSWER: [option letter or number]\n"
                    "REASON: [one clear sentence explanation]\n\n"
                    "If it is not an MCQ, answer the question directly and concisely."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Here is a question extracted from a screenshot:\n\n"
                    f"{extracted_text}\n\n"
                    f"What is the correct answer?"
                )
            }
        ],
        "max_tokens": 200,
        "temperature": 0,
        "stream": False,
    }

    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)

    if resp.status_code == 429:
        time.sleep(3)
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)

    resp.raise_for_status()
    data = resp.json()

    if "choices" not in data:
        raise Exception(f"GPT-OSS unexpected response: {str(data)[:300]}")

    content = data["choices"][0]["message"]["content"]
    if not content or not content.strip():
        raise Exception("GPT-OSS returned empty answer")

    return content.strip()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "step1_vision": VISION_MODEL,
        "step2_reasoning": REASONING_MODEL,
        "groq_key_set": bool(GROQ_API_KEY),
        "pipeline": "Scout extracts → GPT-OSS-120B answers",
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

    # ── Step 1: Scout extracts text from image ────────────────────────────
    try:
        extracted_text = step1_extract(data["image"])
    except requests.exceptions.Timeout:
        return jsonify({"error": "Step 1 (Scout) timed out. Try again."}), 504
    except Exception as e:
        return jsonify({"error": f"Step 1 (Scout extraction) failed: {str(e)}"}), 502

    # ── Step 2: GPT-OSS-120B answers from extracted text ─────────────────
    try:
        answer = step2_answer(extracted_text)
    except requests.exceptions.Timeout:
        return jsonify({"error": "Step 2 (GPT-OSS) timed out. Try again."}), 504
    except Exception as e:
        return jsonify({"error": f"Step 2 (GPT-OSS answer) failed: {str(e)}"}), 502

    # Parse ANSWER line for quick display
    quick = answer
    match = re.search(r"ANSWER:\s*([^\n]+)", answer, re.IGNORECASE)
    if match:
        quick = f"✅ {match.group(1).strip()}"

    return jsonify({
        "answer": quick,
        "full_response": answer,
        "extracted_text": extracted_text,
        "model_used": f"Scout → GPT-OSS-120B",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)