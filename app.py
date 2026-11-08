"""LostSignal - run with:  streamlit run app.py"""
import json
import time
import uuid
from pathlib import Path

import streamlit as st

import importlib
import agent
importlib.reload(agent)  # pick up agent.py edits without restarting

DATA = Path(__file__).parent / "data"
QFILE = DATA / "questions.json"
COURSE = DATA / "course.md"
NOTES = DATA / "notes.md"
LOG = DATA / "log.jsonl"

st.set_page_config(page_title="LostSignal", page_icon="📡", layout="centered")


# ---------- storage ----------
def load_q():
    return json.loads(QFILE.read_text()) if QFILE.exists() else []


def save_q(qs):
    QFILE.write_text(json.dumps(qs, ensure_ascii=False, indent=2))


def log(step, data):
    with LOG.open("a") as f:
        f.write(json.dumps({"t": time.time(), "step": step, "data": data}, ensure_ascii=False) + "\n")


def context():
    parts = [COURSE.read_text()] if COURSE.exists() else []
    if NOTES.exists() and NOTES.read_text().strip():
        parts.append("Professor's notes:\n" + NOTES.read_text())
    return "\n\n".join(parts) or "No course material available."


STUDENTS = DATA / "students"
MATERIALS = DATA / "materials"


def my_id():
    f = my_file()
    if f:
        return f.stem
    # no private code: anonymous id for this browser session, so replies still reach you
    if "anon_id" not in st.session_state:
        st.session_state.anon_id = "s_" + uuid.uuid4().hex[:12]
    return st.session_state.anon_id


def my_file():
    code = st.session_state.get("my_code", "").strip().lower()
    if not code:
        return None
    import hashlib
    STUDENTS.mkdir(exist_ok=True)
    return STUDENTS / (hashlib.sha256(code.encode()).hexdigest()[:16] + ".json")


def remember(question, topic, raw, qid=None):
    f = my_file()
    if not f:
        return
    hist = json.loads(f.read_text()) if f.exists() else []
    hist.append({"question": question, "topic": topic, "raw": raw, "qid": qid, "t": time.time()})
    f.write_text(json.dumps(hist, ensure_ascii=False, indent=2))


def add_question(text, topic):
    qs = load_q()
    qid = f"q{len(qs) + 1}"
    qs.append({"id": qid, "text": text, "topic": topic, "count": 1, "answered": False,
               "created": time.time(), "askers": [my_id()] if my_id() else [], "thread": [],
               "understood": []})
    save_q(qs)
    return qid


def plus_one(qid):
    qs = load_q()
    for q in qs:
        if q["id"] == qid:
            q["count"] += 1
            if my_id() and my_id() not in q.setdefault("askers", []):
                q["askers"].append(my_id())
    save_q(qs)


@st.fragment(run_every="4s")
def answered_inbox():
    """'My questions' on the student page: Pending until the professor marks it answered."""
    me = my_id()
    qs = load_q()
    mine = [q for q in qs if me in q.get("askers", [])]
    if not mine:
        return
    st.subheader("My questions")
    for q in reversed(mine):
        with st.container(border=True):
            st.markdown(f"**{q['text']}**")
            for t in q.get("thread", []):
                st.caption(f"↳ your follow-up: {t['text']}")
            if not q.get("answered"):
                st.caption("⏳ Pending — waiting for the professor")
            elif me in q.get("understood", []):
                st.caption("✅ Answered · you understood")
            else:
                st.success("✅ The professor answered this. Did you understand?")
                c1, c2 = st.columns(2)
                if c1.button("Yes, got it", key="ok_" + q["id"], type="primary"):
                    q.setdefault("understood", []).append(me)
                    save_q(qs)
                    log("understood", {"qid": q["id"]})
                    st.rerun()
                with c2.expander("No, still unclear"):
                    fu = st.text_input("What is still unclear?", key="fu_" + q["id"])
                    if st.button("Send follow-up", key="fs_" + q["id"]) and fu.strip():
                        ok, _ = agent.moderate(fu)
                        if not ok:
                            st.error("Please keep it respectful.")
                        else:
                            q.setdefault("thread", []).append({"text": fu, "t": time.time()})
                            q["answered"] = False      # back to the professor, same thread
                            save_q(qs)
                            log("follow_up", {"qid": q["id"], "text": fu})
                            st.rerun()
    st.divider()


# ---------- student view ----------
def reset():
    for k in list(st.session_state.keys()):
        if k.startswith("s_"):
            del st.session_state[k]


def student():
    st.header("📡 Ask anonymously")
    st.caption("Nobody sees your name. Write it however it comes to you.")
    s = st.session_state
    answered_inbox()

    if s.get("s_done"):
        st.success(s["s_done"])
        if st.button("Ask another question"):
            reset()
            st.rerun()
        return

    if "s_stage" not in s:
        msg = st.text_area("What didn't you get?", placeholder="e.g. why is there a +C at the end??")
        mats = sorted(p.name for p in MATERIALS.glob("*.pdf")) if MATERIALS.exists() else []
        picked = None
        if mats:
            picked = st.selectbox("📚 Material from your professor (optional)", ["None"] + mats)
        photo = st.file_uploader("Or upload your own photo of the board/slide, or a PDF", type=["png", "jpg", "jpeg", "pdf"])
        if st.button("Send", type="primary") and msg.strip():
            with st.spinner("Checking..."):
                ok, reason = agent.moderate(msg)
                log("moderation", {"ok": ok, "reason": reason})
                if not ok:
                    st.error("This message can't be sent. Please keep it respectful.")
                    return
                s.s_msg = msg
                if photo:
                    s.s_img = (photo.getvalue(), photo.type)
                elif picked and picked != "None" and (MATERIALS / picked).exists():
                    s.s_img = ((MATERIALS / picked).read_bytes(), "application/pdf")
                else:
                    s.s_img = None
                s.s_hist = []
                res = agent.analyze(msg, context(), s.s_img)
                log("analyze", res)
            s.s_res = res
            s.s_stage = "analyzed"
            st.rerun()
        return

    res = s.s_res
    if not res.get("on_topic", True):
        st.warning("This doesn't seem to be about this course. "
                   + res.get("off_topic_reason", ""))
        if st.button("Start over"):
            reset()
            st.rerun()
        return

    # diagnosis step: help the student find what they didn't understand
    if res.get("needs_diagnosis") and s.s_stage == "analyzed":
        st.info(res.get("diagnostic_question", "Which part is unclear?"))
        choice = st.radio("Pick one", res.get("options", []) or ["Something else"])
        extra = st.text_input("Or describe it in your words (optional)")
        if st.button("Continue", type="primary"):
            answer = extra.strip() or choice
            s.s_hist.append(f"Q: {res.get('diagnostic_question')} / A: {answer}")
            with st.spinner("Understanding..."):
                s.s_res = agent.refine(s.s_msg, context(), answer, s.s_hist[:-1], s.s_img)
                log("refine", s.s_res)
            st.rerun()
        return

    # confirmation step
    clarified = res.get("clarified_question", "")
    if s.s_stage == "analyzed":
        st.subheader("Is this what you mean?")
        st.markdown(f"> **{clarified}**")
        if res.get("source"):
            st.caption(f"📎 Found in your material: {res['source']}")
        c1, c2 = st.columns(2)
        if c1.button("Yes, that's it", type="primary"):
            s.s_final = clarified
            s.s_topic = res.get("topic", "") + (f" · 📎 {res['source']}" if res.get("source") else "")
            s.s_stage = "check_similar"
            st.rerun()
        with c2.expander("No, it's something else"):
            corr = st.text_input("What do you mean instead?")
            if st.button("Try again") and corr.strip():
                with st.spinner("Rewriting..."):
                    s.s_res = agent.rewrite_with_correction(s.s_msg, context(), clarified, corr, s.s_img)
                    log("correction", s.s_res)
                st.rerun()
        return

    # similar-question step: always ask the student, never merge silently
    if s.s_stage == "check_similar":
        open_qs = [q for q in load_q() if not q["answered"]]
        if "s_match" not in s:
            with st.spinner("Checking if someone asked the same..."):
                s.s_match = agent.find_similar(s.s_final, open_qs)
                log("similar", {"q": s.s_final, "match": s.s_match})
        best_id, score = s.s_match
        match = next((q for q in open_qs if q["id"] == best_id), None)
        if match:
            st.subheader("A classmate asked something very similar")
            st.markdown(f"> **{match['text']}**  \n_{match['count']} student(s) asking_")
            c1, c2 = st.columns(2)
            if c1.button("Yes, same question", type="primary"):
                plus_one(match["id"])
                remember(match["text"], match["topic"], s.s_msg, match["id"])
                s.s_done = "Added your vote. The professor will see it."
                st.rerun()
            if c2.button("No, mine is different"):
                qid = add_question(s.s_final, s.s_topic)
                remember(s.s_final, s.s_topic, s.s_msg, qid)
                s.s_done = "Your question was sent anonymously."
                st.rerun()
        else:
            qid = add_question(s.s_final, s.s_topic)
            remember(s.s_final, s.s_topic, s.s_msg, qid)
            s.s_done = "Your question was sent anonymously."
            st.rerun()


# ---------- professor view ----------
@st.fragment(run_every="4s")
def prof_queue():
    qs = load_q()
    open_qs = sorted([q for q in qs if not q["answered"]], key=lambda q: -q["count"])
    total = sum(q["count"] for q in open_qs)
    st.metric("Open questions", len(open_qs), help=f"{total} students in total")
    st.caption("Updates automatically. Answer whenever you want: after a topic, at the break, or at the end.")
    if not open_qs:
        st.write("No open questions.")
    for q in open_qs:
        with st.container(border=True):
            st.markdown(f"**{q['text']}**")
            st.caption(f"{q['topic']} · {q['count']} student(s)")
            for t in q.get("thread", []):
                st.markdown(f"↳ *Follow-up (still unclear):* {t['text']}")
            if st.button("Mark answered", key=q["id"]):
                for x in qs:
                    if x["id"] == q["id"]:
                        x["answered"] = True
                        x["last_reply_by"] = None
                save_q(qs)
                st.rerun()


def professor():
    st.header("🎓 Professor")
    qs = load_q()
    tab1, tab2, tab3 = st.tabs(["Questions", "Weekly report", "Course material"])
    with tab1:
        prof_queue()
    with tab2:
        if st.button("Generate report", type="primary") and qs:
            with st.spinner("Analysing all questions..."):
                st.session_state.report = agent.weekly_report(qs, context())
                log("report", st.session_state.report)
        rep = st.session_state.get("report")
        if rep:
            for t in rep.get("top_topics", []):
                st.markdown(f"**{t['topic']}** — {t['students']} students  \n{t['what_is_unclear']}")
            st.info(rep.get("suggestion", ""))
    with tab3:
        st.caption("Optional. Without material, LostSignal works only from what students write.")
        pdfs = st.file_uploader("Upload slides or notes (PDF) — students can attach them to their question", type=["pdf"],
                                accept_multiple_files=True)
        MATERIALS.mkdir(exist_ok=True)
        for pdf in pdfs or []:
            if (MATERIALS / pdf.name).exists():
                continue
            (MATERIALS / pdf.name).write_bytes(pdf.getvalue())
            log("material_saved", {"file": pdf.name})
            st.success(f"Added {pdf.name}. Students can now pick it.")
        mats = sorted(MATERIALS.glob("*.pdf"))
        st.markdown("**📚 Uploaded material (visible to students):**")
        if not mats:
            st.write("Nothing yet.")
        for m in mats:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"- {m.name}")
            if c2.button("🗑️", key="del_" + m.name, help="Delete for everyone"):
                m.unlink(missing_ok=True)
                log("material_deleted", {"file": m.name})
                st.rerun()
        if mats and st.button("🗑️ Delete all uploaded documents"):
            for m in mats:
                m.unlink(missing_ok=True)
            log("materials_cleared", {})
            st.rerun()


def my_profile():
    st.header("🧭 My learning profile")
    st.caption("Private. Only you can see this, with your secret code. The professor never sees it.")
    f = my_file()
    if not f:
        st.info("Enter a private code in the sidebar to keep your own history.")
        return
    hist = json.loads(f.read_text()) if f.exists() else []
    if not hist:
        st.write("No questions yet. Ask something in the Student view first.")
        return
    st.subheader(f"Your questions ({len(hist)})")
    st.caption("Tick the questions you want to analyse.")
    chosen = []
    for i, h in reversed(list(enumerate(hist))):
        if st.checkbox(f"{h['question']}  ·  {h.get('topic','')}", value=True, key=f"pick_{i}"):
            chosen.append(h)
    if st.button("What am I missing?", type="primary", disabled=not chosen):
        with st.spinner("Looking at your questions..."):
            st.session_state.brief = agent.learning_brief(chosen, context())
            log("brief", {"n": len(chosen)})
    b = st.session_state.get("brief")
    if b:
        st.subheader("Your weak spots")
        for w in b.get("weak_spots", []):
            st.markdown(f"**{w['topic']}** · asked {w['times_asked']}×  \n{w['what_is_missing']}")
        if b.get("root_gap"):
            st.warning(f"Possible root gap: {b['root_gap']}")
        if b.get("pattern"):
            st.info(f"Your pattern: {b['pattern']}")
        if b.get("study_order"):
            st.markdown("**Review in this order:** " + " → ".join(b["study_order"]))
        st.subheader("Tell your AI tutor what you're missing")
        st.caption("Copy this into your AI tutor.")
        st.code(b.get("prompt_for_ai_tutor", ""), language=None)


st.sidebar.text_input("Your private code (optional)", key="my_code", type="password",
                      help="Lets LostSignal remember YOUR questions for your private profile. Never shown to anyone.")
view = st.sidebar.radio("View", ["Student", "My profile", "Professor"])
st.sidebar.caption("LostSignal · no recording · anonymous · nothing is graded")

try:
    if view == "Student":
        student()
    elif view == "My profile":
        my_profile()
    else:
        professor()
except Exception as e:
    name = type(e).__name__
    if "RateLimit" in name or "429" in str(e):
        st.error("The AI service is out of credits or busy. Check the OpenAI billing page, then try again.")
    else:
        st.error(f"Something went wrong ({name}). Please try again.")
    log("error", {"type": name, "msg": str(e)[:300]})
