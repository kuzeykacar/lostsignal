"""LostSignal agent: turns a confused, anonymous student message into a clear
question for the professor. All LLM calls go through OpenAI.

Pipeline (orchestrated by app.py):
  1. moderate()        - block only real violations (insults, violence...)
  2. analyze()         - is it about this course? what is the student confused about?
                         returns either a clarified question or 1 diagnostic question
  3. refine()          - uses the student's answer to the diagnostic question
  4. find_similar()    - looks for an existing question with the same meaning
  5. weekly_report()   - aggregates all questions for the professor
"""
import base64
import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.9"))
_client = None


def client():
    global _client
    if _client is None:
        _client = OpenAI()  # reads OPENAI_API_KEY from .env
    return _client


def _image_part(file_bytes, mime, name="upload.pdf"):
    b64 = base64.b64encode(file_bytes).decode()
    if mime == "application/pdf":
        return {"type": "file", "file": {"filename": name, "file_data": f"data:application/pdf;base64,{b64}"}}
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _ask_json(system, user_text, image=None):
    content = [{"type": "text", "text": user_text}]
    if image:
        content.append(_image_part(*image))
    resp = client().chat.completions.create(
        model=MODEL,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": content}],
    )
    return json.loads(resp.choices[0].message.content)


# ---------- 1. Safety ----------
def moderate(text):
    """Return (ok, reason). Only real violations are blocked."""
    try:
        r = client().moderations.create(model="omni-moderation-latest", input=text)
        res = r.results[0]
        if res.flagged:
            cats = [k for k, v in res.categories.model_dump().items() if v]
            return False, ", ".join(cats)
    except Exception:
        pass  # if moderation is unavailable, the LLM check below still runs
    data = _ask_json(
        "You check anonymous student messages sent to a professor. "
        "Block ONLY clear insults, harassment, threats, violence, hate or sexual content. "
        "Informal, rude-sounding confusion ('I don't get this stupid formula') is ALLOWED. "
        'Return JSON {"violation": bool, "reason": str}.',
        text,
    )
    return (not data.get("violation", False)), data.get("reason", "")


# ---------- 2. Understand the confusion ----------
SYSTEM_ANALYZE = """You are LostSignal, an assistant inside a university lecture.
A student wrote an anonymous, possibly messy message because they did not understand something.
Your job is NOT to answer or teach. Your job is to find out what the student did not understand
and turn it into one clear question for the professor.

Course context (may be incomplete):
{context}

Rules:
- Use only the student's message, the optional photo and the course context. Never invent lecture content.
- First decide if the message is about THIS course. If not, set on_topic=false.
- If SEVERAL parts of the material could match (e.g. 'this theorem' when the lecture has Fermat, Rolle, Lagrange and Cauchy), do NOT guess: ask a diagnostic question listing those candidates.
- If the confusion is clear enough, write the clarified question about ONE specific thing.
- If it is too vague (e.g. "I didn't get anything"), ask ONE short diagnostic question with 2-4
  concrete options built from the course context and the message, plus an option "Something else".
- ALWAYS write everything (diagnostic question, options, clarified question, topic, reasons) in ENGLISH, whatever language the student or the material uses.

Return JSON:
{{"on_topic": bool,
  "off_topic_reason": str,
  "topic": str,                     // short course topic, e.g. "Integrals - constant of integration"
  "needs_diagnosis": bool,
  "diagnostic_question": str,
  "options": [str],
  "clarified_question": str,
  "source": str}}                   // where in the photo/PDF/course material this comes from, use the PDF page number counted from 1, e.g. "Page 19: Theorem (Rolle)". Empty if not found. Never invent a page."""


def analyze(message, context, image=None, history=None):
    text = f"Student message: {message}"
    if history:
        text += "\nPrevious clarification steps:\n" + "\n".join(history)
    return _ask_json(SYSTEM_ANALYZE.format(context=context), text, image)


def refine(message, context, chosen_option, history, image=None):
    """Called after the student answers a diagnostic question."""
    history = history + [f"Diagnostic answer from the student: {chosen_option}"]
    return analyze(message, context, image, history)


def rewrite_with_correction(message, context, wrong_version, correction, image=None):
    """Student said 'no, that's not my question' and explained more."""
    history = [f"You proposed: {wrong_version}",
               f"The student said this is NOT their question and added: {correction}"]
    return analyze(message, context, image, history)


# ---------- 3. Similar questions ----------
def find_similar(question, existing):
    """existing: list of dicts with id and text. Returns (best_id, score) or (None, 0)."""
    if not existing:
        return None, 0.0
    listing = "\n".join(f"{q['id']}: {q['text']}" for q in existing)
    data = _ask_json(
        "Decide if a new student question asks EXACTLY the same thing as an existing one. "
        "Same topic is NOT enough: the specific doubt must be the same. Be strict. "
        'Return JSON {"best_id": str or null, "score": number between 0 and 1}.',
        f"New question: {question}\n\nExisting questions:\n{listing}",
    )
    score = float(data.get("score") or 0)
    if data.get("best_id") and score >= SIMILARITY_THRESHOLD:
        return data["best_id"], score
    return None, score


# ---------- 4. Weekly report for the professor ----------
def weekly_report(questions, context):
    listing = "\n".join(f"- ({q['count']} students) [{q['topic']}] {q['text']}" for q in questions)
    data = _ask_json(
        "You write a short weekly report for a professor from anonymous student questions. "
        "No student names exist. Do not invent anything not in the list. Write in English. "
        'Return JSON {"top_topics": [{"topic": str, "students": int, "what_is_unclear": str}], '
        '"suggestion": str}.',
        f"Course context:\n{context}\n\nQuestions this week:\n{listing}",
    )
    return data


# ---------- 5. Course material from a PDF ----------
def pdf_to_notes(pdf_bytes, name):
    """Extract the key course content of a PDF (slides/notes) as plain text."""
    content = [{"type": "text", "text": "Extract the course content of this document as compact plain-text notes "
                "in English: topics, definitions, formulas, examples, with slide/page numbers when visible. "
                "Do not add anything that is not in the document."},
               _image_part(pdf_bytes, "application/pdf", name)]
    resp = client().chat.completions.create(model=MODEL, temperature=0,
                                            messages=[{"role": "user", "content": content}])
    return resp.choices[0].message.content


# ---------- 6. Personal learning brief (student side only) ----------
def learning_brief(history, context):
    """history: this student's own confirmed questions over time. Never shown to the professor."""
    listing = "\n".join(f"- [{h.get('topic','')}] {h['question']} (confused message: {h.get('raw','')})" for h in history)
    return _ask_json(
        "You help ONE student understand their own learning gaps from the questions they asked over time. "
        "Base everything only on their questions and the course context. Do not invent. Write in English. "
        "Be kind and concrete. Return JSON {"
        '"weak_spots": [{"topic": str, "times_asked": int, "what_is_missing": str}], '
        '"root_gap": str,            // the earlier concept that probably causes several doubts, or "" '
        '"study_order": [str],       // what to review first, using course topics '
        '"pattern": str,             // e.g. "you get the idea but lose track in the proof steps" '
        '"prompt_for_ai_tutor": str  // a ready prompt the student can paste into any AI tutor (do not name any AI product): '
        'their course, their exact gaps, ask to explain step by step with examples, check understanding '
        'with a question, and not give full exam solutions}',
        f"Course context:\n{context}\n\nThis student's questions:\n{listing}",
    )
