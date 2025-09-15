"""
Credit Decision App — Stabilisation navigation (forms + keys)

Correctifs importants :
- **Chaque étape est un `st.form`** pour éviter les reruns qui changent de page lorsque l’on modifie un champ (slider, select, etc.).
- **Boutons avec clés uniques** (`key`) par étape : évite les collisions entre boutons "Suivant"/"Retour" de pages différentes.
- **Navigation uniquement sur submit** : on ne change `step` qu’après clic sur le bouton de soumission du formulaire de l’étape.
- On conserve toutes les personnalisations précédentes (Étape 0, calcul d’endettement, sliders, historique sur bouton, agrégation des alertes, etc.).
"""

import datetime
import calendar
import pandas as pd
from typing import Dict, Any, Tuple, List
import sys
import os
import re

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


def fmt_fcfa(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def parse_fcfa(s: str) -> Tuple[int, bool]:
    """Parse une saisie FCFA (autorise espaces, virgules, points) → entier >= 0; retourne (valeur, ok)."""
    if s is None:
        return 0, False
    cleaned = re.sub(r"[^0-9]", "", s)
    if cleaned == "":
        return 0, False
    try:
        val = int(cleaned)
        if val < 0:
            return 0, False
        return val, True
    except Exception:
        return 0, False


def is_filled(val) -> bool:
    """Considère comme rempli si non-None et non-vide après trim. Compte la valeur par défaut 'Ahmed Diop'."""
    if val is None:
        return False
    if isinstance(val, str):
        return val.strip() != ""
    return True


def calc_endettement_simplifie(revenu_mensuel: int, charges_mensuelles: int, montant_demande: int, duree_mois: int) -> Tuple[float, float]:
    if duree_mois <= 0 or revenu_mensuel <= 0:
        return 0.0, 0.0
    mensualite = float(montant_demande) / float(duree_mois)
    taux = (float(charges_mensuelles) + mensualite) / float(revenu_mensuel)
    return mensualite, taux


# ------------------ Règles par étape (alertes) ------------------

def eval_step1_alerts(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    rouges, oranges = [], []
    taux = float(data.get("taux_endettement", 0.0))
    if taux > 1/3:
        rouges.append("Alerte (rouge) : Endettement estimé supérieur à 33%")
    if data.get("type_contrat") == "CDD":
        date_fin_cdd = _ensure_date(data.get("date_fin_cdd"))
        date_fin_credit = _ensure_date(data.get("date_fin_credit"))
        if date_fin_cdd and date_fin_credit and date_fin_cdd < date_fin_credit:
            rouges.append("Alerte (rouge) : CDD se termine avant la fin du crédit demandé")
    return rouges, oranges


def eval_step2_alerts(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    rouges, oranges = [], []
    anc = int(data.get("anciennete_compte", 999))
    if anc < 3:
        rouges.append("Alerte (rouge) : Ancienneté du compte < 3 mois")
    if bool(data.get("impayes_actuels", False)):
        rouges.append("Alerte (rouge) : Impayés actuels dans les 6 derniers mois")
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
    anc_emp = int(data.get("anciennete_employeur", 999))
    if anc_emp < 3:
        rouges.append("Alerte (rouge) : Ancienneté chez l’employeur < 3 mois")
    statut = data.get("employeur_statut")
    if statut == "Inconnu pour l'instant":
        oranges.append("Alerte (orange) : Se renseigner sur l'état financier de l'employeur pour avis définitif")
    elif isinstance(statut, str) and statut.startswith("🔴"):
        rouges.append("Alerte (rouge) : Employeur connu avec un état financier risqué")
    return rouges, oranges


# ------------------ Décision finale agrégée ------------------

def final_decision_text(rouges: List[str], oranges: List[str]) -> Tuple[str, str]:
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
        with st.form(key="form_step0"):
            st.subheader("Étape 0 — Identification")
            num_client = st.text_input("Numéro client (8 chiffres, optionnel)", key="num_client")
            nom_prenom = st.text_input("Nom et prénom du client (obligatoire)", key="nom_prenom")
            charge_clientele = st.text_input("Nom et prénom du chargé de clientèle (obligatoire)", value="Ahmed Diop", key="charge_clientele")

            if num_client and (not num_client.isdigit() or len(num_client) != 8):
                st.warning("Le numéro client doit contenir exactement 8 chiffres (ou laisser vide).")

            cols = st.columns(2)
            with cols[0]:
                back0 = st.form_submit_button("⬅ Retour", disabled=True, use_container_width=True)
            with cols[1]:
                can_continue = is_filled(nom_prenom) and is_filled(charge_clientele)
                next0 = st.form_submit_button("Suivant", disabled=not can_continue, use_container_width=True)

        # Bouton Historique en bas, espacé
        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        hist0 = st.button("🗂️ Voir l'historique des simulations", key="hist0")
        if hist0:
            st.session_state.show_history = True

        if next0:
            st.session_state.form_data.update({
                "numero_client": num_client.strip(),
                "nom_prenom_client": nom_prenom.strip(),
                "charge_clientele": charge_clientele.strip(),
            })
            st.session_state.step = 1

    # ---- Étape 1 : Données financières & calcul endettement ----
    elif st.session_state.step == 1:
        with st.form(key="form_step1"):
            st.subheader("Étape 1 — Données financières")
            revenu, ok_rev = fcfa_input("Revenu mensuel (FCFA)", "_rev_fcfa", 700_000)
            charges, ok_chg = fcfa_input("Charges mensuelles (crédits, loyer, etc.) (FCFA)", "_chg_fcfa", 250_000)
            montant, ok_mnt = fcfa_input("Montant du crédit demandé (FCFA)", "_mnt_fcfa", 300_000)
            duree_credit_mois = st.slider("Durée du crédit (mois)", min_value=1, max_value=120, value=12, key="dur_step1")

            mensualite, taux_estime = calc_endettement_simplifie(revenu, charges, montant, duree_credit_mois)
            st.caption(f"Mensualité estimée (sans intérêts) : {fmt_fcfa(int(round(mensualite)))} FCFA")
            st.caption(f"Taux d'endettement estimé : {taux_estime*100:.1f}%")

            type_contrat = st.selectbox("Type de contrat", ["CDI", "CDD"], key="contrat_step1")
            date_fin_cdd = None
            if type_contrat == "CDD":
                date_fin_cdd = st.date_input("Date fin CDD (si CDD)", value=(datetime.date.today() + datetime.timedelta(days=180)), key="cdd_fin_step1")

            # Dates en coulisses pour la règle CDD
            date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
            date_fin_credit = add_months(date_debut_credit, int(duree_credit_mois))

            cols = st.columns(2)
            with cols[0]:
                back1 = st.form_submit_button("⬅ Retour", use_container_width=True)
            with cols[1]:
                can_continue = all([ok_rev, ok_chg, ok_mnt]) and revenu > 0 and duree_credit_mois >= 1
                if type_contrat == "CDD" and date_fin_cdd is None:
                    can_continue = False
                next1 = st.form_submit_button("Suivant", disabled=not can_continue, use_container_width=True)

        # Bouton Historique en bas, espacé
        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        hist1 = st.button("🗂️ Voir l'historique des simulations", key="hist1")
        if hist1:
            st.session_state.show_history = True

        if back1:
            st.session_state.step = 0
        if next1:
            st.session_state.form_data.update({
                "revenu_mensuel": int(revenu),
                "charges_mensuelles": int(charges),
                "montant_demande": int(montant),
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
            for msg in r + o:
                st.warning(msg)
            st.session_state.step = 2

    # ---- Étape 2 : Compte / impayés ----
    elif st.session_state.step == 2:
        with st.form(key="form_step2"):
            st.subheader("Étape 2 — Compte & Historique")
            anciennete_compte = st.slider("Ancienneté du compte (mois)", min_value=0, max_value=240, value=12, key="anc_compte")
            impayes_actuels = st.checkbox("Impayés actuels (6 derniers mois)", key="imp_actuels")
            impayes_anciens = st.checkbox("Impayés anciens (il y a plus de 6 mois)", key="imp_anciens")

            changement_employeur = False
            amelioration_employeur = False
            if impayes_anciens:
                st.markdown("**Informations complémentaires (car impayés anciens cochés)**")
                ch = st.radio("Changement d’employeur ?", ["Non", "Oui"], index=0, key="chg_emp")
                am = st.radio("Amélioration de la situation de l’employeur ?", ["Non", "Oui"], index=0, key="am_emp")
                changement_employeur = (ch == "Oui")
                amelioration_employeur = (am == "Oui")

            cols = st.columns(2)
            with cols[0]:
                back2 = st.form_submit_button("⬅ Retour", use_container_width=True)
            with cols[1]:
                next2 = st.form_submit_button("Suivant", use_container_width=True)

        # Bouton Historique en bas, espacé
        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        hist2 = st.button("🗂️ Voir l'historique des simulations", key="hist2")
        if hist2:
            st.session_state.show_history = True

        if back2:
            st.session_state.step = 1
        if next2:
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

    # ---- Étape 3 : Employeur & décision finale ----
    elif st.session_state.step == 3:
        with st.form(key="form_step3"):
            st.subheader("Étape 3 — Informations employeur & décision")
            anciennete_employeur = st.slider("Ancienneté chez l'employeur (mois)", min_value=0, max_value=480, value=24, key="anc_emp")
            employeur_statut = st.selectbox(
                "L'employeur est-il connu ?",
                ["🟢 Connu - pas d'alerte", "🔴 Connu - Alerte rouge", "Inconnu pour l'instant"],
                index=0,
                key="emp_statut",
            )

            cols = st.columns(2)
            with cols[0]:
                back3 = st.form_submit_button("⬅ Retour", use_container_width=True)
            with cols[1]:
                decide = st.form_submit_button("Décision finale", use_container_width=True)

        # Bouton Historique en bas, espacé
        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        hist3 = st.button("🗂️ Voir l'historique des simulations", key="hist3")
        if hist3:
            st.session_state.show_history = True

        if back3:
            st.session_state.step = 2
        if decide:
            st.session_state.form_data.update({
                "anciennete_employeur": int(anciennete_employeur),
                "employeur_statut": employeur_statut,
            })
            r3, o3 = eval_step3_alerts(st.session_state.form_data)
            st.session_state.alerts_red.extend(r3)
            st.session_state.alerts_orange.extend(o3)

            reds = list(dict.fromkeys(st.session_state.alerts_red))
            oranges = list(dict.fromkeys(st.session_state.alerts_orange))
            level, text = final_decision_text(reds, oranges)
            if level == "red":
                st.error(text)
            elif level == "orange":
                st.warning(text)
            else:
                st.success(text)

            snapshot = {**st.session_state.form_data}
            snapshot.update({
                "alertes_rouges": reds,
                "alertes_oranges": oranges,
                "decision_finale": text,
            })
            st.session_state.historique.append(snapshot)
            st.session_state.alerts_red = []
            st.session_state.alerts_orange = []
            st.session_state.step = 0

    # ---- Historique (affichage à la demande) ----
    if st.session_state.show_history and st.session_state.historique:
        df = pd.DataFrame(st.session_state.historique)
        st.subheader("Historique des simulations")
        st.dataframe(df)
        st.download_button("📥 Télécharger l'historique (CSV)", data=df.to_csv(index=False), file_name="historique_credit.csv", mime="text/csv")
        if st.button("Masquer l'historique", key="hide_hist"):
            st.session_state.show_history = False


if __name__ == "__main__":
    if HAS_STREAMLIT:
        run_streamlit_app()
    else:
        print("Streamlit non installé — version UI non exécutée.")
