"""Limites codées en dur. Elles ne se règlent ni dans plan.json, ni dans reglages.json, ni dans
l'interface : les changer demande une modification du code (et donc une relecture)."""
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from poste.execution.modeles import OrdrePropose
from poste.plan import Plan

NEW_YORK = ZoneInfo("America/New_York")

MONTANT_MAX_PAR_ORDRE_EUR = Decimal("500")
ORDRES_MAX_PAR_JOUR = 2
# Créneau : séance de Wall Street sans le premier ni le dernier quart d'heure (prix les plus agités).
# Provisoire : l'annexe B (horaires du plan) n'a pas été fournie.
CRENEAU_NEW_YORK = (time(9, 45), time(15, 45))


@dataclass(frozen=True)
class InstrumentAutorise:
    isin: str
    symbole: str
    place: str      # code de place chez IBKR (à vérifier dans TWS)
    devise: str


# Liste blanche. Les turbos n'y figurent pas : jamais d'envoi de turbo par l'application.
# L'ETF semi-conducteurs et l'ETP bitcoin n'y sont pas encore : leur ISIN n'est pas choisi.
LISTE_BLANCHE: dict[str, InstrumentAutorise] = {
    "NVDA-1": InstrumentAutorise(isin="US67066G1040", symbole="NVDA", place="FWB", devise="EUR"),
}


def dans_le_creneau(quand: datetime) -> bool:
    ny = quand.astimezone(NEW_YORK)
    return ny.weekday() < 5 and CRENEAU_NEW_YORK[0] <= ny.time() <= CRENEAU_NEW_YORK[1]


def verifier(o: OrdrePropose, plan: Plan, maintenant: datetime, ordres_du_jour: int) -> list[str]:
    raisons = []
    try:
        trade = plan.trade(o.trade_id)
    except KeyError:
        return [f"Instrument {o.trade_id} inconnu du plan."]
    if trade.type == "turbo_long":
        raisons.append("Turbo : jamais envoyé par l'application, quel que soit le mode.")
    autorise = LISTE_BLANCHE.get(o.trade_id)
    if autorise is None:
        if trade.type != "turbo_long":
            raisons.append(f"{o.trade_id} n'est pas dans la liste blanche codée en dur.")
    else:
        if o.isin != autorise.isin:
            raisons.append(f"ISIN {o.isin} différent de la liste blanche ({autorise.isin}).")
        if o.devise != autorise.devise:
            raisons.append(f"Devise {o.devise} : seule la devise {autorise.devise} est autorisée.")
    if o.verdict != "FEU VERT":
        raisons.append(f"La fiche dit {o.verdict}, pas FEU VERT (jour interdit ou conditions non remplies).")
    if not isinstance(o.quantite, int) or o.quantite < 1:
        raisons.append("Quantité entière d'au moins 1 obligatoire.")
    if not (Decimal("0") < o.prix_stop < o.prix_limite):
        raisons.append("Le stop doit être positif et sous le prix limite.")
    if o.montant > MONTANT_MAX_PAR_ORDRE_EUR:
        raisons.append(f"Montant {o.montant} € > maximum de {MONTANT_MAX_PAR_ORDRE_EUR} € par ordre.")
    if ordres_du_jour >= ORDRES_MAX_PAR_JOUR:
        raisons.append(f"Déjà {ordres_du_jour} ordre(s) aujourd'hui : maximum {ORDRES_MAX_PAR_JOUR} par jour.")
    if not dans_le_creneau(maintenant):
        raisons.append("Hors du créneau autorisé (9:45-15:45 à New York, du lundi au vendredi).")
    return raisons
