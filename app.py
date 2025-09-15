"""
Credit Decision App — Rebase propre avec Étape 0, calcul d’endettement, alertes agrégées, sliders, et historique à la demande

Ce fichier repart de ta base et réintègre les exigences validées :
- Étape 0 (Identification) : Numéro client (optionnel, 8 chiffres), Nom & prénom (obligatoire), Chargé de clientèle (obligatoire, défaut « Ahmed Diop »).
- Étape 1 : Saisie Revenu/Charges/Montant (FCFA formatés) + Durée (slider). Calcul du taux d’endettement (sans intérêts : montant/durée). **Pas d’affichage des dates**. Type de contrat (CDI/CDD) + Date fin CDD si CDD.
- Étape 2 : Impayés actuels/anciens (anciens → radios Oui/Non pour changement/amélioration).
- Étape 3 : « L’employeur est-il connu ? » (🟢/🔴/Inconnu) + ancienneté employeur (slider).
- Avant l’étape 3, les **alertes** (rouge/orange) **n’arrêtent pas** le process, elles sont **agrégées**.
- Décision finale :
  • ≥1 rouge → « Crédit refusé… » + liste des rouges
  • sinon ≥1 orange → « Risque de refus… » + liste des oranges
  • sinon → « Crédit accepté »
- Bouton **🗂️ Voir l'historique des simulations** en bas de chaque page, espacé.
- Navigation stable sans `st.form`, clés uniques par étape (`s0_*`, `s1_*`, ...).
"""

import datetime
import calendar
import pandas as pd
from typing import Dict, Any, Tuple, List
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


def fcfa_input(label: str, key: str, default_value: int) -> Tuple[int, bool]:
    default_str = fmt_fcfa(default_value)
    s = st.text_input(label, value=st.session_state.get(key, default_str), key=key)
    val, ok = parse_fcfa(s)
    if not ok:
        st.warning(f"Entrée invalide pour {label}. Utilisez uniquement des chiffres, ex. {default_str}")
    return val, ok


def is_filled(val) -> bool:
    return (val is not None) and (str(val).strip() != "")


def calc_endettement_simplifie(revenu_mensuel: int, charges_mensuelles: int, montant_demande: int, duree_mois: int) -> Tuple[float, float]:
    """Retourne (mensualite_estimee, taux_endettement_estime en décimal). Sans intérêts : mensualite = montant/duree."""
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

    # State init
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

    # =========================
    # Étape 0 — Identification
    # =========================
    if st.session_state.step == 0:
        st.subheader("Étape 0 — Identification")
        num_client = st.text_input("Numéro client (8 chiffres, optionnel)", key="s0_num_client")
        nom_prenom = st.text_input("Nom et prénom du client (obligatoire)", key="s0_nom_prenom")
        charge_clientele = st.text_input(
            "Nom et prénom du chargé de clientèle (obligatoire)", value="Ahmed Diop", key="s0_charge_clientele"
        )

        if num_client and (not num_client.isdigit() or len(num_client) != 8):
            st.warning("Le numéro client doit contenir exactement 8 chiffres (ou laisser vide).")

        col_a, col_b = st.columns(2)
        with col_a:
            st.button("⬅ Retour", key="s0_back", disabled=True, use_container_width=True)
        with col_b:
            next0 = st.button("Suivant", key="s0_next", use_container_width=True)

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        if st.button("🗂️ Voir l'historique des simulations", key="hist_step0"):
            st.session_state.show_history = True

        if next0:
            if not is_filled(nom_prenom) or not is_filled(charge_clientele):
                st.error("Merci de renseigner le nom du client et le chargé de clientèle avant de continuer.")
            else:
                st.session_state.form_data.update({
                    "numero_client": (num_client or "").strip(),
                    "nom_prenom_client": nom_prenom.strip(),
                    "charge_clientele": charge_clientele.strip(),
                })
                st.session_state.step = 1

    # ======================================
    # Étape 1 — Données financières (calc TE)
    # ======================================
    elif st.session_state.step == 1:
        st.subheader("Étape 1 — Données financières")
        revenu, ok_rev = fcfa_input("Revenu mensuel (FCFA)", "s1_rev_fcfa", 700_000)
        charges, ok_chg = fcfa_input("Charges mensuelles (crédits, loyer, etc.) (FCFA)", "s1_chg_fcfa", 250_000)
        montant, ok_mnt = fcfa_input("Montant du crédit demandé (FCFA)", "s1_mnt_fcfa", 300_000)
        duree_credit_mois = st.slider("Durée du crédit (mois)", min_value=1, max_value=120, value=12, key="s1_duree")

        mensualite, taux_estime = calc_endettement_simplifie(revenu, charges, montant, duree_credit_mois)
        st.caption(f"Mensualité estimée (sans intérêts) : {fmt_fcfa(int(round(mensualite)))} FCFA")
        st.caption(f"Taux d'endettement estimé : {taux_estime*100:.1f}%")

        type_contrat = st.selectbox("Type de contrat", ["CDI", "CDD"], key="s1_contrat")
        date_fin_cdd = None
        if type_contrat == "CDD":
            date_fin_cdd = st.date_input(
                "Date fin CDD (si CDD)", value=(datetime.date.today() + datetime.timedelta(days=180)), key="s1_cdd_fin"
            )

        # Dates calculées en coulisses pour la règle CDD
        date_debut_credit = datetime.date.today() + datetime.timedelta(days=15)
        date_fin_credit = add_months(date_debut_credit, int(duree_credit_mois))

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("⬅ Retour", key="s1_back", use_container_width=True):
                st.session_state.step = 0
        with col_b:
            if st.button("Suivant", key="s1_next", use_container_width=True):
                valid = all([ok_rev, ok_chg, ok_mnt]) and revenu > 0 and duree_credit_mois >= 1
                if type_contrat == "CDD" and date_fin_cdd is None:
                    valid = False
                if not valid:
                    st.error("Merci de renseigner correctement tous les champs de l'étape 1 avant de continuer.")
                else:
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

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        if st.button("🗂️ Voir l'historique des simulations", key="hist_step1"):
            st.session_state.show_history = True

    # ==================================
    # Étape 2 — Compte & Historique
    # ==================================
    elif st.session_state.step == 2:
        st.subheader("Étape 2 — Compte & Historique")
        anciennete_compte = st.slider("Ancienneté du compte (mois)", min_value=0, max_value=240, value=12, key="s2_anc_compte")
        impayes_actuels = st.checkbox("Impayés actuels (6 derniers mois)", key="s2_imp_actuels")
        impayes_anciens = st.checkbox("Impayés anciens (il y a plus de 6 mois)", key="s2_imp_anciens")

        changement_employeur = False
        amelioration_employeur = False
        if impayes_anciens:
            st.markdown("**Informations complémentaires (car impayés anciens cochés)**")
            ch = st.radio("Changement d’employeur ?", ["Non", "Oui"], index=0, key="s2_chg_emp")
            am = st.radio("Amélioration de la situation de l’employeur ?", ["Non", "Oui"], index=0, key="s2_am_emp")
            changement_employeur = (ch == "Oui")
            amelioration_employeur = (am == "Oui")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("⬅ Retour", key="s2_back", use_container_width=True):
                st.session_state.step = 1
        with col_b:
            if st.button("Suivant", key="s2_next", use_container_width=True):
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

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        if st.button("🗂️ Voir l'historique des simulations", key="hist_step2"):
            st.session_state.show_history = True

    # ==================================
    # Étape 3 — Employeur & décision
    # ==================================
    elif st.session_state.step == 3:
        st.subheader("Étape 3 — Informations employeur & décision")
        anciennete_employeur = st.slider("Ancienneté chez l'employeur (mois)", min_value=0, max_value=480, value=24, key="s3_anc_emp")
        employeur_statut = st.selectbox(
            "L'employeur est-il connu ?",
            ["🟢 Connu - pas d'alerte", "🔴 Connu - Alerte rouge", "Inconnu pour l'instant"],
            index=0,
            key="s3_emp_statut",
        )

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("⬅ Retour", key="s3_back", use_container_width=True):
                st.session_state.step = 2
        with col_b:
            if st.button("Décision finale", key="s3_decide", use_container_width=True):
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

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        if st.button("🗂️ Voir l'historique des simulations", key="hist_step3"):
            st.session_state.show_history = True

    # ==============================
    # Historique (à la demande)
    # ==============================
    if st.session_state.show_history and st.session_state.historique:
        df = pd.DataFrame(st.session_state.historique)
        st.subheader("Historique des simulations")
        st.dataframe(df)
        st.download_button(
            "📥 Télécharger l'historique (CSV)", data=df.to_csv(index=False), file_name="historique_credit.csv", mime="text/csv"
        )
        if st.button("Masquer l'historique", key="hist_hide"):
            st.session_state.show_history = False


if __name__ == "__main__":
    if HAS_STREAMLIT:
        run_streamlit_app()
    else:
        print("Streamlit non installé — version UI non exécutée.")
