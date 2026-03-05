import os
import json
import time
import random
import hashlib
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
import streamlit as st
import html as html_lib
import streamlit.components.v1 as components

APP_TITLE = "Quiz XLSX (stile Concorsando) - Locale"
DATA_DIR = "data"
STATE_FILE = os.path.join(DATA_DIR, "quiz_state.json")


# ----------------------------
# Utility: storage (JSON)
# ----------------------------
def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_state() -> Dict[str, Any]:
    ensure_data_dir()
    if not os.path.exists(STATE_FILE):
        return {
            "questions": {},
            "stats": {},
            "last_session": {"wrong_qids": [], "correct_qids": [], "ts": None},
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: Dict[str, Any]) -> None:
    ensure_data_dir()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def stable_base_hash(capitolo: str, domanda: str, corretta: str, err1: str, err2: str) -> str:
    raw = "||".join([capitolo.strip(), domanda.strip(), corretta.strip(), err1.strip(), err2.strip()])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def unique_qid_for_state(base_hash: str, questions: Dict[str, Any]) -> str:
    """
    Permette duplicati: se base_hash esiste già, crea base_hash__2, base_hash__3, ...
    """
    if base_hash not in questions:
        return base_hash
    k = 2
    while True:
        qid = f"{base_hash}__{k}"
        if qid not in questions:
            return qid
        k += 1


# ----------------------------
# Reset statistiche
# ----------------------------
def reset_statistics(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resetta SOLO le statistiche, NON cancella le domande.
    """
    questions = state.get("questions", {})
    new_stats: Dict[str, Any] = {}

    for qid in questions.keys():
        new_stats[qid] = {
            "attempts": 0,
            "correct": 0,
            "wrong": 0,
            "streak_correct": 0,
            "last_ts": None,
            "in_wrong_queue": False,
        }

    state["stats"] = new_stats
    state["last_session"] = {"wrong_qids": [], "correct_qids": [], "ts": None}
    save_state(state)
    return state


# ----------------------------
# Quiz Model
# ----------------------------
@dataclass
class Question:
    qid: str
    capitolo: str
    domanda: str
    corretta: str
    errate: List[str]


# ----------------------------
# Import XLSX
# ----------------------------
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    def norm(name: str) -> str:
        s = str(name).strip().lower()
        while s.endswith("."):
            s = s[:-1].strip()
        return s

    df.columns = [norm(c) for c in df.columns]

    def find_col(candidates: List[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    col_cap = find_col(["cap", "capitolo", "chapter"])
    col_dom = find_col(["domanda", "question"])
    col_cor = find_col(["risposta corretta", "risposta_corretta", "corretta", "correct answer", "correct"])

    err_cols = [c for c in df.columns if c.startswith("risposta errata")]
    if len(err_cols) < 2:
        alt_err = [c for c in df.columns if "errata" in c]
        err_cols = (err_cols + [c for c in alt_err if c not in err_cols])[:2]

    if not (col_cap and col_dom and col_cor and len(err_cols) >= 2):
        raise ValueError(
            "Colonne non riconosciute. Servono: cap (o cap.), domanda, risposta corretta, risposta errata (x2). "
            f"Trovate: {list(df.columns)}"
        )

    df = df.rename(
        columns={
            col_cap: "capitolo",
            col_dom: "domanda",
            col_cor: "risposta_corretta",
            err_cols[0]: "risposta_errata_1",
            err_cols[1]: "risposta_errata_2",
        }
    )

    return df[["capitolo", "domanda", "risposta_corretta", "risposta_errata_1", "risposta_errata_2"]]


def validate_row(row: pd.Series, idx: int) -> Tuple[bool, str]:
    vals = [
        str(row["capitolo"]).strip(),
        str(row["domanda"]).strip(),
        str(row["risposta_corretta"]).strip(),
        str(row["risposta_errata_1"]).strip(),
        str(row["risposta_errata_2"]).strip(),
    ]
    if any(v == "" or v.lower() == "nan" for v in vals):
        return False, f"Riga {idx+1}: campo vuoto o non valido."
    return True, ""


def import_xlsx_to_state(uploaded_file, state: Dict[str, Any]) -> Dict[str, Any]:
    df = pd.read_excel(uploaded_file)
    df = normalize_columns(df)

    errors = []
    questions: Dict[str, Any] = state.get("questions", {})
    stats: Dict[str, Any] = state.get("stats", {})

    imported = 0
    skipped = 0

    for i, row in df.iterrows():
        ok, msg = validate_row(row, i)
        if not ok:
            errors.append(msg)
            skipped += 1
            continue

        capitolo = str(row["capitolo"]).strip()
        domanda = str(row["domanda"]).strip()
        corretta = str(row["risposta_corretta"]).strip()
        err1 = str(row["risposta_errata_1"]).strip()
        err2 = str(row["risposta_errata_2"]).strip()

        base = stable_base_hash(capitolo, domanda, corretta, err1, err2)
        qid = unique_qid_for_state(base, questions)  # ✅ duplicati consentiti

        questions[qid] = {
            "capitolo": capitolo,
            "domanda": domanda,
            "corretta": corretta,
            "errate": [err1, err2],
        }
        if qid not in stats:
            stats[qid] = {
                "attempts": 0,
                "correct": 0,
                "wrong": 0,
                "streak_correct": 0,
                "last_ts": None,
                "in_wrong_queue": False,
            }
        imported += 1

    state["questions"] = questions
    state["stats"] = stats
    save_state(state)

    if skipped == 0:
        st.success(f"Import completato ✅ ({imported} righe importate, duplicati inclusi)")
    else:
        st.warning(
            f"Import completato ✅ ({imported} righe importate, duplicati inclusi). "
            f"Attenzione: {skipped} righe con campi vuoti/NaN non sono utilizzabili."
        )
        for e in errors[:25]:
            st.write(f"- {e}")
        if len(errors) > 25:
            st.write(f"... e altre {len(errors)-25} righe.")

    return state


# ----------------------------
# Session builder
# ----------------------------
def get_all_questions(state: Dict[str, Any]) -> List[Question]:
    qs = []
    for qid, q in state.get("questions", {}).items():
        qs.append(
            Question(
                qid=qid,
                capitolo=q["capitolo"],
                domanda=q["domanda"],
                corretta=q["corretta"],
                errate=q["errate"],
            )
        )
    return qs


def filter_questions(questions: List[Question], selected_chapters: List[str]) -> List[Question]:
    if not selected_chapters:
        return questions
    return [q for q in questions if q.capitolo in selected_chapters]


def build_session_qids(
    state: Dict[str, Any],
    mode: str,
    selected_chapters: List[str],
    n_questions: int,
    order: str,
    wrong_scope: str,
) -> List[str]:
    all_qs = get_all_questions(state)
    all_qs = filter_questions(all_qs, selected_chapters)
    stats = state.get("stats", {})

    if mode == "Ripeti sbagliate":
        now = int(time.time())
        if wrong_scope == "Solo ultima sessione":
            qids = state.get("last_session", {}).get("wrong_qids", [])
        elif wrong_scope == "Ultimi 7 giorni":
            seven_days = 7 * 24 * 3600
            qids = []
            for qid, s in stats.items():
                if s.get("wrong", 0) > 0 and s.get("last_ts"):
                    if now - int(s["last_ts"]) <= seven_days:
                        qids.append(qid)
        else:
            qids = [qid for qid, s in stats.items() if s.get("wrong", 0) > 0 or s.get("in_wrong_queue", False)]

        if selected_chapters:
            allowed = {q.qid for q in all_qs}
            qids = [qid for qid in qids if qid in allowed]

        if not qids:
            return []

        if order == "Casuale":
            random.shuffle(qids)
        else:
            qids = sorted(qids, key=lambda x: (state["questions"][x]["capitolo"], state["questions"][x]["domanda"]))

        return qids[:n_questions] if n_questions > 0 else qids

    qids = [q.qid for q in all_qs]
    if not qids:
        return []
    if order == "Casuale":
        random.shuffle(qids)
    else:
        qids = sorted(qids, key=lambda x: (state["questions"][x]["capitolo"], state["questions"][x]["domanda"]))
    return qids[:n_questions] if n_questions > 0 else qids


# ----------------------------
# Stats write
# ----------------------------
def register_answer(state: Dict[str, Any], qid: str, is_correct: bool) -> None:
    stats = state["stats"][qid]
    stats["attempts"] += 1
    stats["last_ts"] = int(time.time())

    if is_correct:
        stats["correct"] += 1
        stats["streak_correct"] = stats.get("streak_correct", 0) + 1
        if stats["streak_correct"] >= 2:
            stats["in_wrong_queue"] = False
    else:
        stats["wrong"] += 1
        stats["streak_correct"] = 0
        stats["in_wrong_queue"] = True


def chapter_stats(state: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for qid, q in state.get("questions", {}).items():
        s = state["stats"].get(qid, {})
        rows.append(
            {
                "Capitolo": q["capitolo"],
                "Tentativi": s.get("attempts", 0),
                "Corrette": s.get("correct", 0),
                "Sbagliate": s.get("wrong", 0),
                "In ripeti sbagliate": bool(s.get("in_wrong_queue", False)),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["Capitolo", "Tentativi", "Corrette", "Sbagliate", "In ripeti sbagliate"])
    df = pd.DataFrame(rows)
    grp = df.groupby("Capitolo", as_index=False).sum(numeric_only=True)
    grp["Accuratezza %"] = grp.apply(
        lambda r: (r["Corrette"] / r["Tentativi"] * 100) if r["Tentativi"] else 0, axis=1
    ).round(1)
    return grp.sort_values(["Accuratezza %", "Sbagliate"], ascending=[True, False])


def overall_stats(state: Dict[str, Any]) -> Dict[str, Any]:
    total_attempts = sum(s.get("attempts", 0) for s in state.get("stats", {}).values())
    total_correct = sum(s.get("correct", 0) for s in state.get("stats", {}).values())
    total_wrong = sum(s.get("wrong", 0) for s in state.get("stats", {}).values())
    wrong_queue = sum(1 for s in state.get("stats", {}).values() if s.get("in_wrong_queue", False))
    acc = (total_correct / total_attempts * 100) if total_attempts else 0.0
    return {
        "domande": len(state.get("questions", {})),
        "tentativi": total_attempts,
        "corrette": total_correct,
        "sbagliate": total_wrong,
        "accuratezza": acc,
        "ripeti_sbagliate": wrong_queue,
    }


# ----------------------------
# Helpers: options/labels per qid
# ----------------------------
def build_labels_for_question(qid: str, q: Dict[str, Any]) -> Tuple[List[str], List[Tuple[int, str]]]:
    options_text = [q["corretta"]] + q["errate"]
    seed = int(hashlib.md5(qid.encode("utf-8")).hexdigest(), 16) % (10**8)
    rng = random.Random(seed)
    order_idx = list(range(len(options_text)))
    rng.shuffle(order_idx)
    shuffled = [(i, options_text[i]) for i in order_idx]  # idx_originale 0=corretta
    labels = [f"{chr(65+k)}) {txt}" for k, (_, txt) in enumerate(shuffled)]
    return labels, shuffled


def compute_is_correct_from_label(labels: List[str], shuffled: List[Tuple[int, str]], chosen_label: str) -> bool:
    pos = labels.index(chosen_label)
    return shuffled[pos][0] == 0


def render_review_scroller(
    qids: List[str],
    state: Dict[str, Any],
    session: Dict[str, Any],
    view_mode: str,
    height_px: int = 540,
) -> None:
    items = []
    for n, qid in enumerate(qids, start=1):
        q = state["questions"][qid]
        labels, shuffled = build_labels_for_question(qid, q)
        chosen_label = session["answers"].get(qid, None)

        if chosen_label is None:
            is_unanswered = True
            is_correct = False
            chosen_show = "— (non risposta)"
        else:
            is_unanswered = False
            is_correct = compute_is_correct_from_label(labels, shuffled, chosen_label)
            chosen_show = chosen_label

        if view_mode == "Solo errate" and (is_correct or is_unanswered):
            continue
        if view_mode == "Solo corrette" and (not is_correct or is_unanswered):
            continue

        # 🔵 NON RISPOSTA resta AZZURRA
        if is_unanswered:
            status = "🔵 NON RISPOSTA"
            box_class = "na"
        else:
            status = "✅ CORRETTA" if is_correct else "❌ ERRATA"
            box_class = "ok" if is_correct else "bad"

        cap = html_lib.escape(str(q["capitolo"]))
        domanda = html_lib.escape(str(q["domanda"]))
        corretta = html_lib.escape(str(q["corretta"]))
        chosen_esc = html_lib.escape(str(chosen_show))

        items.append(
            f"""
          <div class="item {box_class}">
            <div class="title">{n}. {status} <span class="cap">— Capitolo: {cap}</span></div>
            <div class="row"><b>Domanda:</b> {domanda}</div>
            <div class="row"><b>La tua risposta:</b> {chosen_esc}</div>
            <div class="row"><b>Corretta:</b> {corretta}</div>
          </div>
        """
        )

    inner = "".join(items) if items else "<i>Nessun elemento da mostrare.</i>"

    html_doc = f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <style>
          body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin:0; padding:0; }}
          .wrap {{ max-height:{height_px}px; overflow-y:auto; padding: 8px 6px; }}
          .item {{ border:1px solid #e6e6e6; border-radius: 12px; padding: 10px 12px; margin: 10px 0; }}
          .item.ok {{ background:#d7f5d7; border-color:#7bd67b; }}
          .item.bad {{ background:#ffd6d6; border-color:#ff7b7b; }}
          .item.na {{ background:#d6ecff; border-color:#5aa9ff; }}
          .title {{ font-weight:700; margin-bottom: 6px; }}
          .cap {{ font-weight:400; opacity:0.85; font-size: 0.95em; }}
          .row {{ margin: 4px 0; }}
        </style>
      </head>
      <body>
        <div class="wrap">
          {inner}
        </div>
      </body>
    </html>
    """

    components.html(html_doc, height=height_px + 20, scrolling=False)


# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)

st.markdown(
    """
    <style>
    div[data-testid="stRadio"] > div {gap: 0.35rem;}
    .opt {padding: 0.65rem 0.8rem; border-radius: 10px; border: 1px solid #ddd;}
    .correct {background: #d7f5d7 !important; border: 1px solid #7bd67b !important;}
    .wrong {background: #ffd6d6 !important; border: 1px solid #ff7b7b !important;}
    .muted {opacity: 0.92;}
    </style>
    """,
    unsafe_allow_html=True,
)

state = load_state()

with st.sidebar:
    st.header("Navigazione")
    page = st.radio("Schermata", ["QUIZ", "STATISTICHE"], index=0)

    st.divider()
    st.header("Importa XLSX")
    uploaded = st.file_uploader("Carica XLSX", type=["xlsx"])
    if uploaded is not None:
        if st.button("Importa / Aggiorna banca dati"):
            try:
                state = import_xlsx_to_state(uploaded, state)
            except Exception as e:
                st.error(f"Errore import: {e}")

    st.divider()

    if page == "QUIZ":
        st.header("Sessione")

        all_questions = get_all_questions(state)
        if not all_questions:
            st.info("Carica un file .xlsx per iniziare.")
        else:
            chapters = sorted(list({q.capitolo for q in all_questions}))
            selected_chapters = st.multiselect("Capitoli (facoltativo)", chapters, default=[])

            mode = st.selectbox("Modalità", ["Studio", "Simulazione", "Ripeti sbagliate"])

            wrong_scope = "Tutte"
            if mode == "Ripeti sbagliate":
                wrong_scope = st.selectbox("Ambito sbagliate", ["Solo ultima sessione", "Ultimi 7 giorni", "Tutte"])

            order = st.selectbox("Ordine", ["Casuale", "Per capitolo"])
            n_questions = st.number_input("Numero domande (0 = tutte)", min_value=0, max_value=5000, value=20, step=5)

            show_immediate = True
            if mode == "Simulazione":
                show_immediate = st.checkbox("Mostra correzione subito", value=False)

            if "session" not in st.session_state:
                st.session_state.session = None

            if st.button("Avvia sessione"):
                qids = build_session_qids(
                    state=state,
                    mode=mode,
                    selected_chapters=selected_chapters,
                    n_questions=int(n_questions),
                    order=order,
                    wrong_scope=wrong_scope,
                )
                if not qids:
                    st.warning("Nessuna domanda disponibile con questi filtri/modalità.")
                else:
                    st.session_state.session = {
                        "mode": mode,
                        "show_immediate": show_immediate if mode != "Studio" else True,
                        "qids": qids,
                        "idx": 0,
                        "answers": {},     # in Simulazione = modificabili
                        "revealed": {},    # per feedback immediato
                        "start_ts": int(time.time()),
                        "scored": False,   # ✅ Simulazione: stats solo a fine esame
                        "selected_chapters": selected_chapters,
                    }
                    state["last_session"] = {"wrong_qids": [], "correct_qids": [], "ts": int(time.time())}
                    save_state(state)
                    st.success(f"Sessione avviata: {len(qids)} domande.")


# ----------------------------
# PAGE: STATISTICHE
# ----------------------------
if page == "STATISTICHE":
    all_questions = get_all_questions(state)
    if not all_questions:
        st.info("Carica un file .xlsx per vedere le statistiche.")
        st.stop()

    st.subheader("Riepilogo")
    s = overall_stats(state)
    st.write(f"- Domande in banca: **{s['domande']}**")
    st.write(f"- Tentativi totali: **{s['tentativi']}**")
    st.write(f"- Accuratezza: **{s['accuratezza']:.1f}%**")
    st.write(f"- In “Ripeti sbagliate”: **{s['ripeti_sbagliate']}**")

    st.divider()
    st.subheader("Reset statistiche")
    st.caption("Azzera tentativi/corrette/sbagliate, streak, coda ripeti sbagliate e ultima sessione. NON cancella le domande.")
    confirm_reset = st.checkbox("Confermo: voglio resettare tutte le statistiche", value=False)
    if st.button("🧹 Reset statistiche", disabled=(not confirm_reset)):
        state = reset_statistics(state)
        st.success("Statistiche resettate ✅")
        st.rerun()

    st.divider()
    st.subheader("Andamento per capitolo")
    df_stats = chapter_stats(state)
    if df_stats.empty:
        st.write("Nessuna statistica ancora.")
    else:
        st.dataframe(df_stats, use_container_width=True, hide_index=True)

    st.stop()


# ----------------------------
# PAGE: QUIZ
# ----------------------------
all_questions = get_all_questions(state)
if not all_questions:
    st.info("Carica un file .xlsx (sidebar) per iniziare il quiz.")
    st.stop()

session = st.session_state.get("session")
if not session:
    st.info("Avvia una sessione dalla sidebar (QUIZ).")
    st.stop()

qids = session["qids"]
idx = session["idx"]
mode_now = session.get("mode", "Studio")
show_immediate = session.get("show_immediate", True)


def score_simulation_once() -> Tuple[List[str], List[str]]:
    """
    Calcola corrette/sbagliate in base alle risposte finali della Simulazione.
    Registra le statistiche UNA SOLA VOLTA e salva last_session.
    """
    wrongs: List[str] = []
    corrects: List[str] = []

    for qid_local in qids:
        chosen_label = session["answers"].get(qid_local, None)
        if chosen_label is None:
            # NON RISPOSTA: non incrementa tentativi
            continue

        q_local = state["questions"][qid_local]
        labels_local, shuffled_local = build_labels_for_question(qid_local, q_local)
        is_correct = compute_is_correct_from_label(labels_local, shuffled_local, chosen_label)

        # registra su state
        register_answer(state, qid_local, is_correct)

        if is_correct:
            corrects.append(qid_local)
        else:
            wrongs.append(qid_local)

    save_state(state)
    state["last_session"] = {"wrong_qids": wrongs, "correct_qids": corrects, "ts": int(time.time())}
    save_state(state)
    return wrongs, corrects


# ----------------------------
# Fine sessione
# ----------------------------
if idx >= len(qids):
    if mode_now == "Simulazione" and not session.get("scored", False):
        wrongs, corrects = score_simulation_once()
        session["wrong_in_session"] = wrongs
        session["correct_in_session"] = corrects
        session["scored"] = True
    else:
        wrongs = session.get("wrong_in_session", [])
        corrects = session.get("correct_in_session", [])

    st.success("Sessione completata ✅")
    st.write(f"Corrette: **{len(corrects)}**  |  Sbagliate: **{len(wrongs)}**  | Totale domande: **{len(qids)}**")

    if mode_now == "Simulazione":
        st.divider()
        st.subheader("Revisione simulazione")
        view_mode = st.radio("Mostra", ["Tutte", "Solo errate", "Solo corrette"], horizontal=True)
        render_review_scroller(qids=qids, state=state, session=session, view_mode=view_mode, height_px=540)

        st.divider()
        c1, c2 = st.columns([1, 2])
        with c1:
            if st.button("Ripeti subito le errate", disabled=(len(wrongs) == 0)):
                qids2 = list(wrongs)
                random.shuffle(qids2)
                st.session_state.session = {
                    "mode": "Ripeti sbagliate",
                    "show_immediate": True,
                    "qids": qids2,
                    "idx": 0,
                    "answers": {},
                    "revealed": {},
                    "start_ts": int(time.time()),
                    "wrong_in_session": [],
                    "correct_in_session": [],
                    "scored": False,
                    "selected_chapters": session.get("selected_chapters", []),
                }
                st.rerun()
        with c2:
            if len(wrongs) == 0:
                st.info("Non ci sono errate da ripetere ✅")

    st.divider()
    if st.button("Chiudi sessione"):
        st.session_state.session = None
        st.rerun()

    st.stop()


# ----------------------------
# Domanda corrente
# ----------------------------
qid = qids[idx]
q = state["questions"][qid]

st.progress((idx + 1) / len(qids))
st.write(f"**{idx+1}/{len(qids)}** — **{q['capitolo']}**")
st.markdown(f"## {q['domanda']}")

labels, shuffled = build_labels_for_question(qid, q)

radio_key = f"radio_{qid}"
# Preimposta la radio con l'ultima scelta (utile per modificare in Simulazione)
if radio_key not in st.session_state:
    st.session_state[radio_key] = session["answers"].get(qid, None)


def on_select():
    chosen = st.session_state.get(radio_key, None)
    if chosen is None:
        return

    # Studio e Ripeti sbagliate: blocca dopo la prima risposta (stile training)
    if mode_now in ["Studio", "Ripeti sbagliate"]:
        if qid in session["answers"]:
            return

        session["answers"][qid] = chosen
        is_correct = compute_is_correct_from_label(labels, shuffled, chosen)
        register_answer(state, qid, is_correct)
        save_state(state)

        # per fine sessione "Rapida"
        if "wrong_in_session" not in session:
            session["wrong_in_session"] = []
        if "correct_in_session" not in session:
            session["correct_in_session"] = []
        if is_correct:
            session["correct_in_session"].append(qid)
        else:
            session["wrong_in_session"].append(qid)

        session["revealed"][qid] = True
        return

    # ✅ SIMULAZIONE (ESAME): risposta MODIFICABILE
    session["answers"][qid] = chosen
    # feedback immediato opzionale (senza registrare stats)
    session["revealed"][qid] = bool(show_immediate)


# Studio: mostra subito corretta
if mode_now == "Studio":
    st.markdown(
        f'<div class="opt correct"><b>✅ Risposta corretta (Studio):</b> {q["corretta"]}</div>',
        unsafe_allow_html=True,
    )

# RADIO: in Simulazione NON è disabilitata (puoi cambiare)
if mode_now in ["Studio", "Ripeti sbagliate"] and qid in session["answers"]:
    chosen_label = session["answers"].get(qid, None)
    st.radio(
        "Scegli una risposta:",
        labels,
        index=labels.index(chosen_label) if chosen_label in labels else 0,
        disabled=True,
    )
else:
    chosen_label = session["answers"].get(qid, None)
    st.radio(
        "Scegli una risposta:",
        labels,
        index=labels.index(chosen_label) if chosen_label in labels else None,
        key=radio_key,
        on_change=on_select,
    )

# FEEDBACK (in Simulazione solo se show_immediate)
if session["revealed"].get(qid, False) and session["answers"].get(qid, None) is not None:
    chosen_label = session["answers"][qid]
    is_correct = compute_is_correct_from_label(labels, shuffled, chosen_label)

    if is_correct:
        st.markdown(
            f'<div class="opt correct"><b>✅ Corretto!</b> Risposta: {q["corretta"]}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="opt wrong"><b>❌ Errato.</b> Hai scelto: {chosen_label}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="opt correct muted"><b>✅ Corretta:</b> {q["corretta"]}</div>',
            unsafe_allow_html=True,
        )

# NAVIGAZIONE
nav1, nav2, nav3 = st.columns([1, 1, 2])
with nav1:
    if st.button("⬅️ Indietro", disabled=(idx == 0)):
        session["idx"] -= 1
        st.rerun()
with nav2:
    if st.button("Avanti ➡️", disabled=(idx >= len(qids) - 1)):
        session["idx"] += 1
        st.rerun()
with nav3:
    if st.button("Termina sessione"):
        session["idx"] = len(qids)
        st.rerun()
