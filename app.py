"""
Credit Decision App

Ce fichier contient :
- la logique décisionnelle (fonction `decision_credit`) adaptée aux règles PDF,
- une application Streamlit multi-étapes (si Streamlit est installé),
- un mode CLI / suite de tests qui s'exécute automatiquement si Streamlit n'est pas présent.

Mises à jour (Étape 2) :
1) `Impayés anciens` devient **binaire** (checkbox) ; plus de saisie de nombre.
2) Si `Impayés anciens = Oui`, on pose deux questions :
   - `Changement d’employeur ?` (checkbox)
   - `Amélioration de la situation de l’employeur ?` (checkbox)
   - Si au moins une est **Oui** → on vérifie **taux d'endettement ≤ 25%** (0.25).
       - Si `taux > 25%` → **Refus** : "limiter le taux d'endettement à 25% car impayés anciens".
       - Sinon → on peut continuer.
   - Si les deux sont **Non** → **Refus** : "Pas de changement chez l'employeur suite anciens impayés".

Les validations restent compatibles avec les formulaires multi-étapes.
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
    """Add months to a date reliably (rollover years/months)."""
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
    Applique les règles de décision. Le paramètre `data` peut être partiel (validation étape-par-étape).
    Retourne : 'Refus (rouge) : ...' | 'Risque ORANGE : ...' | 'ACCEPTE'
    """

    # Taux d'endettement (normalisation : si >1 on suppose un pourcentage)
    raw_taux = data.get("taux_endettement", 0.0)
    try:
        taux_endettement = float(raw_taux)
    except Exception:
        taux_endettement = 0.0
    if taux_endettement > 1.0:
        taux_endettement = taux_endettement / 100.0

    type_contrat = data.get("type_contrat", "CDI")

    # Crédit: durée et dates (début = today + 15 jours)
    duree_credit_mois = int(data.get("duree_credit_mois", 0))
    if duree_credit_mois > 0:
        date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
        date_fin_credit = add_months(date_debut_credit, duree_credit_mois)
    else:
        date_debut_credit = None
        date_fin_credit = datetime.date.max

    # Données compte / employeur avec défauts permissifs pour validation partielle
    anciennete_compte = int(data.get("anciennete_compte", 999))
    impayes_actuels = bool(data.get("impayes_actuels", False))
    impayes_anciens = bool(data.get("impayes_anciens", False))
    changement_employeur = bool(data.get("changement_employeur", False))
    amelioration_employeur = bool(data.get("amelioration_employeur", False))

    anciennete_employeur = int(data.get("anciennete_employeur", 999))
    employeur_connu = data.get("employeur_connu", "Oui")
    suspicion_employeur = bool(data.get("suspicion_employeur", False))

    # 1) Endettement — refus immédiat si > 1/3
    if taux_endettement > (1.0 / 3.0):
        return "Refus (rouge) : Endettement trop élevé"

    # 2) CDD — refuser si le contrat se termine avant la fin du crédit demandé
    if type_contrat == "CDD":
        date_fin_cdd = _ensure_date(data.get("date_fin_cdd", None))
        if date_fin_cdd is not None and date_fin_cdd < date_fin_credit:
            return "Refus (rouge) : CDD se termine avant la fin du crédit demandé"

    # 3) Ancienneté compte
    if anciennete_compte < 3:
        return "Refus (rouge) : Client trop récent"

    # 4) Impayés actuels
    if impayes_actuels:
        return "Refus (rouge) : Impayés actuels dans les 6 derniers mois"

    # 4bis) Impayés anciens (nouvelle logique binaire)
    if impayes_anciens:
        if changement_employeur or amelioration_employeur:
            # Au moins une réponse positive -> vérifier taux <= 25%
            if taux_endettement > 0.25:
                return "Refus (rouge) : limiter le taux d'endettement à 25% car impayés anciens"
            # sinon on peut continuer (pas de décision finale ici)
        else:
            # Les deux réponses sont négatives -> refus
            return "Refus (rouge) : Pas de changement chez l'employeur suite anciens impayés"

    # 5) Ancienneté chez l'employeur
    if anciennete_employeur < 3:
        return "Refus (rouge) : Ancienneté chez l’employeur < 3 mois"
    if 3 <= anciennete_employeur <= 12:
        if employeur_connu == "Non" or suspicion_employeur:
            return "Risque ORANGE : Employeur non fiable ou suspicion"

    # 6) Suspicion employeur (générale)
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

        raw_taux = st.number_input(
            "Taux d'endettement (ex. 0.60 = 60% ou 60)", min_value=0.0, max_value=100.0, step=0.1, value=0.3
        )
        st.caption("Vous pouvez saisir 0.6 ou 60. Les valeurs >1 sont interprétées comme pourcentage.")

        duree_credit_mois = st.number_input("Durée du crédit (mois)", min_value=1, value=12)
        type_contrat = st.selectbox("Type de contrat", ["CDI", "CDD"])

        date_fin_cdd = None
        if type_contrat == "CDD":
            date_fin_cdd = st.date_input("Date fin CDD (si CDD)", value=(datetime.date.today() + datetime.timedelta(days=180)))

        date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
        date_fin_credit = add_months(date_debut_credit, int(duree_credit_mois))
        st.info(f"Date de début estimée du crédit : {date_debut_credit} — Date de fin estimée : {date_fin_credit}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Suivant"):
                taux_normalise = float(raw_taux)
                if taux_normalise > 1.0:
                    taux_normalise /= 100.0

                st.session_state.form_data.update({
                    "taux_endettement": taux_normalise,
                    "duree_credit_mois": int(duree_credit_mois),
                    "type_contrat": type_contrat,
                    "date_fin_cdd": date_fin_cdd,
                    "date_debut_credit": date_debut_credit,
                    "date_fin_credit": date_fin_credit,
                })

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
        impayes_anciens = st.checkbox("Impayés anciens (il y a plus de 6 mois)")

        changement_employeur = False
        amelioration_employeur = False
        if impayes_anciens:
            st.markdown("**Informations complémentaires (car impayés anciens cochés)**")
            changement_employeur = st.checkbox("Changement d’employeur ?")
            amelioration_employeur = st.checkbox("Amélioration de la situation de l’employeur ?")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅ Retour"):
                st.session_state.step = 1
        with col2:
            if st.button("Suivant"):
                st.session_state.form_data.update({
                    "anciennete_compte": int(anciennete_compte),
                    "impayes_actuels": bool(impayes_actuels),
                    "impayes_anciens": bool(impayes_anciens),
                    "changement_employeur": bool(changement_employeur),
                    "amelioration_employeur": bool(amelioration_employeur),
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

                st.session_state.historique.append({**st.session_state.form_data, "Décision": resultat})
                st.session_state.step = 1

    # Historique + export
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
        {"name": "endettement_trop_eleve (rouge)",
         "input": {"taux_endettement": 0.6, "duree_credit_mois": 12},
         "expected_contains": "Refus"},
        {"name": "CDD termine (rouge)",
         "input": {"taux_endettement": 0.10, "type_contrat": "CDD", "date_fin_cdd": yesterday, "duree_credit_mois": 12},
         "expected_contains": "Refus"},
        {"name": "CDD assez long (ok)",
         "input": {"taux_endettement": 0.10, "type_contrat": "CDD", "date_fin_cdd": future, "duree_credit_mois": 6},
         "expected_contains": "ACCEPTE"},
        {"name": "client_trop_recent (rouge)",
         "input": {"taux_endettement": 0.10, "anciennete_compte": 1, "duree_credit_mois": 12},
         "expected_contains": "Refus"},
        {"name": "impayes_actuels (rouge)",
         "input": {"taux_endettement": 0.10, "impayes_actuels": True, "duree_credit_mois": 12},
         "expected_contains": "Refus"},
        {"name": "impayes_anciens_sans_changement (rouge)",
         "input": {"taux_endettement": 0.10, "impayes_anciens": True, "changement_employeur": False, "amelioration_employeur": False, "duree_credit_mois": 12},
         "expected_contains": "Refus"},
        {"name": "impayes_anciens_avec_changement_taux>25 (rouge)",
         "input": {"taux_endettement": 0.30, "impayes_anciens": True, "changement_employeur": True, "amelioration_employeur": False, "duree_credit_mois": 12},
         "expected_contains": "Refus"},
        {"name": "impayes_anciens_avec_changement_taux<=25 (continue)",
         "input": {"taux_endettement": 0.20, "impayes_anciens": True, "amelioration_employeur": True, "duree_credit_mois": 12, "anciennete_compte": 12, "anciennete_employeur": 24},
         "expected_contains": "ACCEPTE"},
        {"name": "anciennete_employeur_court (rouge)",
         "input": {"taux_endettement": 0.10, "anciennete_employeur": 2, "duree_credit_mois": 12},
         "expected_contains": "Refus"},
        {"name": "employeur_non_fiable (orange)",
         "input": {"taux_endettement": 0.05, "anciennete_employeur": 6, "employeur_connu": "Non", "duree_credit_mois": 12},
         "expected_contains": "ORANGE"},
        {"name": "suspicion_employeur (orange)",
         "input": {"taux_endettement": 0.05, "anciennete_employeur": 24, "suspicion_employeur": True, "duree_credit_mois": 12},
         "expected_contains": "ORANGE"},
        {"name": "accepte (ok)",
         "input": {"taux_endettement": 0.10, "anciennete_compte": 12, "anciennete_employeur": 24, "duree_credit_mois": 12},
         "expected_contains": "ACCEPTE"},
        {"name": "partial_after_step1_no_rouge",
         "input": {"taux_endettement": 0.20, "type_contrat": "CDI", "duree_credit_mois": 12},
         "expected_contains": "ACCEPTE"},
        {"name": "partial_after_step1_cdd_expired (rouge)",
         "input": {"taux_endettement": 0.10, "type_contrat": "CDD", "date_fin_cdd": yesterday, "duree_credit_mois": 12},
         "expected_contains": "Refus"},
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
