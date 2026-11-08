# LostSignal
**Student Tech Clash 2026 · AI on Campus · Team Polito Zero Signal**

> "Students don't stay silent because they understood. They stay silent because they're embarrassed, can't put it into words, or don't even know *what* they didn't understand."

LostSignal lets a student write their confusion anonymously, in their own messy words, during a lecture. An AI agent finds out what they really didn't understand, turns it into one clear question, asks the student to confirm it, and sends it anonymously to the professor, who answers whenever they choose.

## How to run
```bash
pip3 install -r requirements.txt          # openai, streamlit, python-dotenv
cp .env.example .env                     # then put your OpenAI key in .env (never commit it)
python3 -m streamlit run app.py           # or double-click start.command (macOS)
```
Open http://localhost:8501. Use the sidebar to switch between **Student** and **Professor**.

- Model: `gpt-4o-mini` (set `OPENAI_MODEL` in `.env` to change) · OpenAI `omni-moderation-latest` for safety
- Libraries: `openai`, `streamlit`, `python-dotenv` · no training, only pre-trained models
- Files: `app.py` (interface + orchestrator), `agent.py` (LLM tools), `data/course.md` (syllabus), `data/materials/` (PDFs uploaded by the professor), `data/questions.json` (shared memory: questions, +1s, threads), `data/students/` (private per-student history, file name = hash of the student's code), `data/log.jsonl` (every step traced)
- Three views in the sidebar: **Student** (ask + My questions), **My profile** (private), **Professor** (queue, report, material)

## Architecture
```
 STUDENT UI                     ORCHESTRATOR (app.py)                      PROFESSOR UI
 ask anonymously ─────────────► loop: analyse → decide → act → observe ──► question queue
 My questions (status) ◄──────                                      ◄──── Mark answered
 My profile (private)                                                    weekly report
                                                                         course material (PDFs)
 GUARDRAILS (in code, not only in the prompt)
   moderate()        OpenAI moderation + LLM check: block only real violations
   on_topic          only questions about THIS course get through
   never answers for the professor · never invents material · never merges without consent
   professor never sees names or personal profiles

 LLM DECISIONS (agent.py, JSON outputs)
   analyze()   clear?            → propose ONE clarified question + source page ("Page 19")
               vague?            → ask ONE diagnostic question (2-4 options)
               several matches?  → ask which one, don't guess
   refine() / rewrite_with_correction()   loop until the student confirms
   find_similar()                same doubt already asked? (strict, >= 0.90) → student decides
   learning_brief()              the student's OWN selected questions → weak spots, root gap,
                                 pattern, review order, ready prompt for any AI tutor
   weekly_report()               all questions → what the class didn't understand

 TOOLS / ACTIONS
   add_question · plus_one · follow-up on the same thread · mark answered
   "Did you understand?" (yes → closed / no → back to the professor, same thread)
   save / delete course PDFs (no AI cost on upload; read only when a student attaches one)

 KNOWLEDGE   syllabus + professor's PDFs (picked by the student) + student's own photo/PDF
             no material → works only from the student's words, no invention

 MEMORY      questions.json (shared, anonymous) · students/<hash>.json (private) · log.jsonl
```
**Input:** anonymous free text (+ optional professor PDF or own photo/PDF). **Knowledge:** syllabus, attached material. **Decisions (LLM):** on-topic? clear, vague or ambiguous? which options? same as an existing question? what is this student missing over time? **Actions:** diagnose, clarify, cite the page, queue, +1, follow-up thread, close the loop with "Did you understand?", personal brief, class report. **Output:** clear anonymous questions for the professor; a private learning profile for each student.

**Question lifecycle:** written → diagnosed → clarified → confirmed by the student → (+1 or new) → ⏳ Pending → professor marks answered → "Did you understand?" → ✅ closed, or ↳ follow-up back to the professor on the same thread.

**Design choice.** The orchestrator is controlled on purpose: the LLM decides at every step (ask again, clarify, reject, propose merge), while safety, anonymity and consent rules live in code. In education, predictability matters more than freedom.

## Example interactions
**1 · Vague confusion → diagnosis → clear question (with Lecture 12 PDF)**
- Student: *"i didnt get this theorem, the derivatives one"*
- Agent: *"Which theorem do you mean? Fermat · Rolle · Lagrange (Mean Value) · Cauchy · Something else"*
- Student: *Rolle*
- Agent: *"Is this what you mean? 'Why does Rolle's theorem require f(a) = f(b), and why does that guarantee a point where f'(x) = 0?'"* · 📎 *Page 19: Theorem (Rolle)*
- Student: *Yes* → sent anonymously.

**2 · Similar question → student decides**
- Agent: *"A classmate asked something very similar: 'Why do we add +C to an indefinite integral but not to a definite one?' (7 students)"*
- Student: *"Yes, same"* → +1 (now 8). If *"No, mine is different"* → kept as a separate question.

**3 · Boundary: off-topic**
- Student (Analysis 1): *"what's the best pizza near campus?"*
- Agent: *"This doesn't seem to be about this course."* Nothing is sent.

**4 · Boundary: respectful-but-informal is allowed, abuse is blocked**
- *"I don't get this stupid formula at all"* → allowed (frustration, not abuse), clarified normally.
- A message insulting the professor → *"This message can't be sent. Please keep it respectful."*

**5 · Boundary: it doesn't answer for the professor**
- Student: *"just tell me the answer"*
- Agent does not answer; it clarifies the question and sends it to the professor. LostSignal helps students *find* their question; it never thinks for them.

**6 · Closing the loop: "Did you understand?"**
- Student's card in *My questions*: ⏳ *Pending — waiting for the professor*
- Professor answers in class, clicks **Mark answered** → student sees: *"The professor answered this. Did you understand?"*
- *"No, still unclear: why can't f(a) be different from f(b)?"* → goes back to the professor under the **same** question as a follow-up. Not a new question, and it doesn't block the lecture.

**7 · Private learning profile ("What am I missing?")**
- The student ticks 5 of their past questions (definition of derivative, chain rule, Rolle p.19, Lagrange p.21, critical points p.16).
- Agent: weak spots with how often each was asked · *root gap:* "Rolle's theorem — Lagrange is proved from it" · *pattern:* "you get the idea but lose track in proof steps" · *review order:* Fermat → Rolle → Lagrange · a ready prompt for any AI tutor describing exactly these gaps.
- Only the student sees this. The professor sees anonymous class-level data only.

## Privacy & ethics
No recording of the lecture (no copyright or consent issues) · fully anonymous to the professor · a student's history is stored under a hash of their own secret code and shown only to them · nothing affects grades · only course questions reach the professor · the AI never invents lecture content · uploaded PDFs can be deleted by the professor at any time.

## Who benefits / who might be left out
Shy students, international students, anyone who loses the thread. Left out: students without a device. Mitigation: works on any phone or laptop browser, and the professor can still take questions out loud.

## Success measures
Questions per lecture (vs. hands raised before) · % of clarified questions confirmed by students ("yes, that's it") · % of questions answered by the professor · % of answered questions marked "I understood" (vs. follow-ups) · topics flagged in the weekly report that improve in later weeks.

## Level 3 status (honest)
- **Knowledge graph (Path B):** partial. The private profile infers prerequisite links (root gap, review order) with the LLM, but there is no explicit graph store yet. Next step: extract concept → prerequisite triples from the professor's PDFs.
- **Multi-agent (Path A):** not implemented; we chose one controlled orchestrator for predictability in class.
- **Launch campaign (Path C):** see the team's campaign slide.
