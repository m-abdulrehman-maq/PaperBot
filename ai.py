"""Gemini helpers: PDF ingestion, solutions, MCQs and practice questions.

Gemini is called over plain REST (no SDK) so there are no heavy dependencies.
It can read a PDF directly (inline_data), which removes the need for a
separate OCR / text-extraction step.
"""
import json
import base64
import urllib.request
import urllib.error

import config

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _call(parts, json_mode=False, timeout=120):
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    url = f"{_BASE}/{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
    body = {"contents": [{"parts": parts}]}
    if json_mode:
        body["generationConfig"] = {"response_mime_type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400]
        raise RuntimeError(f"Gemini HTTP {e.code}: {detail}") from e


def text(prompt, json_mode=False, timeout=120):
    return _call([{"text": prompt}], json_mode=json_mode, timeout=timeout)


def _pdf_parts(prompt, pdf_bytes):
    return [
        {"text": prompt},
        {"inline_data": {"mime_type": "application/pdf",
                         "data": base64.b64encode(pdf_bytes).decode("ascii")}},
    ]


def extract_text_from_pdf(pdf_bytes):
    """Return the raw readable text of the paper (best effort)."""
    prompt = ("Extract ALL readable text from this exam paper exactly as written. "
              "Return plain text only, preserving question numbering.")
    try:
        return _call(_pdf_parts(prompt, pdf_bytes), timeout=120)
    except Exception:
        return ""


def structure_questions(pdf_bytes):
    """Return a list of {q_number, q_text, topic, difficulty, marks}."""
    prompt = (
        "You are parsing a university exam paper. Return ONLY a JSON array. "
        "Each element must have keys: q_number (string), q_text (string), "
        "topic (short topic name), difficulty (easy|medium|hard), "
        "marks (number or null). Split into individual questions/sub-questions. "
        "Infer topic and difficulty from the content.")
    raw = _call(_pdf_parts(prompt, pdf_bytes), json_mode=True, timeout=120)
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    cleaned = []
    for q in data:
        if not isinstance(q, dict) or not q.get("q_text"):
            continue
        diff = str(q.get("difficulty", "")).lower()
        cleaned.append({
            "q_number": str(q.get("q_number") or "")[:32],
            "q_text": str(q["q_text"])[:4000],
            "topic": str(q.get("topic") or "")[:120],
            "difficulty": diff if diff in ("easy", "medium", "hard") else None,
            "marks": _num(q.get("marks")),
        })
    return cleaned


def generate_solution(pdf_bytes=None, paper_text=None):
    prompt = (
        "Solve this exam paper completely and clearly for a student. For each "
        "question give the final answer and a concise worked explanation. Use "
        "plain text with clear question numbers. Keep it accurate.")
    if pdf_bytes:
        return _call(_pdf_parts(prompt, pdf_bytes), timeout=180)
    return text(f"{prompt}\n\nPaper:\n{paper_text or ''}", timeout=180)


def generate_mcqs(paper_text):
    prompt = (
        "Based on the topics in this exam paper, create 10 multiple-choice "
        "questions (4 options each) that test the same concepts. After all "
        "questions, add an 'Answers:' section with the correct option letters. "
        "Plain text only.")
    return text(f"{prompt}\n\nPaper:\n{paper_text or ''}", timeout=120)


def generate_practice(paper_text):
    prompt = (
        "Based on the topics in this exam paper, create 6 fresh practice "
        "questions of similar style and difficulty (not copies). Add brief "
        "answer hints at the end. Plain text only.")
    return text(f"{prompt}\n\nPaper:\n{paper_text or ''}", timeout=120)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
