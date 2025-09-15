"""
Credit Decision App

This file contains two modes:
1) Streamlit web app (if the `streamlit` package is available).  
2) CLI / test mode fallback (runs automatically when Streamlit is not installed).

We intentionally avoid importing Streamlit at top-level so the file can be executed in environments
where Streamlit is not available. If Streamlit is present, the Streamlit UI will run. Otherwise a
set of automated tests will run and results will be printed and saved to `historique_credit_cli.csv`.

The decision logic (function `decision_credit`) is robust to *partial* input dictionaries so it
can be called after each step of a multi-step form to determine whether a red (refus) condition
is already met (so the form can stop early), or whether an orange (alerte) condition is present.
"""

import datetime
import pandas as pd
import sys
import os
from typing import Dict, Any

# Try to import streamlit only when we need it.
try:
    import streamlit as st  # type: ignore
    HAS_STREAMLIT = True
except Exception:
    HAS_STREAMLIT = False


# ------------------
# Decision logic
# ------------------

def _ensure_date(obj):
    """Return a datetime.date from obj when possible, else datetime.date.max."""
    if obj is None:
        return datetime.date.max
    if isinstance(obj, datetime.date):
        return obj
    if isinstance(obj, datetime.datetime):
        return obj.date()
    if isinstance(obj, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.datetime.strptime(obj, fmt).date()
            except Exception:
                pass
    return datetime.date.max


def decision_credit(data: Dict[str, Any]) -> str:
    """
    Applies the decision rules. The function is tolerant to missing keys and uses defaults that
    *avoid* false early refusals when a field has not been provided yet (useful for step-by-step
    forms where we validate early steps).

    Returns one of:
      - "Refus (rouge) : ..."
      - "Risque ORANGE : ..."
      - "ACCEPTE"
    """

    # Safe extraction with defaults that *do not* trigger false refusals when keys are missing.
    taux_endettement = float(data.get("taux_endettement", 0.0))
    type_contrat = data.get("type_contrat", "CDI")
    date_fin_cdd = _ensure_date(data.get("date_fin_cdd", None))

    # For stepwise validation we prefer defaults that mean "no problem" if not provided.
    anciennete_compte = int(data.get("anciennete_compte", 999))
    impayes_actuels = bool(data.get("impayes_actuels", False))
    anciens_impayes = int(data.get("anciens_impayes", 0))
    anciennete_employeur = int(data.get("anciennete_employeur", 999))
    employeur_connu = data.get("employeur_connu", "Oui")
    suspicion_employeur = bool(data.get("suspicion_employeur", False))

    # 1) Taux d'endettement
    if taux_endettement > (1.0 / 3.0):
        return "Refus (rouge) : Endettement trop élevé"

    # 2) Contrat
    if type_contrat == "CDD" and date_fin_cdd <= datetime.date.today():
        return "Refus (rouge) : CDD terminé"

    # 3) Ancienneté du compte
    if anciennete_compte < 3:
        return "Refus (rouge) : Client trop récent"

    # 4) Impayés
    if impayes_actuels:
        return "Refus (rouge) : Impayés actuels dans les 6 derniers mois"
    if anciens_impayes > 1:
        return "Refus (rouge) : Trop d'anciens impayés"

    # 5) Ancienneté chez l'employeur
    if anciennete_employeur < 3:
        return "Refus (rouge) : Ancienneté chez l’employeur < 3 mois"
    if 3 <= anciennete_employeur <= 12:
        if employeur_connu == "Non" or suspicion_employeur:
            return "Risque ORANGE : Employeur non fiable ou suspicion"

    # 6) Suspicion générale
    if suspicion_employeur:
        return "Risque ORANGE : Vérification nécessaire sur employeur"

    # Everything passed
    return "ACCEPTE"


# ------------------
# Streamlit UI (only used when Streamlit is available)
# ------------------

def run_streamlit_app():
    """Launch the multi-step Streamlit app."""
    st.set_page_config(page_title="Simulation Crédit", layout="centered")
    st.title("📊 Simulation Octroi Crédit à la Consommation")

    if "step" not in st.session_state:
        st.session_state.step = 1
    if "form_data" not in st.session_state:
        st.session_state.form_data = {}
    if "historique" not in st.session_state:
        st.session_state.historique = []

    # Step 1
    if st.session_state.step == 1:
        st.subheader("Étape 1 — Informations de base")
        taux_endettement = st.number_input("Taux d'endettement (%)", min_value=0.0, max_value=100.0, step=0.1) / 100.0
        type_contrat = st.selectbox("Type de contrat", ["CDI", "CDD"])
        date_fin_cdd = st.date_input("Date fin CDD (si applicable)", value=datetime.date.today())

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Suivant"):
                st.session_state.form_data.update({
                    "taux_endettement": taux_endettement,
                    "type_contrat": type_contrat,
                    "date_fin_cdd": date_fin_cdd,
                })
                # Check for immediate red conditions
                resultat = decision_credit(st.session_state.form_data)
                if "Refus" in resultat:
                    st.error(resultat)
                else:
                    st.session_state.step = 2

    # Step 2
    elif st.session_state.step == 2:
        st.subheader("Étape 2 — Compte et impayés")
        anciennete_compte = st.number_input("Ancienneté du compte (mois)", min_value=0)
        impayes_actuels = st.checkbox("Impayés actuels (6 derniers mois)")
        anciens_impayes = st.number_input("Nb d'anciens impayés > 1 mois", min_value=0)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅ Retour"):
                st.session_state.step = 1
        with col2:
            if st.button("Suivant"):
                st.session_state.form_data.update({
                    "anciennete_compte": anciennete_compte,
                    "impayes_actuels": impayes_actuels,
                    "anciens_impayes": anciens_impayes,
                })
                resultat = decision_credit(st.session_state.form_data)
                if "Refus" in resultat:
                    st.error(resultat)
                else:
                    st.session_state.step = 3

    # Step 3
    elif st.session_state.step == 3:
        st.subheader("Étape 3 — Informations employeur")
        anciennete_employeur = st.number_input("Ancienneté chez l'employeur (mois)", min_value=0)
        employeur_connu = st.selectbox("Employeur connu ?", ["Oui", "Non"])
        suspicion_employeur = st.checkbox("Suspicion sur l'employeur")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅ Retour"):
                st.session_state.step = 2
        with col2:
            if st.button("Décision finale"):
                st.session_state.form_data.update({
                    "anciennete_employeur": anciennete_employeur,
                    "employeur_connu": employeur_connu,
                    "suspicion_employeur": suspicion_employeur,
                })
                resultat = decision_credit(st.session_state.form_data)

                if "Refus" in resultat:
                    st.error(resultat)
                elif "ORANGE" in resultat:
                    st.warning(resultat)
                else:
                    st.success(resultat)

                # Store in history and reset to step 1
                st.session_state.historique.append({**st.session_state.form_data, "Décision": resultat})
                st.session_state.step = 1

    # History and export
    if st.session_state.historique:
        df = pd.DataFrame(st.session_state.historique)
        st.subheader("Historique des simulations")
        st.dataframe(df)
        st.download_button(
            "📥 Télécharger l'historique (CSV)",
            data=df.to_csv(index=False),
            file_name="historique_credit.csv",
            mime="text/csv",
        )


# ------------------
# CLI / Test mode
# ------------------

def run_cli_tests():
    """Runs a set of test cases for the decision function and writes a CSV summary."""
    now = datetime.date.today()
    yesterday = now - datetime.timedelta(days=1)
    future = now + datetime.timedelta(days=365)

    test_cases = [
        {
            "name": "endettement_trop_eleve (rouge)",
            "input": {"taux_endettement": 0.40},
            "expected_contains": "Refus",
        },
        {
            "name": "CDD termine (rouge)",
            "input": {"taux_endettement": 0.10, "type_contrat": "CDD", "date_fin_cdd": yesterday},
            "expected_contains": "Refus",
        },
        {
            "name": "client_trop_recent (rouge)",
            "input": {"taux_endettement": 0.10, "anciennete_compte": 1},
            "expected_contains": "Refus",
        },
        {
            "name": "impayes_actuels (rouge)",
            "input": {"taux_endettement": 0.10, "impayes_actuels": True},
            "expected_contains": "Refus",
        },
        {
            "name": "anciens_impayes_trop (rouge)",
            "input": {"taux_endettement": 0.10, "anciens_impayes": 2},
            "expected_contains": "Refus",
        },
        {
            "name": "anciennete_employeur_court (rouge)",
            "input": {"taux_endettement": 0.10, "anciennete_employeur": 2},
            "expected_contains": "Refus",
        },
        {
            "name": "employeur_non_fiable (orange)",
            "input": {"taux_endettement": 0.05, "anciennete_employeur": 6, "employeur_connu": "Non"},
            "expected_contains": "ORANGE",
        },
        {
            "name": "suspicion_employeur (orange)",
            "input": {"taux_endettement": 0.05, "anciennete_employeur": 24, "suspicion_employeur": True},
            "expected_contains": "ORANGE",
        },
        {
            "name": "accepte (ok)",
            "input": {"taux_endettement": 0.10, "anciennete_compte": 12, "anciennete_employeur": 24},
            "expected_contains": "ACCEPTE",
        },
        # Partial input tests (simulate early step checks)
        {
            "name": "partial_after_step1_no_rouge",
            "input": {"taux_endettement": 0.20, "type_contrat": "CDI"},
            "expected_contains": "ACCEPTE",
        },
        {
            "name": "partial_after_step1_cdd_expired (rouge)",
            "input": {"taux_endettement": 0.10, "type_contrat": "CDD", "date_fin_cdd": yesterday},
            "expected_contains": "Refus",
        },
    ]

    rows = []
    print("Running CLI tests for decision_credit()...\n")
    for tc in test_cases:
        name = tc["name"]
        inp = tc["input"]
        expected = tc["expected_contains"]
        try:
            out = decision_credit(inp)
            passed = expected in out
            rows.append({"test": name, "input": inp, "output": out, "passed": passed})
            status = "PASS" if passed else "FAIL"
            print(f"[{status}] {name}: -> {out}")
        except Exception as e:
            rows.append({"test": name, "input": inp, "output": f"EXCEPTION: {e}", "passed": False})
            print(f"[ERROR] {name}: exception: {e}")

    df = pd.DataFrame(rows)
    csv_path = os.path.join(os.getcwd(), "historique_credit_cli.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nSummary saved to: {csv_path}")

    # Exit with non-zero code if any test failed so CI can catch it
    any_failed = not df["passed"].all()
    if any_failed:
        print("\nSome tests failed. Inspect 'historique_credit_cli.csv' for details.")
        # Do not forcibly exit in interactive contexts, but return non-zero for scripts
        sys.exit(1)
    else:
        print("\nAll tests passed.")


# ------------------
# Entrypoint
# ------------------

if __name__ == "__main__":
    if HAS_STREAMLIT:
        # When executed with `streamlit run this_file.py` Streamlit will run and this branch will
        # not be executed in the usual script manner. But if someone runs `python this_file.py`
        # and streamlit is installed, we still provide the UI.
        run_streamlit_app()
    else:
        print("Streamlit not installed — running CLI test suite instead.\n")
        run_cli_tests()

# If the module is imported, do not run anything automatically. The Streamlit runner will
# import this module and execute run_streamlit_app() because the top-level streamlit import
# is deferred.
