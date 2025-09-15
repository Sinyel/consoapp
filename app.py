"""
Credit Decision App — Version avec Étape 0, calcul d’endettement, sliders, et agrégation des alertes

Modifs demandées :
1) **Étape 0 (Identification)** : Numéro client (optionnel, 8 chiffres), Nom & Prénom (obligatoire), Chargé de clientèle (obligatoire, défaut « Ahmed Diop »).
2) **Étape 1** : on ne saisit plus le taux d’endettement ; il est **calculé** à partir de : Revenu mensuel, Charges mensuelles, Montant demandé et Durée (slider). Affichage du taux estimé (pas d’affichage des dates de début/fin).
3) **Durée / Ancienneté** : utilisation de **sliders** pour Durée du crédit, Ancienneté du compte, Ancienneté chez l’employeur.
4) **Historique** : n’est pas affiché automatiquement ; un bouton "Voir l'historique des simulations" l’affiche.
5) **Alertes avant l’étape 3** : si un message **rouge** ou **orange** apparaît, **on continue** le processus. Le message emploie le terme **« Alerte »** (et non « Refus ») avant la décision finale.
6) **Décision finale** :
   - S’il y a ≥1 **alerte rouge** (sur l’ensemble des étapes) ⇒ **Crédit refusé** avec la **liste des motifs rouges**.
   - Sinon, s’il y a ≥1 **alerte orange** ⇒ **Risque de refus** avec la **liste des motifs orange**.
   - Sinon ⇒ **Crédit accepté**.

Remarques :
- Pour le calcul de la mensualité, on utilise une estimation **simplifiée sans intérêts** : `mensualite = montant / duree_mois`.
  Le taux d’endettement estimé = `(charges_mensuelles + mensualite) / revenu_mensuel`.
- La règle CDD (contrat se terminant avant la fin de crédit) s’applique en coulisses (dates non affichées).
"""

import datetime
import calendar
import pandas as pd
from typing import Dict, Any, Tuple, List
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


def calc_endettement_simplifie(revenu_mensuel: float, charges_mensuelles: float, montant_demande: float, duree_mois: int) -> Tuple[float, float]:
    """Retourne (mensualite_estimee, taux_endettement_estime en décimal). Sans intérêts : mensualite = montant/duree."""
    if duree_mois <= 0 or revenu_mensuel <= 0:
        return 0.0, 0.0
    mensualite = max(0.0, float(montant_demande)) / float(duree_mois)
    taux = (max(0.0, float(charges_mensuelles)) + mensualite) / float(revenu_mensuel)
    return mensualite, taux


# ------------------ Règles par étape (retournent des listes d’alertes) ------------------

def eval_step1_alerts(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Retourne (rouges, oranges) détectées à l’étape 1."""
    rouges, oranges = [], []

    # Règle endettement > 1/3 (alerte rouge avant décision finale)
    taux = float(data.get("taux_endettement", 0.0))
    if taux > 1/3:
        rouges.append("Alerte (rouge) : Endettement estimé supérieur à 33%")

    # Règle CDD se terminant avant fin de crédit (alerte rouge)
    if data.get("type_contrat") == "CDD":
        date_fin_cdd = _ensure_date(data.get("date_fin_cdd"))
        date_fin_credit = _ensure_date(data.get("date_fin_credit"))
        if date_fin_cdd and date_fin_credit and date_fin_cdd < date_fin_credit:
            rouges.append("Alerte (rouge) : CDD se termine avant la fin du crédit demandé")

    return rouges, oranges


def eval_step2_alerts(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    rouges, oranges = [], []

    # Ancienneté compte < 3 mois
    anc = int(data.get("anciennete_compte", 999))
    if anc < 3:
        rouges.append("Alerte (rouge) : Ancienneté du compte < 3 mois")

    # Impayés actuels
    if bool(data.get("impayes_actuels", False)):
        rouges.append("Alerte (rouge) : Impayés actuels dans les 6 derniers mois")

    # Impayés anciens
    if bool(data.get("impayes_anciens", False)):
        ch = bool(data.get("changement_employeur", False))
        am = bool(data.get("amelioration_employeur", False))
        taux = float(data.get("taux_endettement", 0.0))
        if ch or am:
            if taux > 0.25:
                oranges.append("Alerte (orange) : Limiter le taux d'endettement à 25% car impayés anciens")
        else:
            rouges.append("Alerte (rouge) : Pas de changement chez l'employeur suite à des impayés anciens")

    return rouges, oranges


def eval_step3_alerts(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    rouges, oranges = [], []

    # Ancienneté employeur < 3 mois
    anc_emp = int(data.get("anciennete_employeur", 999))
    if anc_emp < 3:
        rouges.append("Alerte (rouge) : Ancienneté chez l’employeur < 3 mois")

    statut = data.get("employeur_statut")
    if statut == "Inconnu pour l'instant":
        oranges.append("Alerte (orange) : Se renseigner sur l'état financier de l'employeur pour avis définitif")
    elif isinstance(statut, str) and statut.startswith("🔴"):
        rouges.append("Alerte (rouge) : Employeur connu avec un état financier risqué")
    # 🟢 pas d’alerte

    return rouges, oranges


# ------------------ Décision finale agrégée ------------------

def final_decision_text(rouges: List[str], oranges: List[str]) -> Tuple[str, str]:
    """Retourne (niveau, texte) où niveau ∈ {red, orange, green}."""
    if rouges:
        motifs = "\n".join([f"• {m}" for m in rouges])
        return "red", f"Crédit refusé pour motif(s) suivant(s) :\n{motifs}"
    if oranges:
        motifs = "\n".join([f"• {m}" for m in oranges])
        return "orange", f"Risque de refus de crédit pour motif(s) suivant(s) :\n{motifs}"
    return "green", "Crédit accepté"


# ------------------ Streamlit UI ------------------

def run_streamlit_app():
    st.set_page_config(page_title="Simulation Crédit", layout="centered")
    st.title("📊 Simulation Octroi Crédit à la Consommation")

    # state init
    if "step" not in st.session_state:
        st.session_state.step = 0
    if "form_data" not in st.session_state:
        st.session_state.form_data = {}
    if "historique" not in st.session_state:
        st.session_state.historique = []
    if "alerts_red" not in st.session_state:
        st.session_state.alerts_red = []
    if "alerts_orange" not in st.session_state:
        st.session_state.alerts_orange = []
    if "show_history" not in st.session_state:
        st.session_state.show_history = False

    # ---- Étape 0 : Identification ----
    if st.session_state.step == 0:
        st.subheader("Étape 0 — Identification")
        num_client = st.text_input("Numéro client (8 chiffres, optionnel)")
        nom_prenom = st.text_input("Nom et prénom du client (obligatoire)")
        charge_clientele = st.text_input("Nom et prénom du chargé de clientèle (obligatoire)", value="Ahmed Diop")

        # validations non bloquantes pour le numéro client (optionnel)
        if num_client and (not num_client.isdigit() or len(num_client) != 8):
            st.warning("Le numéro client doit contenir exactement 8 chiffres (ou laisser vide).")

        can_continue = bool(nom_prenom.strip()) and bool(charge_clientele.strip())

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Suivant", disabled=not can_continue):
                st.session_state.form_data.update({
                    "numero_client": num_client.strip(),
                    "nom_prenom_client": nom_prenom.strip(),
                    "charge_clientele": charge_clientele.strip(),
                })
                st.session_state.step = 1
        with col2:
            if st.button("Voir l'historique des simulations"):
                st.session_state.show_history = True

    # ---- Étape 1 : Données financières & calcul endettement ----
    elif st.session_state.step == 1:
        st.subheader("Étape 1 — Données financières")
        revenu = st.number_input("Revenu mensuel (FCFA)", min_value=0.0, value=0.0, step=1000.0)
        charges = st.number_input("Charges mensuelles (crédits, loyer, etc.) (FCFA)", min_value=0.0, value=0.0, step=1000.0)
        montant = st.number_input("Montant du crédit demandé (FCFA)", min_value=0.0, value=0.0, step=1000.0)
        duree_credit_mois = st.slider("Durée du crédit (mois)", min_value=1, max_value=120, value=12)

        mensualite, taux_estime = calc_endettement_simplifie(revenu, charges, montant, duree_credit_mois)
        st.caption(f"Mensualité estimée (sans intérêts) : {mensualite:,.0f} FCFA")
        st.caption(f"Taux d'endettement estimé : {taux_estime*100:.1f}%")

        type_contrat = st.selectbox("Type de contrat", ["CDI", "CDD"])
        date_fin_cdd = None
        if type_contrat == "CDD":
            date_fin_cdd = st.date_input("Date fin CDD (si CDD)", value=(datetime.date.today() + datetime.timedelta(days=180)))

        # calcul dates en coulisses pour la règle CDD
        date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
        date_fin_credit = add_months(date_debut_credit, int(duree_credit_mois))

        if st.button("Suivant"):
            st.session_state.form_data.update({
                "revenu_mensuel": float(revenu),
                "charges_mensuelles": float(charges),
                "montant_demande": float(montant),
                "duree_credit_mois": int(duree_credit_mois),
                "taux_endettement": float(taux_estime),
                "type_contrat": type_contrat,
                "date_fin_cdd": date_fin_cdd,
                "date_debut_credit": date_debut_credit,
                "date_fin_credit": date_fin_credit,
            })
            r, o = eval_step1_alerts(st.session_state.form_data)
            st.session_state.alerts_red.extend(r)
            st.session_state.alerts_orange.extend(o)
            # Affichage des alertes (on continue de toute façon)
            for msg in r:
                st.warning(msg)
            for msg in o:
                st.warning(msg)
            st.session_state.step = 2

        if st.button("⬅ Retour"):
            st.session_state.step = 0

        if st.button("Voir l'historique des simulations"):
            st.session_state.show_history = True

    # ---- Étape 2 : Compte / impayés ----
    elif st.session_state.step == 2:
        st.subheader("Étape 2 — Compte & Historique")
        anciennete_compte = st.slider("Ancienneté du compte (mois)", min_value=0, max_value=240, value=12)
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

        if st.button("Suivant"):
            st.session_state.form_data.update({
                "anciennete_compte": int(anciennete_compte),
                "impayes_actuels": bool(impayes_actuels),
                "impayes_anciens": bool(impayes_anciens),
                "changement_employeur": bool(changement_employeur),
                "amelioration_employeur": bool(amelioration_employeur),
            })
            r, o = eval_step2_alerts(st.session_state.form_data)
            st.session_state.alerts_red.extend(r)
            st.session_state.alerts_orange.extend(o)
            for msg in r + o:
                st.warning(msg)
            st.session_state.step = 3

        if st.button("⬅ Retour"):
            st.session_state.step = 1

        if st.button("Voir l'historique des simulations"):
            st.session_state.show_history = True

    # ---- Étape 3 : Employeur & décision finale ----
    elif st.session_state.step == 3:
        st.subheader("Étape 3 — Informations employeur & décision")
        anciennete_employeur = st.slider("Ancienneté chez l'employeur (mois)", min_value=0, max_value=480, value=24)
        employeur_statut = st.selectbox(
            "L'employeur est-il connu ?",
            ["🟢 Connu - pas d'alerte", "🔴 Connu - Alerte rouge", "Inconnu pour l'instant"],
            index=0,
        )

        if st.button("Décision finale"):
            st.session_state.form_data.update({
                "anciennete_employeur": int(anciennete_employeur),
                "employeur_statut": employeur_statut,
            })
            r3, o3 = eval_step3_alerts(st.session_state.form_data)
            st.session_state.alerts_red.extend(r3)
            st.session_state.alerts_orange.extend(o3)

            # Décision agrégée
            level, text = final_decision_text(list(dict.fromkeys(st.session_state.alerts_red)),
                                              list(dict.fromkeys(st.session_state.alerts_orange)))
            if level == "red":
                st.error(text)
            elif level == "orange":
                st.warning(text)
            else:
                st.success(text)

            # Enregistrer l'historique et reset des alertes pour prochaine simulation
            snapshot = {**st.session_state.form_data}
            snapshot.update({
                "alertes_rouges": list(dict.fromkeys(st.session_state.alerts_red)),
                "alertes_oranges": list(dict.fromkeys(st.session_state.alerts_orange)),
                "decision_finale": text,
            })
            st.session_state.historique.append(snapshot)
            st.session_state.alerts_red = []
            st.session_state.alerts_orange = []
            st.session_state.step = 0

        if st.button("⬅ Retour"):
            st.session_state.step = 2

        if st.button("Voir l'historique des simulations"):
            st.session_state.show_history = True

    # ---- Historique (affichage à la demande) ----
    if st.session_state.show_history and st.session_state.historique:
        df = pd.DataFrame(st.session_state.historique)
        st.subheader("Historique des simulations")
        st.dataframe(df)
        st.download_button("📥 Télécharger l'historique (CSV)", data=df.to_csv(index=False), file_name="historique_credit.csv", mime="text/csv")
        # bouton pour masquer
        if st.button("Masquer l'historique"):
            st.session_state.show_history = False


if __name__ == "__main__":
    if HAS_STREAMLIT:
        run_streamlit_app()
    else:
        print("Streamlit non installé — version UI non exécutée.")
