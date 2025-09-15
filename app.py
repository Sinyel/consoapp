"""
Credit Decision App

Mise à jour Étape 2 :
- Si `changement_employeur` ou `amelioration_employeur` est Oui et que `taux_endettement > 0.25`,
  alors l’utilisateur **ne peut pas continuer** le processus.
- Un message orange (warning) s’affiche :
  "Condition (orange) : limiter le taux d'endettement à 25% car impayés anciens".
"""

import datetime
import calendar
import pandas as pd
import sys
import os
from typing import Dict, Any

try:
    import streamlit as st  # type: ignore
    HAS_STREAMLIT = True
except Exception:
    HAS_STREAMLIT = False


def _ensure_date(obj):
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
    if months <= 0:
        return sourcedate
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def decision_credit(data: Dict[str, Any]) -> str:
    raw_taux = data.get("taux_endettement", 0.0)
    try:
        taux_endettement = float(raw_taux)
    except Exception:
        taux_endettement = 0.0
    if taux_endettement > 1.0:
        taux_endettement = taux_endettement / 100.0

    type_contrat = data.get("type_contrat", "CDI")
    duree_credit_mois = int(data.get("duree_credit_mois", 0))
    if duree_credit_mois > 0:
        date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
        date_fin_credit = add_months(date_debut_credit, duree_credit_mois)
    else:
        date_debut_credit = None
        date_fin_credit = datetime.date.max

    anciennete_compte = int(data.get("anciennete_compte", 999))
    impayes_actuels = bool(data.get("impayes_actuels", False))
    impayes_anciens = bool(data.get("impayes_anciens", False))
    changement_employeur = bool(data.get("changement_employeur", False))
    amelioration_employeur = bool(data.get("amelioration_employeur", False))

    anciennete_employeur = int(data.get("anciennete_employeur", 999))
    employeur_connu = data.get("employeur_connu", "Oui")
    suspicion_employeur = bool(data.get("suspicion_employeur", False))

    if taux_endettement > (1.0 / 3.0):
        return "Refus (rouge) : Endettement trop élevé"

    if type_contrat == "CDD":
        date_fin_cdd = _ensure_date(data.get("date_fin_cdd", None))
        if date_fin_cdd is not None and date_fin_cdd < date_fin_credit:
            return "Refus (rouge) : CDD se termine avant la fin du crédit demandé"

    if anciennete_compte < 3:
        return "Refus (rouge) : Client trop récent"

    if impayes_actuels:
        return "Refus (rouge) : Impayés actuels dans les 6 derniers mois"

    if impayes_anciens:
        if changement_employeur or amelioration_employeur:
            if taux_endettement > 0.25:
                return "Condition (orange) : limiter le taux d'endettement à 25% car impayés anciens"
        else:
            return "Refus (rouge) : Pas de changement chez l'employeur suite anciens impayés"

    if anciennete_employeur < 3:
        return "Refus (rouge) : Ancienneté chez l’employeur < 3 mois"
    if 3 <= anciennete_employeur <= 12:
        if employeur_connu == "Non" or suspicion_employeur:
            return "Risque ORANGE : Employeur non fiable ou suspicion"

    if suspicion_employeur:
        return "Risque ORANGE : Vérification nécessaire sur employeur"

    return "ACCEPTE"


def run_streamlit_app():
    st.set_page_config(page_title="Simulation Crédit", layout="centered")
    st.title("📊 Simulation Octroi Crédit à la Consommation")

    if "step" not in st.session_state:
        st.session_state.step = 1
    if "form_data" not in st.session_state:
        st.session_state.form_data = {}
    if "historique" not in st.session_state:
        st.session_state.historique = []

    if st.session_state.step == 1:
        st.subheader("Étape 1 — Informations de base")
        raw_taux = st.number_input(
            "Taux d'endettement (ex. 0.60 = 60% ou 60)", min_value=0.0, max_value=100.0, step=0.1, value=0.3
        )
        duree_credit_mois = st.number_input("Durée du crédit (mois)", min_value=1, value=12)
        type_contrat = st.selectbox("Type de contrat", ["CDI", "CDD"])
        date_fin_cdd = None
        if type_contrat == "CDD":
            date_fin_cdd = st.date_input("Date fin CDD (si CDD)", value=(datetime.date.today() + datetime.timedelta(days=180)))
        date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
        date_fin_credit = add_months(date_debut_credit, int(duree_credit_mois))
        st.info(f"Date de début crédit : {date_debut_credit} — Date de fin : {date_fin_credit}")
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
            elif "Condition (orange)" in resultat:
                st.warning(resultat)
            else:
                st.session_state.step = 2

    elif st.session_state.step == 2:
        st.subheader("Étape 2 — Compte et historique")
        anciennete_compte = st.number_input("Ancienneté du compte (mois)", min_value=0)
        impayes_actuels = st.checkbox("Impayés actuels (6 derniers mois)")
        impayes_anciens = st.checkbox("Impayés anciens (il y a plus de 6 mois)")
        changement_employeur = False
        amelioration_employeur = False
        if impayes_anciens:
            st.markdown("**Informations complémentaires (car impayés anciens cochés)**")
            ch = st.radio("Changement d’employeur ?", ["Non", "Oui"], index=0)
            am = st.radio("Amélioration de la situation de l’employeur ?", ["Non", "Oui"], index=0)
            changement_employeur = (ch == "Oui")
            amelioration_employeur = (am == "Oui")
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
                elif "Condition (orange)" in resultat:
                    st.warning(resultat)
                elif "ORANGE" in resultat:
                    st.warning(resultat)
                else:
                    st.session_state.step = 3

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
                elif "ORANGE" in resultat or "Condition (orange)" in resultat:
                    st.warning(resultat)
                else:
                    st.success(resultat)
                st.session_state.historique.append({**st.session_state.form_data, "Décision": resultat})
                st.session_state.step = 1

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


if __name__ == "__main__":
    if HAS_STREAMLIT:
        run_streamlit_app()
    else:
        print("Streamlit non installé — tests non exécutés dans cette version simplifiée.")
