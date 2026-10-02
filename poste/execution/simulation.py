"""Registre des ordres envoyés et porte d'accès aux ordres réels.

Ordres réels autorisés seulement si : au moins 20 ordres simulés ET au moins 30 jours de simulation,
le tout sans aucune anomalie (une anomalie remet le compteur à zéro), ET un fichier d'autorisation
écrit par toi contenant exactement la phrase PHRASE_AUTORISATION."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from poste.execution.modeles import OrdrePropose
from poste.regles import FUSEAU

ORDRES_SIMULES_MIN = 20
JOURS_SIMULATION_MIN = 30
PHRASE_AUTORISATION = "J'autorise l'envoi d'ordres réels par l'application, dans les limites codées en dur."


class RegistreSimulation:
    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)
        self.entrees: list[dict] = []
        if self.chemin.exists():
            self.entrees = json.loads(self.chemin.read_text(encoding="utf-8"))

    def noter(self, quand: datetime, ordre: OrdrePropose, etat: str, anomalies: list[str],
              ecarts_fiche: list[str], simulation: bool = True, prix_execution=None,
              quantite_executee: int = 0) -> None:
        self.entrees.append({
            "quand": quand.isoformat(), "simulation": simulation, "trade_id": ordre.trade_id,
            "fiche_id": ordre.fiche_id, "quantite": ordre.quantite, "prix_limite": str(ordre.prix_limite),
            "prix_stop": str(ordre.prix_stop), "etat": etat,
            "prix_execution": None if prix_execution is None else str(prix_execution),
            "quantite_executee": quantite_executee, "anomalies": anomalies, "ecarts_fiche": ecarts_fiche})
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.chemin.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entrees, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.chemin)

    def ordres_du_jour(self, maintenant: datetime) -> int:
        jour = maintenant.astimezone(FUSEAU).date()
        return sum(1 for e in self.entrees if datetime.fromisoformat(e["quand"]).astimezone(FUSEAU).date() == jour)

    def anomalies(self) -> list[dict]:
        return [e for e in self.entrees if e["anomalies"]]


def porte_ordres_reels(registre: RegistreSimulation, maintenant: datetime,
                       chemin_autorisation: Path) -> tuple[bool, list[str]]:
    sim = sorted((e for e in registre.entrees if e["simulation"]), key=lambda e: e["quand"])
    derniere_anomalie: Optional[int] = None
    for i, e in enumerate(sim):
        if e["anomalies"]:
            derniere_anomalie = i
    propres = sim if derniere_anomalie is None else sim[derniere_anomalie + 1:]
    raisons = []
    if len(propres) < ORDRES_SIMULES_MIN:
        raisons.append(f"{len(propres)} ordre(s) simulé(s) sans anomalie : il en faut {ORDRES_SIMULES_MIN}.")
    duree = maintenant - datetime.fromisoformat(propres[0]["quand"]) if propres else timedelta(0)
    if duree < timedelta(days=JOURS_SIMULATION_MIN):
        raisons.append(f"{duree.days} jour(s) de simulation sans anomalie : il en faut au moins"
                       f" {JOURS_SIMULATION_MIN} jours.")
    chemin = Path(chemin_autorisation)
    if not chemin.exists() or chemin.read_text(encoding="utf-8").strip() != PHRASE_AUTORISATION:
        raisons.append(f"Autorisation écrite absente : crée {chemin.name} avec la phrase exacte"
                       f" « {PHRASE_AUTORISATION} ».")
    return (not raisons, raisons)
