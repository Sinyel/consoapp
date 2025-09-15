"""
Credit Decision App

Correctif important (Étape 1) :
- Le message **« En attente (orange)… »** ne doit apparaître **qu’à l’étape 3** (décision finale sur le statut de l’employeur).
- La fonction `decision_credit` ne produit plus d’orange « en attente » tant que le champ `employeur_statut` n’a pas été saisi.

Mises à jour récentes :
- Étape 1 : durée du crédit (mois) pour calculer date de début (J+15) et date de fin ; refus si CDD se termine avant la fin du crédit.
- Étape 2 : impayés anciens = binaire ; si oui → poser 2 questions (changement/ amélioration). Si au moins une = Oui : exiger taux ≤ 25% sinon **Condition (orange)** qui bloque. Si les deux = Non : **Refus**.
- Étape 3 : « L’employeur est-il connu ? » avec 3 choix (🟢/🔴/Inconnu) menant à la décision finale.
"""

import datetime
import calendar
import pandas as pd
from typing import Dict, Any
import sys
import os

try:
    import streamlit as st  # type: ignore
    HAS_STREAMLIT = True
except Exception:
    HAS_STREAMLIT = False


# ------------------ Helpers ------------------

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


# ------------------ Decision logic ------------------

def decision_credit(data: Dict[str, Any]) -> str:
    """Applique les règles. Tolère des données partielles pour la validation étape par étape."""
    # Taux d'endettement (supporte 0-1 ou 0-100)
    raw_taux = data.get("taux_endettement", 0.0)
    try:
        taux_endettement = float(raw_taux)
    except Exception:
        taux_endettement = 0.0
    if taux_endettement > 1.0:
        taux_endettement = taux_endettement / 100.0

    type_contrat = data.get("type_contrat", "CDI")

    # Crédit: durée et dates (début = today + 15j)
    duree_credit_mois = int(data.get("duree_credit_mois", 0))
    if duree_credit_mois > 0:
        date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
        date_fin_credit = add_months(date_debut_credit, duree_credit_mois)
    else:
        date_debut_credit = None
        date_fin_credit = datetime.date.max

    # Étape 2
    anciennete_compte = int(data.get("anciennete_compte", 999))
    impayes_actuels = bool(data.get("impayes_actuels", False))
    impayes_anciens = bool(data.get("impayes_anciens", False))
    changement_employeur = bool(data.get("changement_employeur", False))
    amelioration_employeur = bool(data.get("amelioration_employeur", False))

    # Étape 3
    anciennete_employeur = int(data.get("anciennete_employeur", 999))
    # ⚠️ Pas de défaut « inconnu » ici pour éviter l’orange prématuré à l’étape 1
    employeur_statut = data.get("employeur_statut", None)  # None si non saisi (avant étape 3)

    # ---- Étape 1 règles ----
    if taux_endettement > (1.0 / 3.0):
        return "Refus (rouge) : Endettement trop élevé"

    if type_contrat == "CDD":
        date_fin_cdd = _ensure_date(data.get("date_fin_cdd", None))
        if date_fin_cdd is not None and date_fin_cdd < date_fin_credit:
            return "Refus (rouge) : CDD se termine avant la fin du crédit demandé"

    # ---- Étape 2 règles ----
    if anciennete_compte < 3:
        return "Refus (rouge) : Client trop récent"

    if impayes_actuels:
        return "Refus (rouge) : Impayés actuels dans les 6 derniers mois"

    if impayes_anciens:
        if changement_employeur or amelioration_employeur:
            if taux_endettement > 0.25:
                return "Condition (orange) : limiter le taux d'endettement à 25% car impayés anciens"
            # sinon on peut continuer
        else:
            return "Refus (rouge) : Pas de changement chez l'employeur suite anciens impayés"

    # ---- Étape 3 règles ----
    if anciennete_employeur < 3:
        return "Refus (rouge) : Ancienneté chez l’employeur < 3 mois"

    # Si l'étape 3 n'est pas encore renseignée, ne pas rendre une décision finale orange/verte ici
    if employeur_statut is None:
        return "ACCEPTE"

    # Décision finale selon le statut employeur
    if employeur_statut == "Inconnu pour l'instant":
        return "En attente (orange) : Se renseigner sur l'état financier de l'employeur pour avis définitif"
    if employeur_statut.startswith("🔴"):
        return "Refus (rouge) : Employeur connu avec un état financier risqué"
    if employeur_statut.startswith("🟢"):
        return "Crédit accepté (vert)"

    return "En attente (orange) : Statut employeur non déterminé"


# ------------------ Streamlit UI ------------------

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
                elif "Condition (orange)" in resultat:
                    st.warning(resultat)
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
                else:
                    st.session_state.step = 3

    # --- Étape 3 ---
    elif st.session_state.step == 3:
        st.subheader("Étape 3 — Informations employeur")
        anciennete_employeur = st.number_input("Ancienneté chez l'employeur (mois)", min_value=0)
        employeur_statut = st.selectbox(
            "L'employeur est-il connu ?",
            [
                "🟢 Connu - pas d'alerte",
                "🔴 Connu - Alerte rouge",
                "Inconnu pour l'instant",
            ],
            index=0,
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("⬅ Retour"):
                st.session_state.step = 2
        with col2:
            if st.button("Décision finale"):
                st.session_state.form_data.update({
                    "anciennete_employeur": int(anciennete_employeur),
                    "employeur_statut": employeur_statut,
                })
                resultat = decision_credit(st.session_state.form_data)
                if "Refus" in resultat:
                    st.error(resultat)
                elif "orange" in resultat.lower():
                    st.warning(resultat)
                elif "accepté" in resultat.lower() or "accept" in resultat.lower():
                    st.success(resultat)
                else:
                    st.info(resultat)
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


if __name__ == "__main__":
    if HAS_STREAMLIT:
        run_streamlit_app()
    else:
        print("Streamlit non installé — tests non exécutés dans cette version simplifiée.")
