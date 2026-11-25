"""Commandes directes : reconnues par motifs, exécutées sans modèle (instantané, 0 Mo de RAM en plus).

Seules les formulations sans ambiguïté sont reconnues ; tout le reste part vers l'agent.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from .consignes import JOURS, MOIS

SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "google": "https://www.google.com",
    "netflix": "https://www.netflix.com", "onshape": "https://cad.onshape.com", "wikipedia": "https://fr.wikipedia.org",
    "google maps": "https://maps.google.com", "maps": "https://maps.google.com", "google drive": "https://drive.google.com",
    "twitch": "https://www.twitch.tv", "github": "https://github.com", "amazon": "https://www.amazon.fr",
    "leboncoin": "https://www.leboncoin.fr", "deezer": "https://www.deezer.com",
}
NE_PAS_INTERCEPTER = re.compile(r"\b(fichier|dossier|document|pdf|photo|image|et (fais|cree|ecris|clique|resume|dis))")
# Le « nom » cache une suite d'actions (« Safari puis cherche… », « Notes, crée… ») ou désigne autre chose
# qu'une appli (« un nouvel onglet », « mes mails », « le dernier fichier ») : c'est pour l'agent.
NOM_COMPLEXE = re.compile(r"\b(puis|ensuite|et)\b|[,;]|:(?!//)")
# « Annule » seul (ou presque) : la dernière action sur les fichiers. « Annule mon rendez-vous » part vers l'agent.
ANNULER = (r"^(?:peux-tu |tu peux )?(?:annule|annuler|annule ca|annule cela|annule-la|annule la derniere action|"
           r"annule ma derniere action|annule ce que tu viens de faire|annule la derniere chose|defais ca|defais|"
           r"reviens en arriere|retour en arriere|fais marche arriere|(?:ctrl|cmd|commande)[ +-]?z|undo)"
           r"(?: stp| s'il te plait)?$")
RESUME_MATIN = "résume mes mails non lus et mon agenda du jour"
NOM_NON_APPLI = re.compile(r"^(tout|toutes|mes|ma|mon|un|une|le dernier|la derniere|nouvel|nouveau|nouvelle|"
                           r"l['’]onglet|onglet)\b")


@dataclass
class Plan:
    actions: list[tuple[str, dict]] = field(default_factory=list)
    reponse: str = ""
    tolerant: bool = False  # plusieurs actions indépendantes : un échec n'arrête pas les autres


def _calcul(original: str) -> Plan | None:
    """« Combien font 5000-964 », « 12 fois 7 », « 20 % de 150 » : calculé exactement, sans modèle."""
    from ..calcul import CalculImpossible, calculer, en_francais, expression
    if expression(original) is None:
        return None
    try:
        return Plan([], f"{en_francais(calculer(original))}")
    except CalculImpossible as e:
        return Plan([], f"Calcul impossible : {e}.")
    except (OverflowError, ValueError):
        return None


def _norm(texte: str) -> str:
    """Minuscules sans accents, MÊME longueur que l'original (pour extraire les noms avec leur casse)."""
    return "".join(unicodedata.normalize("NFD", c)[0].lower() if c.strip() else " " for c in texte)


def _nom_simple(nom: str) -> bool:
    nom = nom.strip()
    return bool(nom) and not NOM_COMPLEXE.search(nom) and not NOM_NON_APPLI.match(nom)


def _nettoyer(nom: str) -> str:
    nom = re.sub(r"^(l'|le |la |les |l’|un |une |des |du |de |d')", "", nom.strip(), flags=re.I)
    nom = re.sub(r"^(application|appli|app|logiciel|site)\s+", "", nom, flags=re.I)
    return nom.strip(" .!?,;\"'«»")


class CommandesRapides:
    def __init__(self):
        P = re.compile
        demande = r"(?:peux-tu |tu peux |stp |s'il te plait )?"
        self.motifs = [
            (P(ANNULER), lambda m, t: Plan([("annuler_derniere_action", {})])),
            # Réglages Système sur une rubrique : « ouvre les réglages Bluetooth », « va dans les réglages du son ».
            (P(rf"^{demande}(?:ouvre|va dans|affiche|montre)(?: moi)? (?:les |le )?(?:reglages|parametres|preferences)"
               r"(?: systeme)?(?: de la| du| des| de l'| d'| sur la| sur le| sur| rubrique| section| :)? (?P<r>[a-z0-9' -]{2,30})$"),
             lambda m, t: Plan([("ouvrir_reglage", {"rubrique": m.group("r").strip()})])),
            # Question à Claude : un seul outil déterministe (le modèle se perdait dans l'interface).
            (P(rf"^{demande}(?:ouvre claude(?: en mode chat)?(?:,| et)? )?(?:demande|pose|ecris|dis)(?:-lui|-le)?"
               r"(?: a claude| a l'app claude)?(?: la question)?(?: de| si| :|,)? (?P<q>.{4,})$"),
             self._claude),
            (P(rf"^{demande}(?:fais|fait|prepare|donne)[- ]moi (?:un|le) (?:resume|point|briefing)"
               r"(?: de (?:ma|la) journee| du jour| du matin)? (?:chaque matin|tous les matins)"
               r"(?: (?:a|vers) (?P<h>\d{1,2}) ?(?:h|:|heures?)? ?(?P<mn>\d{2})?)?$"), self._resume_matin),
            # « Tous les matins à 8h, fais-moi un résumé… », « chaque lundi à 9h, range mes téléchargements » :
            # programmé à coup sûr (le modèle faisait parfois le résumé tout de suite au lieu de le programmer).
            # Toujours confirmé, avec la demande complète.
            (P(r"^(?P<freq>tous les (?:jours|matins|soirs)|chaque (?:jour|matin|soir|semaine|lundi|mardi|mercredi|"
               r"jeudi|vendredi|samedi|dimanche)|tous les (?:lundis|mardis|mercredis|jeudis|vendredis|samedis|"
               r"dimanches)|toutes les heures|en semaine|du lundi au vendredi)"
               r"(?: (?:a|vers|des) (?P<h>\d{1,2}) ?(?:h|:|heures?)? ?(?P<mn>\d{2})?)?\s*[,:]?\s+(?P<q>.{6,})$"),
             self._planifier),
            (P(rf"^{demande}(?:lance|ouvre|va sur) youtube et (?:cherche|recherche|trouve)(?: moi)? (?:une |des )?(?:videos? (?:de |sur |d')?)?(?P<q>.+)$"),
             self._youtube_chercher),
            (P(rf"^{demande}(?:mets|joue|lance|regarde)(?: moi)? (?:la |une )?(?:video|musique|chanson|clip)? ?(?:de |d')?(?P<q>.+?) sur youtube$"),
             self._youtube_lire),
            (P(rf"^{demande}(?:cherche|recherche)(?: moi)? (?P<q>.+?) sur (?P<site>google|youtube)$"), self._chercher_sur),
            (P(rf"^{demande}(?:ouvre|lance|demarre)(?: moi)? (?P<nom>.+)$"), self._ouvrir),
            # « Ferme tout sauf Claude », « quitte toutes mes applis » : un seul outil, confirmé avec la liste.
            (P(rf"^{demande}(?:ferme|quitte)(?: moi)? (?:tout|toutes? (?:les |mes )?(?:applis|applications|"
               r"logiciels|programmes|fenetres)(?: ouvertes| lancees)?)(?: sauf (?P<sauf>.+))?$"),
             lambda m, t: Plan([("fermer_applications", {"sauf": self._extrait(m, t, "sauf") if m.group("sauf")
                                                          else ""})])),
            (P(rf"^{demande}(?:ferme|quitte)(?: moi)? (?P<noms>[^,]+(?:,[^,]+)*,? et [^,]+|[^,]+(?:,[^,]+)+)$"),
             self._quitter_plusieurs),
            (P(rf"^{demande}(?:ferme|quitte)(?: moi)? (?P<nom>.+)$"), self._quitter),
            (P(rf"^{demande}(?:coupe|desactive|eteins|eteint|arrete|deconnecte)(?: moi)? (?:le )?wi-?fi$"),
             lambda m, t: Plan([("regler_wifi", {"actif": False})])),
            (P(rf"^{demande}(?:active|allume|remets|rallume|reactive|reconnecte)(?: moi)? (?:le )?wi-?fi$"),
             lambda m, t: Plan([("regler_wifi", {"actif": True})])),
            (P(rf"^{demande}(?:active|passe en|mets(?: le)?|bascule en) (?:le )?mode (?:sombre|nuit|dark)$"),
             lambda m, t: Plan([("mode_sombre", {"actif": True})])),
            (P(rf"^{demande}(?:desactive|enleve|quitte|passe en|mets(?: le)?|bascule en) (?:le )?mode "
               r"(?:sombre|nuit|dark|clair)$"),
             lambda m, t: Plan([("mode_sombre", {"actif": "clair" in m.group(0)})])),
            (P(r"^(?:mets |regle |monte |baisse )?(?:le )?(?:volume|son) (?:a |au )?(?P<n>\d{1,3}) ?%?$"), self._volume),
            (P(r"^(?:monte|augmente) (?:le )?(?:son|volume)$"), lambda m, t: self._media("volume_plus")),
            (P(r"^(?:baisse|diminue) (?:le )?(?:son|volume)$"), lambda m, t: self._media("volume_moins")),
            (P(r"^(?:coupe le son|mute|silence|mets en sourdine)$"), lambda m, t: self._media("muet")),
            (P(r"^(?:pause|mets (?:en )?pause|stop la musique)$"), lambda m, t: self._media("pause")),
            (P(r"^(?:reprends|reprend|lecture|play|remets la musique)$"), lambda m, t: self._media("lecture")),
            (P(r"^(?:suivant|chanson suivante|musique suivante|next)$"), lambda m, t: self._media("suivant")),
            (P(r"^(?:precedent|chanson precedente|musique precedente)$"), lambda m, t: self._media("precedent")),
            (P(r"^(?:prends une |fais une )?capture d'ecran$"), lambda m, t: Plan([("capture_ecran", {})])),
            (P(r"^(?:quelle heure (?:est-il|il est)|il est quelle heure)$"), self._heure),
            (P(r"^(?:quel jour (?:sommes-nous|on est|est-on|est-ce)|on est quel jour|quelle est la date(?: d'aujourd'hui)?"
               r"|quelle date (?:sommes-nous|on est|est-on|est-ce|aujourd'hui)|on est le combien|c'est quoi la date)$"), self._date),
            (P(r"^(?:(?:etat de la |niveau de )?batterie|(?:combien de|quel niveau de) batterie(?: il me reste| reste-t-il)?"
               r"|(?:quel est )?l'?espace disque(?: libre)?|infos? systeme)$"), lambda m, t: Plan([("infos_systeme", {})])),
            (P(r"^(?:etat de la )?(?:memoire|ram)(?: du mac)?|pourquoi (?:le|mon) mac (?:rame|est lent)$"),
             lambda m, t: Plan([("etat_memoire", {})])),
        ]

    def reconnaitre(self, demande: str, registre=None) -> Plan | None:
        original = demande.strip().rstrip(" ?!.")
        calcul = _calcul(original)
        if calcul is not None:
            return calcul
        t = _norm(original)
        t_court = re.sub(r"\s+", " ", t)
        if t_court != t:  # espaces multiples : on repart d'un original compacté
            original = re.sub(r"\s+", " ", original)
            t = t_court
        for motif, action in self.motifs:
            m = motif.match(t)
            if m:
                plan = action(m, original)
                if plan is None:
                    continue
                if registre is not None and any(registre.get(n) is None for n, _ in plan.actions):
                    return None  # outil indisponible sur cette plateforme : laisser l'agent gérer
                return plan
        return None

    # --- Actions ------------------------------------------------------------

    @staticmethod
    def _extrait(m, original, groupe):
        return original[m.start(groupe):m.end(groupe)]

    def _youtube_chercher(self, m, original):
        q = _nettoyer(self._extrait(m, original, "q"))
        return Plan([("chrome_rechercher", {"requete": q, "site": "youtube"})], "Recherche YouTube ouverte : {0}")

    def _youtube_lire(self, m, original):
        q = _nettoyer(self._extrait(m, original, "q"))
        return Plan([("youtube_lire", {"requete": q})])

    def _chercher_sur(self, m, original):
        q = _nettoyer(self._extrait(m, original, "q"))
        return Plan([("chrome_rechercher", {"requete": q, "site": m.group("site")})])

    def _claude(self, m, original):
        if "claude" not in m.group(0):
            return None
        q = self._extrait(m, original, "q").strip(" :,")
        q = re.sub(r"^(a|à) claude\s*(de|si|:)?\s*", "", q, flags=re.I).strip()
        return Plan([("demander_a_claude", {"question": q[:1].upper() + q[1:]})]) if len(q) > 3 else None

    def _ouvrir(self, m, original):
        if NE_PAS_INTERCEPTER.search(m.group(0)) or not _nom_simple(m.group("nom")):
            return None
        nom = _nettoyer(self._extrait(m, original, "nom"))
        if not nom or len(nom.split()) > 4:
            return None
        cle = _norm(nom)
        if cle in SITES:
            return Plan([("ouvrir_url", {"url": SITES[cle]})], f"{nom} est ouvert.")
        if re.match(r"^(https?://|www\.)|^[a-z0-9-]+\.(com|fr|org|net|io|dev|tv)$", cle):
            return Plan([("ouvrir_url", {"url": nom if nom.startswith("http") else "https://" + nom})])
        return Plan([("ouvrir_application", {"nom": nom})])

    def _quitter_plusieurs(self, m, original):
        """« Ferme Chrome, Finder et Claude » : chaque nom doit être une appli installée, sinon l'agent s'en charge."""
        if NE_PAS_INTERCEPTER.search(m.group(0)):
            return None
        brut = self._extrait(m, original, "noms")
        noms = [_nettoyer(n) for n in re.split(r",|\bet\b", brut, flags=re.I) if _nettoyer(n)]
        if len(noms) < 2 or len(noms) > 8 or any(len(n.split()) > 4 for n in noms):
            return None
        try:
            from ..outils.applications import trouver_application
            if any(trouver_application(n) is None for n in noms):
                return None
        except Exception:  # noqa: BLE001 - hors Mac : on laisse l'agent
            return None
        return Plan([("quitter_application", {"nom": n}) for n in noms], tolerant=True)

    def _quitter(self, m, original):
        if NE_PAS_INTERCEPTER.search(m.group(0)) or not _nom_simple(m.group("nom")):
            return None
        nom = _nettoyer(self._extrait(m, original, "nom"))
        if not nom or len(nom.split()) > 4 or _norm(nom) in ("tout", "toutes les applis", "tout le monde"):
            return None
        return Plan([("quitter_application", {"nom": nom})])

    @staticmethod
    def _resume_matin(m, original):
        h = int(m.group("h") or 8)
        mn = int(m.group("mn") or 0)
        if h > 23 or mn > 59:
            return None
        return Plan([("planifier_tache", {"demande": RESUME_MATIN, "frequence": "quotidien",
                                          "heure": f"{h:02d}:{mn:02d}"})])

    def _planifier(self, m, original):
        freq = m.group("freq")
        jour = ""
        if "heures" in freq:
            frequence = "horaire"
        elif "semaine" in freq and "chaque" not in freq or "lundi au vendredi" in freq:
            frequence = "jours_ouvres"
        elif any(j in freq for j in ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")) \
                or "chaque semaine" in freq:
            frequence = "hebdomadaire"
            jour = next((j for j in ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
                         if j in freq), "lundi")
        else:
            frequence = "quotidien"
        h = int(m.group("h")) if m.group("h") else (19 if "soir" in freq else 8)
        mn = int(m.group("mn") or 0)
        if h > 23 or mn > 59:
            return None
        q = self._extrait(m, original, "q").strip(" ,.")
        if re.match(r"(?i)(je|j'|j’|on|nous|il|elle|ils|elles|tu|c'est|ca|ça|mon|ma|mes|le|la|les)\b", q):
            return None  # « tous les jours je bois du café » : un constat, pas une tâche
        args = {"demande": q[:1].upper() + q[1:], "frequence": frequence, "heure": f"{h:02d}:{mn:02d}"}
        if jour:
            args["jour"] = jour
        return Plan([("planifier_tache", args)])

    def _volume(self, m, original):
        return Plan([("regler_volume", {"niveau": min(int(m.group("n")), 100)})])

    @staticmethod
    def _media(action):
        return Plan([("controle_media", {"action": action})])

    @staticmethod
    def _heure(m, original):
        return Plan([], f"Il est {datetime.now():%H:%M}.")

    @staticmethod
    def _date(m, original):
        d = datetime.now()
        return Plan([], f"Nous sommes le {JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}.")
