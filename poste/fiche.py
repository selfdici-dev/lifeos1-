"""Phase 0 : la fiche d'ordre.

build_order_sheet est une fonction pure : elle ne lit ni réseau ni horloge ni fichier
(le plan lui est passé, ou chargé une fois depuis plan.json). Tous les montants sont
en Decimal pour éviter les erreurs d'arrondi des nombres à virgule flottante.
"""
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from poste.exposition import Exposition, Position, calculer_exposition
from poste.plan import Plan, Trade, charger_plan
from poste.regles import raisons_feu_vert

CENT = Decimal("0.01")
CENT_ = Decimal("100")
A_VERIFIER = "[à vérifier dans ton appli]"
RAPPEL = "Aide à la décision, pas un conseil financier."


class Verdict(str, Enum):
    FEU_VERT = "FEU VERT"
    ATTENDRE = "ATTENDRE"
    INTERDIT = "INTERDIT"


class Saisie(BaseModel):
    """Les prix que tu lis toi-même dans Trade Republic et TradingView."""

    model_config = ConfigDict(frozen=True)

    prix_vendeur_eur: Decimal = Field(gt=0, description="Prix vendeur (ask) affiché dans Trade Republic, en €")
    cours_ref: Decimal = Field(gt=0, description="Cours de référence sur TradingView")
    mm50_ref: Decimal = Field(gt=0, description="Moyenne mobile 50 jours sur TradingView")
    eurusd: Optional[Decimal] = Field(default=None, gt=0, description="Taux EUR/USD (1 € = x $)")
    taux_us10a_pct: Decimal = Field(description="Taux US 10 ans, en %")
    sp500_variation_seance_pct: Decimal = Field(description="Variation du S&P 500 sur la séance, en %")
    evenement_majeur_24h: bool = Field(description="Annonce à impact fort dans les 24 h ?")
    perte_cumulee_eur: Decimal = Field(default=Decimal("0"), ge=0)
    barriere_ref: Optional[Decimal] = Field(default=None, gt=0, description="Barrière du turbo, en points")


@dataclass
class Fiche:
    trade_id: str
    nom: str
    niveau: int
    verdict: Verdict
    raisons: list[str] = field(default_factory=list)
    quantite: Optional[int] = None
    prix_limite_eur: Optional[Decimal] = None
    prix_stop_eur: Optional[Decimal] = None
    objectifs_eur: list[Decimal] = field(default_factory=list)
    perte_max_eur: Optional[Decimal] = None
    perte_au_stop_eur: Optional[Decimal] = None
    gain_vise_eur: Optional[Decimal] = None
    ratio_gain_risque: Optional[Decimal] = None
    montant_engage_eur: Optional[Decimal] = None
    exposition: Optional[Exposition] = None
    conversion: dict = field(default_factory=dict)
    etapes: list[str] = field(default_factory=list)
    si_ca_tourne_mal: list[str] = field(default_factory=list)
    si_ca_marche: list[str] = field(default_factory=list)

    def texte(self) -> str:
        l = [f"=== FICHE D'ORDRE {self.trade_id} : {self.nom} (niveau {self.niveau}) ===",
             f"VERDICT : {self.verdict.value}"]
        l += [f"  - {r}" for r in self.raisons]
        if self.verdict is Verdict.INTERDIT:
            l.append("Aucun ordre aujourd'hui pour ce trade.")
        if self.conversion:
            c = self.conversion
            l.append(f"Conversion (EUR/USD saisi = {c['eurusd']}) : cours ≈ {c['cours_ref_eur']} €,"
                     f" moyenne 50 jours ≈ {c['mm50_ref_eur']} €")
        if self.quantite is not None:
            if self.verdict is Verdict.ATTENDRE:
                l.append("Ne passe pas d'ordre maintenant. Chiffres donnés pour information :")
            l += [
                f"Quantité : {self.quantite} (entière)",
                f"Prix limite : {self.prix_limite_eur} €",
                f"Prix du stop : {self.prix_stop_eur} €",
                "Objectifs : " + " / ".join(f"{o} €" for o in self.objectifs_eur),
                f"Montant engagé : {self.montant_engage_eur} € (frais d'achat inclus)",
                f"PERTE MAXIMALE : {self.perte_max_eur} € (frais inclus)",
            ]
            if self.perte_au_stop_eur != self.perte_max_eur:
                l.append(f"Perte si le stop s'exécute à son prix : {self.perte_au_stop_eur} €")
            l += [
                f"Gain visé si tous les objectifs sont atteints (rien ne le garantit) : {self.gain_vise_eur} €",
                f"Ratio gain/risque (au stop) : {self.ratio_gain_risque}",
            ]
        if self.etapes:
            l.append("ÉTAPES DANS L'APPLI :")
            l += [f"  {i}. {e}" for i, e in enumerate(self.etapes, 1)]
        if self.si_ca_tourne_mal:
            l.append("SI ÇA TOURNE MAL :")
            l += [f"  - {e}" for e in self.si_ca_tourne_mal]
        if self.si_ca_marche:
            l.append("SI ÇA MARCHE :")
            l += [f"  - {e}" for e in self.si_ca_marche]
        if self.exposition is not None:
            if self.quantite is not None:
                l.append("(exposition calculée en comptant ce trade)")
            l.append(self.exposition.texte())
        l.append("Seuils du plan : points de départ non testés.")
        l.append(RAPPEL)
        return "\n".join(l)


@lru_cache(maxsize=1)
def _plan_par_defaut() -> Plan:
    return charger_plan()


def _cent(x: Decimal, mode=ROUND_HALF_UP) -> Decimal:
    return x.quantize(CENT, rounding=mode)


def _entier_inf(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_FLOOR))


def build_order_sheet(trade_id: str, prix_saisis: Saisie, niveau: int, plan: Optional[Plan] = None,
                      positions: Optional[list[Position]] = None) -> Fiche:
    plan = plan or _plan_par_defaut()
    positions = positions or []
    trade = plan.trade(trade_id)
    niv = plan.niveau(niveau)
    s = prix_saisis
    frais = plan.frais_par_ordre_eur
    turbo = trade.type == "turbo_long"

    if trade.devise_ref == "USD" and s.eurusd is None:
        raise ValueError("EUR/USD obligatoire : le cours de référence est en dollars")
    if turbo and s.barriere_ref is None:
        raise ValueError("barrière du turbo obligatoire")

    fiche = Fiche(trade_id=trade.id, nom=trade.nom, niveau=int(niveau), verdict=Verdict.FEU_VERT)
    fiche.conversion = _conversion(trade, s)
    fiche.exposition = calculer_exposition(positions, plan.capital_eur)

    # ---- règles bloquantes -> INTERDIT, aucune fiche émise ----
    interdits = []
    if s.evenement_majeur_24h:
        interdits.append("Annonce majeure dans les 24 h : pas d'achat.")
    interdits += raisons_feu_vert(s.taux_us10a_pct, s.sp500_variation_seance_pct)
    if s.perte_cumulee_eur >= niv.seuil_arret_perte_cumulee_eur:
        interdits.append(f"Perte cumulée {s.perte_cumulee_eur} € ≥ seuil d'arrêt du niveau"
                         f" ({niv.seuil_arret_perte_cumulee_eur} €) : achats arrêtés.")
    if trade.filtre_mm50 and s.cours_ref <= s.mm50_ref:
        interdits.append(f"Condition d'entrée non remplie : cours ({s.cours_ref}) pas au-dessus de la moyenne"
                         f" mobile 50 jours ({s.mm50_ref}).")
    if turbo and s.barriere_ref >= s.cours_ref:
        interdits.append("Barrière au-dessus du cours : ce n'est pas un turbo long valable (ou il est désactivé).")

    if interdits:
        fiche.verdict = Verdict.INTERDIT
        fiche.raisons = interdits
        return fiche

    # ---- calculs ----
    limite = _cent(s.prix_vendeur_eur * (1 + plan.marge_limite_pct / CENT_), ROUND_CEILING)
    stop = _cent(limite * (1 - trade.stop_pct / CENT_), ROUND_FLOOR)
    if stop <= 0 or stop >= limite:
        fiche.verdict = Verdict.INTERDIT
        fiche.raisons = ["Prix trop bas pour poser un stop au centime près."]
        return fiche

    # Turbo : s'il touche la barrière il vaut ~0, donc on risque toute la mise.
    risque_unitaire = limite if turbo else limite - stop
    q_risque = _entier_inf((niv.risque_max_par_trade_eur - 2 * frais) / risque_unitaire)
    q_montant = _entier_inf((niv.montant_max_par_trade_eur - frais) / limite)
    q = min(q_risque, q_montant)
    if q < 1:
        fiche.verdict = Verdict.INTERDIT
        fiche.raisons = [f"Budget du niveau {niveau} trop petit pour 1 titre entier à {limite} €"
                         f" avec ce stop (risque {niv.risque_max_par_trade_eur} € max)."]
        return fiche

    objectifs = [_cent(limite * (1 + p / CENT_)) for p in trade.objectifs_pct]
    ventes = _plan_de_vente(q, objectifs)
    gain = sum(qv * (o - limite) for qv, o in ventes) - frais * (1 + len(ventes))
    perte_au_stop = q * (limite - stop) + 2 * frais
    perte_max = q * risque_unitaire + 2 * frais

    fiche.quantite = q
    fiche.prix_limite_eur = limite
    fiche.prix_stop_eur = stop
    fiche.objectifs_eur = objectifs
    fiche.perte_au_stop_eur = perte_au_stop
    fiche.perte_max_eur = perte_max
    fiche.gain_vise_eur = gain
    fiche.ratio_gain_risque = _cent(gain / perte_au_stop)
    fiche.montant_engage_eur = q * limite + frais
    fiche.exposition = calculer_exposition(positions, plan.capital_eur, ajout=(trade.theme, fiche.montant_engage_eur))

    # ---- conditions d'attente -> ATTENDRE ----
    attendre = []
    if trade.meme_cours_que_ref:
        cours_eur = fiche.conversion.get("cours_ref_eur", s.cours_ref)
        ecart = abs(s.prix_vendeur_eur - cours_eur) / cours_eur * CENT_
        if ecart > plan.tolerance_ecart_prix_pct:
            attendre.append(f"Écart de {_cent(ecart)} % entre le prix Trade Republic ({s.prix_vendeur_eur} €) et"
                            f" TradingView converti ({cours_eur} €) : vérifie l'instrument, le taux EUR/USD et ta saisie.")
    if trade.fourchette_entree_ref:
        bas, haut = trade.fourchette_entree_ref
        if s.cours_ref > haut:
            attendre.append(f"Cours {s.cours_ref} au-dessus de la fourchette d'entrée ({bas}–{haut}) : attends un repli.")
        elif s.cours_ref < bas:
            attendre.append(f"Cours {s.cours_ref} sous la fourchette d'entrée ({bas}–{haut}) : le scénario a changé, attends.")
    if turbo:
        dmin, dmax = trade.barriere_distance_pct
        dist = _cent((s.cours_ref - s.barriere_ref) / s.cours_ref * CENT_)
        if not dmin <= dist <= dmax:
            attendre.append(f"Barrière à {dist} % sous le cours : le plan veut {dmin}–{dmax} %. Choisis un autre turbo.")
    if fiche.ratio_gain_risque < plan.ratio_min_gain_risque:
        attendre.append(f"Ratio gain/risque {fiche.ratio_gain_risque} < {plan.ratio_min_gain_risque} minimum du plan.")

    fiche.si_ca_tourne_mal = _si_mal(trade, q, stop, perte_au_stop, perte_max, s)
    fiche.si_ca_marche = _si_bien(limite, ventes, q)
    if attendre:
        fiche.verdict = Verdict.ATTENDRE
        fiche.raisons = attendre
        return fiche

    fiche.raisons = ["Toutes les règles du plan sont respectées."]
    fiche.etapes = _etapes(trade, plan, q, limite, stop, s)
    return fiche


def _conversion(trade: Trade, s: Saisie) -> dict:
    if trade.devise_ref != "USD":
        return {}
    return {
        "eurusd": s.eurusd,
        "cours_ref_eur": _cent(s.cours_ref / s.eurusd),
        "mm50_ref_eur": _cent(s.mm50_ref / s.eurusd),
    }


def _plan_de_vente(q: int, objectifs: list[Decimal]) -> list[tuple[int, Decimal]]:
    """Moitié au premier objectif, le reste au dernier. Un seul titre : tout au dernier."""
    if len(objectifs) == 1 or q == 1:
        return [(q, objectifs[-1])]
    q1 = q // 2
    return [(q1, objectifs[0]), (q - q1, objectifs[-1])]


def _etapes(trade: Trade, plan: Plan, q: int, limite: Decimal, stop: Decimal, s: Saisie) -> list[str]:
    isin = f" (ISIN {trade.isin})" if trade.isin else ""
    e = [f"Ouvre « {trade.nom} »{isin} dans Trade Republic. {A_VERIFIER}"]
    if trade.type == "turbo_long":
        e.append(f"Dans la fiche du produit, vérifie que c'est un turbo LONG sur le Nasdaq-100 et que sa barrière"
                 f" (knock-out) vaut {s.barriere_ref} points. {A_VERIFIER}")
    e += [
        f"Vérifie le prix vendeur : il doit être proche de {s.prix_vendeur_eur} €. S'il dépasse {limite} €,"
        f" n'achète pas et refais la fiche.",
        f"Appuie sur Acheter et choisis un ordre à cours limité. {A_VERIFIER}",
        f"Quantité : {q} (nombre entier, jamais de fraction).",
        f"Prix limite : {limite} €. Coût maximal : {q * limite} € + {plan.frais_par_ordre_eur} € de frais."
        f" {A_VERIFIER} (frais)",
        f"Validité : jusqu'à la fin de la journée si l'option existe, puis valide l'ordre. {A_VERIFIER}",
        f"Dès que l'achat est exécuté : ordre de vente stop (stop-loss), quantité {q},"
        f" prix de déclenchement {stop} €. {A_VERIFIER}",
        "Note dans ton journal : heure, prix d'exécution réel, stop, objectifs, raison du trade.",
    ]
    return e


def _si_mal(trade: Trade, q: int, stop: Decimal, perte_au_stop: Decimal, perte_max: Decimal, s: Saisie) -> list[str]:
    l = [f"Si le prix tombe à {stop} €, le stop vend tes {q} titres : perte ≈ {perte_au_stop} € frais inclus.",
         "Ne descends JAMAIS le stop pour « laisser une chance ».",
         "Une ouverture en forte baisse (gap) peut faire vendre sous le stop : la perte serait alors plus grande."]
    if trade.type == "turbo_long":
        l.append(f"Si le Nasdaq-100 touche {s.barriere_ref} points, le turbo est désactivé et ne vaut presque"
                 f" plus rien : tu perds {perte_max} € (perte maximale).")
    return l


def _si_bien(limite: Decimal, ventes: list[tuple[int, Decimal]], q: int) -> list[str]:
    l = []
    if len(ventes) == 2:
        (q1, o1), (q2, o2) = ventes
        l.append(f"À {o1} €, vends {q1} titre(s), puis remonte le stop des {q2} restants à {limite} €"
                 f" (ton prix d'achat).")
        l.append(f"À {o2} €, vends les {q2} restants.")
    else:
        (qv, o), = ventes
        l.append(f"À {o} €, vends tes {qv} titre(s).")
    l.append("On ne remonte le stop que vers le haut, jamais vers le bas.")
    l.append("Ces objectifs sont des points de départ non testés, pas une promesse.")
    return l
