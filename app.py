# app.py — PanQuiz Web con:
# ✅ Upload CSV/XLSX
# ✅ Inserimento manuale domande
# ✅ Salvataggio “in memoria” su Supabase (persistente)
# ✅ Link condivisibile: https://TUAPP.streamlit.app/?set=ID
# ✅ Modalità: Tutte / Esame / Solo sbagliate
# ✅ PanQuiz-style: pagina unica scroll, selezione azzurra, dopo Correggi card verde/rossa

import random
import time
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="PanQuiz Web", page_icon="🧠", layout="wide")

REQUIRED_COLS = ["domanda", "corretta", "errata1", "errata2"]

# ---------- CSS ----------
st.markdown("""
<style>
html, body, [class*="css"]  { background: #ffffff !important; color: #111111 !important; }
h1, h2, h3, h4, p, label, span, div { color: #111111 !important; }

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

/* Radio “bello”: evidenzia azzurro la scelta */
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
/* supportato su Chrome/Edge moderni */
div[role="radiogroup"] label:has(input:checked) {
  background: #dbeafe !important;
  border: 1px solid #60a5fa !important;
}
</style>
""", unsafe_allow_html=True)

# ---------- Supabase ----------
# Metti in Streamlit Cloud → Settings → Secrets:
# SUPABASE_URL="https://xxxx.supabase.co"
# SUPABASE_ANON_KEY="xxxxx"
def get_supabase():
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
    except Exception:
        return None

supabase = get_supabase()

# Tabella consigliata (Supabase SQL Editor):
# create table if not exists quiz_sets (
#   id text primary key,
#   created_at timestamp with time zone default now(),
#   title text,
#   payload jsonb not null
# );

def make_set_id() -> str:
    # ID corto: timestamp + random
    return f"{int(time.time())}{random.randint(1000,9999)}"

def save_quiz_set(title: str, df: pd.DataFrame) -> str:
    if supabase is None:
        raise ValueError("Supabase non configurato: aggiungi SUPABASE_URL e SUPABASE_ANON_KEY nei Secrets.")
    payload = df.to_dict(orient="records")
    set_id = make_set_id()
    supabase.table("quiz_sets").insert({
        "id": set_id,
        "title": title.strip() if title else "PanQuiz",
        "payload": payload
    }).execute()
    return set_id

def load_quiz_set(set_id: str) -> pd.DataFrame:
    if supabase is None:
        raise ValueError("Supabase non configurato: aggiungi SUPABASE_URL e SUPABASE_ANON_KEY nei Secrets.")
    res = supabase.table("quiz_sets").select("payload,title").eq("id", set_id).limit(1).execute()
    if not res.data:
        raise ValueError("Set non trovato (ID inesistente).")
    payload = res.data[0]["payload"]
    return pd.DataFrame(payload)

# ---------- Helpers ----------
def empty_df():
    return pd.DataFrame(columns=REQUIRED_COLS)

def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return empty_df()

    # garantisci colonne
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = ""
    df = df[REQUIRED_COLS].copy()

    # pulizia
    df = df.dropna(subset=REQUIRED_COLS).copy()
    for c in REQUIRED_COLS:
        df[c] = df[c].astype(str).str.strip()
    df = df[(df["domanda"] != "") & (df["corretta"] != "")]
    return df.reset_index(drop=True)

def load_file(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if name.endswith(".xlsx"):
        return pd.read_excel(uploaded_file)
    raise ValueError("Formato non supportato. Usa CSV o XLSX.")

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
    df = st.session_state.quiz_df
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
    df = st.session_state.quiz_df
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
    st.session_state.result = {
        "correct": correct, "total": total, "pct": pct,
        "wrong_ids": wrong_ids, "unanswered": unanswered, "details": details
    }
    st.session_state.wrong_bank = set(wrong_ids)

# ---------- Session init ----------
if "manual_df" not in st.session_state:
    st.session_state.manual_df = empty_df()
if "file_df" not in st.session_state:
    st.session_state.file_df = empty_df()

if "source" not in st.session_state:
    st.session_state.source = "Solo file"

if "wrong_bank" not in st.session_state:
    st.session_state.wrong_bank = set()

if "mode" not in st.session_state:
    st.session_state.mode = "Tutte"

if "exam_n" not in st.session_state:
    st.session_state.exam_n = 10

# ---------- Caricamento automatico da LINK (?set=ID) ----------
# Nota: aprendo https://TUAPP.streamlit.app/?set=1234 carica automaticamente quel set.
try:
    qp = st.query_params
    shared_set = qp.get("set")
except Exception:
    shared_set = None

if shared_set and not st.session_state.get("_loaded_shared_once"):
    try:
        shared_df = normalize_df(load_quiz_set(str(shared_set)))
        if len(shared_df) > 0:
            st.session_state.file_df = shared_df
            st.session_state.source = "Solo file"
            st.session_state.wrong_bank = set()
            st.session_state.mode = "Tutte"
            st.session_state.exam_n = min(10, len(shared_df))
            st.session_state._loaded_shared_once = True
            st.success("✅ Domande caricate dal link condiviso!")
    except Exception as e:
        st.session_state._loaded_shared_once = True
        st.error(f"Errore caricamento set dal link: {e}")

# ---------- UI ----------
st.title("🧠 PanQuiz Web")

# Sezione “memoria / link”
with st.expander("💾 Memoria & Link condivisibile (per amici)", expanded=True):
    st.write("Salva le domande su Supabase e genera un link tipo: **https://TUAPP.streamlit.app/?set=ID**")
    cS1, cS2, cS3 = st.columns([1.4, 1.0, 1.6])

    with cS1:
        save_title = st.text_input("Nome set (opzionale)", value="PanQuiz")
    with cS2:
        if st.button("💾 Salva set"):
            # salva la sorgente attuale (in basso scegli “Solo file / Solo manuale / File+manuale”)
            # per ora salva quello che risulta in st.session_state.quiz_df (costruito più sotto)
            # quindi se vuoi salvare subito, prima scegli la sorgente e poi clicca.
            if "quiz_df" not in st.session_state or len(st.session_state.quiz_df) == 0:
                st.error("Non ci sono domande da salvare.")
            else:
                try:
                    set_id = save_quiz_set(save_title, st.session_state.quiz_df)
                    st.session_state.last_set_id = set_id
                    st.success("Salvato!")
                except Exception as e:
                    st.error(str(e))
    with cS3:
        last_id = st.session_state.get("last_set_id")
        if last_id:
            st.write("👉 Link da inviare agli amici (aggiungi alla fine dell’URL della tua app):")
            st.code(f"?set={last_id}", language="text")
            st.caption("Esempio: https://TUAPP.streamlit.app/?set=" + str(last_id))

    st.divider()
    cL1, cL2 = st.columns([1.4, 1.0])
    with cL1:
        manual_set_id = st.text_input("Oppure carica un set per ID", value="")
    with cL2:
        if st.button("📥 Carica questo ID"):
            if not manual_set_id.strip():
                st.error("Inserisci un ID.")
            else:
                try:
                    shared_df = normalize_df(load_quiz_set(manual_set_id.strip()))
                    st.session_state.file_df = shared_df
                    st.session_state.source = "Solo file"
                    st.session_state.wrong_bank = set()
                    st.session_state.mode = "Tutte"
                    st.session_state.exam_n = min(10, len(shared_df))
                    st.success("Set caricato!")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

tab1, tab2 = st.tabs(["📄 Carica file", "✍️ Inserimento manuale"])

with tab1:
    uploaded = st.file_uploader(
        "Carica CSV o Excel (colonne: domanda, corretta, errata1, errata2)",
        type=["csv", "xlsx"]
    )
    if uploaded:
        try:
            df_loaded = normalize_df(load_file(uploaded))
            if len(df_loaded) == 0:
                st.error("Il file non contiene righe valide.")
            else:
                st.session_state.file_df = df_loaded
                st.success(f"File caricato: {len(df_loaded)} domande.")
        except Exception as e:
            st.error(str(e))

    if len(st.session_state.file_df) > 0:
        with st.expander("Vedi anteprima domande del file"):
            st.dataframe(st.session_state.file_df, use_container_width=True)

with tab2:
    st.subheader("Aggiungi una domanda (3 risposte: 1 corretta + 2 errate)")
    with st.form("add_q_form", clear_on_submit=True):
        domanda = st.text_input("Domanda")
        corretta = st.text_input("Risposta corretta")
        errata1 = st.text_input("Risposta errata 1")
        errata2 = st.text_input("Risposta errata 2")
        add = st.form_submit_button("➕ Aggiungi")

    if add:
        if not (domanda.strip() and corretta.strip() and errata1.strip() and errata2.strip()):
            st.error("Compila tutti i campi.")
        else:
            new_row = pd.DataFrame([{
                "domanda": domanda.strip(),
                "corretta": corretta.strip(),
                "errata1": errata1.strip(),
                "errata2": errata2.strip()
            }])
            st.session_state.manual_df = pd.concat([st.session_state.manual_df, new_row], ignore_index=True)
            st.success("Domanda aggiunta!")

    cA, cB, cC = st.columns(3)
    with cA:
        if st.button("🗑️ Elimina ultima"):
            if len(st.session_state.manual_df) > 0:
                st.session_state.manual_df = st.session_state.manual_df.iloc[:-1].reset_index(drop=True)
                st.rerun()
    with cB:
        if st.button("🧹 Svuota tutte"):
            st.session_state.manual_df = empty_df()
            st.rerun()
    with cC:
        if len(st.session_state.manual_df) > 0:
            csv_bytes = st.session_state.manual_df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Scarica CSV manuale", data=csv_bytes, file_name="domande_manual.csv", mime="text/csv")

    st.caption(f"Domande inserite manualmente: **{len(st.session_state.manual_df)}**")
    if len(st.session_state.manual_df) > 0:
        st.dataframe(st.session_state.manual_df, use_container_width=True)

st.divider()

# ---------- Sorgente domande ----------
st.subheader("📚 Sorgente domande per il quiz")

source = st.radio(
    "Usa domande da:",
    ["Solo file", "Solo manuale", "File + manuale"],
    index=["Solo file", "Solo manuale", "File + manuale"].index(st.session_state.source),
    horizontal=True
)
st.session_state.source = source

file_df = normalize_df(st.session_state.file_df)
manual_df = normalize_df(st.session_state.manual_df)

if source == "Solo file":
    quiz_df = file_df
elif source == "Solo manuale":
    quiz_df = manual_df
else:
    quiz_df = pd.concat([file_df, manual_df], ignore_index=True)

quiz_df = normalize_df(quiz_df)
st.session_state.quiz_df = quiz_df

st.caption(f"Domande disponibili per il quiz: **{len(quiz_df)}**")

if len(quiz_df) == 0:
    st.warning("Non ci sono domande. Carica un file oppure inserisci manualmente.")
    st.stop()

# ---------- Controlli quiz ----------
c1, c2, c3, c4, c5 = st.columns([1.2, 1.1, 1.1, 1.1, 1.4])

with c1:
    mode = st.selectbox("Modalità", ["Tutte", "Esame", "Solo sbagliate"],
                        index=["Tutte","Esame","Solo sbagliate"].index(st.session_state.mode))
with c2:
    exam_n = st.number_input("N esame", min_value=1, max_value=len(quiz_df),
                             value=min(int(st.session_state.exam_n), len(quiz_df)),
                             step=1, disabled=(mode!="Esame"))
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

# Solo sbagliate senza errori
if mode == "Solo sbagliate" and len(st.session_state.wrong_bank) == 0:
    st.success("🎉 Non hai domande sbagliate da ripassare (prima fai un quiz e premi Correggi).")
    st.stop()

# Init quiz prima volta
if "quiz_ids" not in st.session_state or len(st.session_state.get("quiz_ids", [])) == 0:
    start_quiz(st.session_state.mode, st.session_state.exam_n)

quiz_ids = st.session_state.get("quiz_ids", [])
if len(quiz_ids) == 0:
    st.info("Nessuna domanda disponibile per questa modalità.")
    st.stop()

st.caption(f"Domande nel quiz: **{len(quiz_ids)}** — Modalità: **{st.session_state.mode}**")

# ---------- Render domande ----------
df = st.session_state.quiz_df

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

# ---------- Riepilogo ----------
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