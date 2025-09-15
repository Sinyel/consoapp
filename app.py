"""
Credit Decision App

Ce fichier contient :
- la logique décisionnelle (fonction `decision_credit`) adaptée aux règles PDF,
- une application Streamlit multi-étapes (si Streamlit est installé),
- un mode CLI / suite de tests qui s'exécute automatiquement si Streamlit n'est pas présent.

Corrections appliquées suite à ton retour sur l'étape 1 :
1) Le taux d'endettement est interprété correctement — l'UI accepte soit une valeur décimale (ex. 0.6) soit un pourcentage (ex. 60) ; la valeur est normalisée en décimal avant d'être évaluée. Une valeur strictement supérieure à 1/3 déclenche immédiatement un refus (rouge).
2) Le champ "Date fin CDD" n'est affiché **que** si l'utilisateur choisit "CDD" comme type de contrat.
3) On demande la **durée du crédit (en mois)** dès l'étape 1 ; l'application calcule la **date de début du crédit = aujourd'hui + 15 jours** et la **date de fin du crédit** en ajoutant la durée demandée. La règle CDD -> refus est : si `date_fin_cdd < date_fin_du_crédit_demandé` alors refus (rouge).

Remarques :
- La fonction `decision_credit` est résistante aux validations étape-par-étape : elle ne retourne pas de faux refus quand un champ attendu n'est pas encore fourni (par ex. lors de la validation partielle après l'étape 1), sauf pour les conditions qui peuvent être évaluées immédiatement (ex. taux d'endettement).
- Si Streamlit n'est pas disponible, le script lancera la suite de tests CLI et enregistrera un CSV `historique_credit_cli.csv`.
"""

import datetime
import calendar
import pandas as pd
import sys
import os
from typing import Dict, Any

# Import Streamlit uniquement si disponible
try:
    import streamlit as st  # type: ignore
    HAS_STREAMLIT = True
except Exception:
    HAS_STREAMLIT = False


# ------------------
# Helpers
# ------------------

def _ensure_date(obj):
    """Converts obj to datetime.date when possible, otherwise returns None."""
    if obj is None:
        return None
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
    return None


def add_months(sourcedate: datetime.date, months: int) -> datetime.date:
    """Add months to a date reliably (rollover years/months).
    Uses calendar.monthrange to clamp day of month.
    """
    if months <= 0:
        return sourcedate
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


# ------------------
# Decision logic
# ------------------

def decision_credit(data: Dict[str, Any]) -> str:
    """
    Applique les règles de décision. Le paramètre `data` est un dictionnaire qui peut être
    partiellement rempli (utile pour des validations étape par étape). La fonction retourne :
      - 'Refus (rouge) : ...',
      - 'Risque ORANGE : ...',
      - 'ACCEPTE'
    """

    # Normalisation / valeurs par défaut sécurisées pour validations partielles
    raw_taux = data.get("taux_endettement", 0.0)
    try:
        taux_endettement = float(raw_taux)
    except Exception:
        taux_endettement = 0.0

    # Interprétation intelligente : si user donne > 1 on considère que c'est un pourcentage (ex. 60 -> 0.6)
    if taux_endettement > 1.0:
        taux_endettement = taux_endettement / 100.0

    type_contrat = data.get("type_contrat", "CDI")

    duree_credit_mois = int(data.get("duree_credit_mois", 0))
    # Date de début = aujourd'hui + 15 jours suivant la règle demandée
    if duree_credit_mois > 0:
        date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
        date_fin_credit = add_months(date_debut_credit, duree_credit_mois)
    else:
        date_debut_credit = None
        date_fin_credit = datetime.date.max  # permet d'éviter des refus si la durée n'est pas encore saisie

    # Safety-extracted employer / account fields with permissive defaults
    anciennete_compte = int(data.get("anciennete_compte", 999))
    impayes_actuels = bool(data.get("impayes_actuels", False))
    anciens_impayes = int(data.get("anciens_impayes", 0))
    anciennete_employeur = int(data.get("anciennete_employeur", 999))
    employeur_connu = data.get("employeur_connu", "Oui")
    suspicion_employeur = bool(data.get("suspicion_employeur", False))

    # 1) Endettement — condition immédiate rouge si > 1/3
    if taux_endettement > (1.0 / 3.0):
        return "Refus (rouge) : Endettement trop élevé"

    # 2) Contrat CDD — on vérifie la date de fin du contrat seulement si le champ a été fourni
    if type_contrat == "CDD":
        raw_date_fin_cdd = data.get("date_fin_cdd", None)
        date_fin_cdd = _ensure_date(raw_date_fin_cdd)
        if date_fin_cdd is not None and date_fin_cdd < date_fin_credit:
            return "Refus (rouge) : CDD se termine avant la fin du crédit demandé"

    # 3) Ancienneté compte
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

    # 6) Suspicion employeur
    if suspicion_employeur:
        return "Risque ORANGE : Vérification nécessaire sur employeur"

    return "ACCEPTE"


# ------------------
# Streamlit UI (multi-étapes)
# ------------------

def run_streamlit_app():
    st.set_page_config(page_title="Simulation Crédit", layout="centered")
    st.title("📊 Simulation Octroi Crédit à la Consommation")

    if "step" not in st.session_state:
        st.session_state.step = 1
    if "form_data" not in st.session_state:
        st.session_state.form_data = {}
    if "historique" not in st.session_state:
        st.session_state.historique = []

    # --- Étape 1 ---
    if st.session_state.step == 1:
        st.subheader("Étape 1 — Informations de base")

        # On accepte soit un décimal 0-1, soit un pourcentage 0-100 (auto-detect)
        raw_taux = st.number_input(
            "Taux d'endettement (ex. 0.60 = 60% ou 60)", min_value=0.0, max_value=100.0, step=0.1, value=0.3
        )
        st.caption("Saisie acceptée : 0.6 ou 60 (les deux). Les valeurs >1 seront interprétées comme des pourcentages.")

        duree_credit_mois = st.number_input("Durée du crédit (mois)", min_value=1, value=12)

        type_contrat = st.selectbox("Type de contrat", ["CDI", "CDD"])

        date_fin_cdd = None
        if type_contrat == "CDD":
            date_fin_cdd = st.date_input("Date fin CDD (si CDD)", value=(datetime.date.today() + datetime.timedelta(days=180)))

        # Calcul des dates de crédit pour affichage
        date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
        date_fin_credit = add_months(date_debut_credit, int(duree_credit_mois))
        st.info(f"Date de début estimée du crédit : {date_debut_credit} — Date de fin estimée : {date_fin_credit}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Suivant"):
                # Normalisation du taux (auto-detect)
                taux_normalise = float(raw_taux)
                if taux_normalise > 1.0:
                    taux_normalise = taux_normalise / 100.0

                st.session_state.form_data.update({
                    "taux_endettement": taux_normalise,
                    "duree_credit_mois": int(duree_credit_mois),
                    "type_contrat": type_contrat,
                    "date_fin_cdd": date_fin_cdd,
                    "date_debut_credit": date_debut_credit,
                    "date_fin_credit": date_fin_credit,
                })

                # Vérification immédiate des règles évaluables en étape 1
                resultat = decision_credit(st.session_state.form_data)
                if "Refus" in resultat:
                    st.error(resultat)
                else:
                    st.session_state.step = 2

    # --- Étape 2 ---
    elif st.session_state.step == 2:
        st.subheader("Étape 2 — Compte et historique")
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
                    "anciennete_compte": int(anciennete_compte),
                    "impayes_actuels": bool(impayes_actuels),
                    "anciens_impayes": int(anciens_impayes),
                })
                resultat = decision_credit(st.session_state.form_data)
                if "Refus" in resultat:
                    st.error(resultat)
                else:
                    st.session_state.step = 3

    # --- Étape 3 ---
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
                    "anciennete_employeur": int(anciennete_employeur),
                    "employeur_connu": employeur_connu,
                    "suspicion_employeur": bool(suspicion_employeur),
                })
                resultat = decision_credit(st.session_state.form_data)

                if "Refus" in resultat:
                    st.error(resultat)
                elif "ORANGE" in resultat:
                    st.warning(resultat)
                else:
                    st.success(resultat)

                # Sauvegarde dans l'historique
                st.session_state.historique.append({**st.session_state.form_data, "Décision": resultat})
                st.session_state.step = 1

    # Affichage historique + export
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
    now = datetime.date.today()
    yesterday = now - datetime.timedelta(days=1)
    future = now + datetime.timedelta(days=365)

    test_cases = [
        {
            "name": "endettement_trop_eleve (rouge)",
            "input": {"taux_endettement": 0.6, "duree_credit_mois": 12},
            "expected_contains": "Refus",
        },
        {
            "name": "CDD termine (rouge)",
            "input": {"taux_endettement": 0.10, "type_contrat": "CDD", "date_fin_cdd": yesterday, "duree_credit_mois": 12},
            "expected_contains": "Refus",
        },
        {
            "name": "CDD assez long (ok)",
            "input": {"taux_endettement": 0.10, "type_contrat": "CDD", "date_fin_cdd": future, "duree_credit_mois": 6},
            "expected_contains": "ACCEPTE",
        },
        {
            "name": "client_trop_recent (rouge)",
            "input": {"taux_endettement": 0.10, "anciennete_compte": 1, "duree_credit_mois": 12},
            "expected_contains": "Refus",
        },
        {
            "name": "impayes_actuels (rouge)",
            "input": {"taux_endettement": 0.10, "impayes_actuels": True, "duree_credit_mois": 12},
            "expected_contains": "Refus",
        },
        {
            "name": "anciens_impayes_trop (rouge)",
            "input": {"taux_endettement": 0.10, "anciens_impayes": 2, "duree_credit_mois": 12},
            "expected_contains": "Refus",
        },
        {
            "name": "anciennete_employeur_court (rouge)",
            "input": {"taux_endettement": 0.10, "anciennete_employeur": 2, "duree_credit_mois": 12},
            "expected_contains": "Refus",
        },
        {
            "name": "employeur_non_fiable (orange)",
            "input": {"taux_endettement": 0.05, "anciennete_employeur": 6, "employeur_connu": "Non", "duree_credit_mois": 12},
            "expected_contains": "ORANGE",
        },
        {
            "name": "suspicion_employeur (orange)",
            "input": {"taux_endettement": 0.05, "anciennete_employeur": 24, "suspicion_employeur": True, "duree_credit_mois": 12},
            "expected_contains": "ORANGE",
        },
        {
            "name": "accepte (ok)",
            "input": {"taux_endettement": 0.10, "anciennete_compte": 12, "anciennete_employeur": 24, "duree_credit_mois": 12},
            "expected_contains": "ACCEPTE",
        },
        {
            "name": "partial_after_step1_no_rouge",
            "input": {"taux_endettement": 0.20, "type_contrat": "CDI", "duree_credit_mois": 12},
            "expected_contains": "ACCEPTE",
        },
        {
            "name": "partial_after_step1_cdd_expired (rouge)",
            "input": {"taux_endettement": 0.10, "type_contrat": "CDD", "date_fin_cdd": yesterday, "duree_credit_mois": 12},
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

    any_failed = not df["passed"].all()
    if any_failed:
        print("\nSome tests failed. Inspect 'historique_credit_cli.csv' for details.")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


# ------------------
# Entrypoint
# ------------------

if __name__ == "__main__":
    if HAS_STREAMLIT:
        run_streamlit_app()
    else:
        print("Streamlit not installé — lancement du mode CLI / tests...\n")
        run_cli_tests()

# Fin du fichier
