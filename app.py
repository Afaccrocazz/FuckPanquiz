import random
import pandas as pd
import streamlit as st

st.set_page_config(page_title="PanQuiz Web", page_icon="🧠", layout="wide")

REQUIRED_COLS = ["domanda", "corretta", "errata1", "errata2"]

# --- CSS (bianco/nero + selezione azzurra + card verde/rossa dopo correzione) ---
st.markdown("""
<style>
/* base */
html, body, [class*="css"]  { background: #ffffff !important; color: #111111 !important; }
h1, h2, h3, h4, p, label, span, div { color: #111111 !important; }

/* card */
.pq-card {
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 14px 14px 10px 14px;
  margin: 10px 0 14px 0;
  background: #ffffff;
}
.pq-correct { background: #dcfce7 !important; border: 2px solid #16a34a !important; }
.pq-wrong   { background: #fee2e2 !important; border: 2px solid #dc2626 !important; }
.pq-unans   { background: #fef3c7 !important; border: 2px solid #f59e0b !important; }

.pq-title { font-weight: 800; font-size: 16px; margin-bottom: 8px; }

/* radio: prova a renderlo più “azzurro” quando selezionato */
div[role="radiogroup"] label {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 10px 12px;
  margin: 6px 0;
  background: #ffffff;
}
div[role="radiogroup"] label:hover {
  border: 1px solid #93c5fd;
  background: #f8fbff;
}
div[role="radiogroup"] label:has(input:checked) {
  background: #dbeafe !important;
  border: 1px solid #60a5fa !important;
}
</style>
""", unsafe_allow_html=True)

def load_file(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if name.endswith(".xlsx"):
        return pd.read_excel(uploaded_file)
    raise ValueError("Formato non supportato. Usa CSV o XLSX.")

def validate_df(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Mancano colonne: {', '.join(missing)}")
    df = df.dropna(subset=REQUIRED_COLS).copy()
    for c in REQUIRED_COLS:
        df[c] = df[c].astype(str).str.strip()
    df = df[(df["domanda"] != "") & (df["corretta"] != "")]
    return df.reset_index(drop=True)

def build_quiz(df: pd.DataFrame, ids):
    ids = list(ids)
    random.shuffle(ids)
    options_map = {}
    for qid in ids:
        row = df.iloc[qid]
        opts = [row["corretta"], row["errata1"], row["errata2"]]
        random.shuffle(opts)
        options_map[qid] = opts
    return ids, options_map

def start_quiz(mode, exam_n):
    df = st.session_state.df
    all_ids = list(range(len(df)))

    if mode == "Tutte":
        ids = all_ids
    elif mode == "Esame":
        n = max(1, min(int(exam_n), len(df)))
        ids = all_ids[:]
        random.shuffle(ids)
        ids = ids[:n]
    else:  # Solo sbagliate
        ids = list(st.session_state.wrong_bank)

    if len(ids) == 0:
        st.session_state.quiz_ids = []
        st.session_state.options_map = {}
        st.session_state.answers = {}
        st.session_state.graded = False
        st.session_state.result = None
        return

    quiz_ids, options_map = build_quiz(df, ids)
    st.session_state.quiz_ids = quiz_ids
    st.session_state.options_map = options_map
    st.session_state.answers = {}
    st.session_state.graded = False
    st.session_state.result = None

def grade_quiz():
    df = st.session_state.df
    quiz_ids = st.session_state.quiz_ids
    answers = st.session_state.answers

    correct = 0
    wrong_ids = []
    unanswered = []

    details = []
    for i, qid in enumerate(quiz_ids, start=1):
        row = df.iloc[qid]
        right = row["corretta"]
        picked = answers.get(qid)

        if picked is None:
            unanswered.append(qid)
            status = "unanswered"
        elif picked == right:
            correct += 1
            status = "correct"
        else:
            wrong_ids.append(qid)
            status = "wrong"

        details.append({
            "i": i, "qid": qid, "domanda": row["domanda"],
            "picked": picked, "right": right, "status": status
        })

    total = len(quiz_ids)
    pct = (correct / total * 100) if total else 0

    st.session_state.graded = True
    st.session_state.result = {"correct": correct, "total": total, "pct": pct,
                               "wrong_ids": wrong_ids, "unanswered": unanswered, "details": details}
    st.session_state.wrong_bank = set(wrong_ids)

# --- UI ---
st.title("🧠 PanQuiz Web (Streamlit)")

uploaded = st.file_uploader("Carica CSV o Excel (colonne: domanda, corretta, errata1, errata2)", type=["csv", "xlsx"])

if not uploaded:
    st.info("Carica un file per iniziare.")
    st.stop()

try:
    df = validate_df(load_file(uploaded))
except Exception as e:
    st.error(str(e))
    st.stop()

# init/reset quando cambia file
if "file_name" not in st.session_state or st.session_state.file_name != uploaded.name:
    st.session_state.file_name = uploaded.name
    st.session_state.df = df
    st.session_state.wrong_bank = set()
    st.session_state.mode = "Tutte"
    st.session_state.exam_n = min(10, len(df))
    start_quiz("Tutte", st.session_state.exam_n)
else:
    st.session_state.df = df

# controlli
c1, c2, c3, c4, c5 = st.columns([1.2, 1.1, 1.1, 1.1, 1.4])

with c1:
    mode = st.selectbox("Modalità", ["Tutte", "Esame", "Solo sbagliate"],
                        index=["Tutte","Esame","Solo sbagliate"].index(st.session_state.mode))
with c2:
    exam_n = st.number_input("N esame", min_value=1, max_value=len(df),
                             value=int(st.session_state.exam_n), step=1, disabled=(mode!="Esame"))
with c3:
    if st.button("▶️ Avvia/Reset"):
        st.session_state.mode = mode
        st.session_state.exam_n = int(exam_n)
        start_quiz(mode, exam_n)
        st.rerun()
with c4:
    if st.button("🎲 Rimescola"):
        st.session_state.mode = mode
        st.session_state.exam_n = int(exam_n)
        start_quiz(mode, exam_n)
        st.rerun()
with c5:
    if st.button("✅ Correggi"):
        grade_quiz()
        st.rerun()

# info
if mode == "Solo sbagliate" and len(st.session_state.wrong_bank) == 0:
    st.success("🎉 Non hai domande sbagliate da ripassare (prima fai un quiz e premi Correggi).")
    st.stop()

quiz_ids = st.session_state.get("quiz_ids", [])
if len(quiz_ids) == 0:
    st.info("Nessuna domanda disponibile per questa modalità.")
    st.stop()

st.caption(f"Domande: **{len(quiz_ids)}** — Modalità: **{mode}**")

# --- render domande (scroll pagina) ---
df = st.session_state.df
for k, qid in enumerate(quiz_ids, start=1):
    row = df.iloc[qid]
    domanda = row["domanda"]
    opts = st.session_state.options_map[qid]

    card_class = "pq-card"
    if st.session_state.get("graded") and st.session_state.get("result"):
        det = st.session_state.result["details"][k-1]
        if det["status"] == "correct":
            card_class += " pq-correct"
        elif det["status"] == "wrong":
            card_class += " pq-wrong"
        else:
            card_class += " pq-unans"

    st.markdown(f'<div class="{card_class}"><div class="pq-title">{k}. {domanda}</div>', unsafe_allow_html=True)

    # risposta selezionata
    current = st.session_state.answers.get(qid)

    choice = st.radio(
        label="",
        options=opts,
        index=opts.index(current) if current in opts else None,
        key=f"q_{qid}",
        label_visibility="collapsed"
    )
    st.session_state.answers[qid] = choice

    if st.session_state.get("graded") and st.session_state.get("result"):
        right = row["corretta"]
        picked = st.session_state.answers.get(qid)
        if picked == right:
            st.success("Corretta")
        else:
            st.error(f"Corretta: {right}")

    st.markdown("</div>", unsafe_allow_html=True)

# riepilogo
if st.session_state.get("graded") and st.session_state.get("result"):
    r = st.session_state.result
    st.subheader("📊 Risultato")
    st.write(f"Corrette: **{r['correct']} / {r['total']}** — **{r['pct']:.1f}%**")
    if len(r["unanswered"]) > 0:
        st.warning(f"Non risposte: **{len(r['unanswered'])}**")
    if len(r["wrong_ids"]) > 0:
        st.info("Per ripassare: seleziona **Solo sbagliate** e premi **Avvia/Reset**.")
    else:
        st.success("🎯 Perfetto! Nessun errore.")