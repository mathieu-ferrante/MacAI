"""Classifieur de demandes : plus proches voisins sur des exemples étiquetés, branché dans le routeur et l'agent."""
import pytest

from macai.agent.classifieur import Classifieur, Decision, lire_exemples
from macai.agent.orchestrateur import Orchestrateur
from macai.llm.ollama import Reponse
from macai.outils.base import Registre, Risque, outil

from .conftest import FauxOllama, appel

MOTS = ["mail", "mails", "fichier", "dossier", "phrase", "poeme", "merci", "comment", "chaque", "ouvre", "page",
        "chrome", "range", "facture", "volume"]


class OllamaMots(FauxOllama):
    """Embeddings factices mais « sémantiques » : un axe par mot-clé."""
    def vecteurs(self, modele, textes, dimensions=None):
        import unicodedata
        sortie = []
        for t in textes:
            t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
            v = [float(t.count(m)) for m in MOTS] + [0.01] * ((dimensions or 256) - len(MOTS))
            sortie.append(v)
        return sortie


EXEMPLES = [
    {"texte": "résume mes mails", "intention": "information", "domaines": ["organisation"]},
    {"texte": "lis mes mails non lus", "intention": "information", "domaines": ["organisation"]},
    {"texte": "range le dossier", "intention": "action", "domaines": ["fichiers"]},
    {"texte": "range ce fichier", "intention": "action", "domaines": ["fichiers"]},
    {"texte": "écris une phrase", "intention": "redaction", "domaines": []},
    {"texte": "un poème et une phrase", "intention": "redaction", "domaines": []},
    {"texte": "merci", "intention": "conversation", "domaines": []},
    {"texte": "comment ça marche", "intention": "explication", "domaines": []},
    {"texte": "chaque lundi range le dossier", "intention": "planifier", "domaines": ["taches", "fichiers"]},
    {"texte": "ouvre la page dans chrome", "intention": "action", "domaines": ["web"]},
]


def test_decision_par_voisins(tmp_path):
    c = Classifieur(OllamaMots(), "m", tmp_path / "cache", exemples=[dict(e) for e in EXEMPLES])
    d = c.classer("peux-tu résumer mes mails ?")
    assert d.intention == "information" and d.domaines[0][0] == "organisation" and d.sure()
    assert c.classer("écris-moi une phrase sur la mer").intention == "redaction"
    assert c.classer("ouvre chrome sur cette page").domaines[0][0] == "web"
    # Cache : un second classifieur relit les vecteurs sans recalculer.
    autre = OllamaMots()
    autre.vecteurs_appels = 0
    c2 = Classifieur(autre, "m", tmp_path / "cache", exemples=[dict(e) for e in EXEMPLES])
    c2._preparer()
    assert c2._vecteurs is not None and len(c2._vecteurs) == len(EXEMPLES)


def test_indisponible_ou_vide_renvoie_rien(tmp_path):
    class Panne(FauxOllama):
        def vecteurs(self, *a, **k):
            raise OSError("Ollama arrêté")
    assert Classifieur(Panne(), "m", tmp_path / "c", exemples=[dict(e) for e in EXEMPLES]).classer("x") is None
    assert Classifieur(OllamaMots(), "m", None, exemples=[]).classer("résume mes mails") is None


def test_fichier_d_exemples_valide():
    ex = lire_exemples(jeu=None)
    if not ex:
        pytest.skip("exemples_routage.jsonl absent")
    assert all(e["intention"] and isinstance(e["domaines"], list) for e in ex)
    assert {e.get("jeu", "entrainement") for e in ex} <= {"entrainement", "test"}


class FauxClassifieur:
    def __init__(self, decision):
        self.decision = decision

    def classer(self, demande):
        return self.decision


def _registre():
    r = Registre()

    @outil("ecrire_fichier_texte", "Crée un fichier texte", "fichiers", {"chemin": ("string", "")},
           risque=Risque.CREATION, mac_seulement=False, registre=r)
    def ecrire(ctx, chemin):
        return "écrit"

    @outil("planifier_tache", "Programme une tâche", "taches", {"demande": ("string", "")},
           risque=Risque.SENSIBLE, toujours_confirmer=True, mac_seulement=False, registre=r)
    def planifier(ctx, demande):
        return "programmé"

    @outil("resumer_mails", "Lit les derniers mails", "organisation", {}, mac_seulement=False, registre=r)
    def resumer(ctx):
        return "3 mails"
    return r


def test_redaction_sure_sans_outils(ctx):
    ctx.registre = _registre()
    ctx.services["classifieur"] = FauxClassifieur(Decision("redaction", 0.9))
    ctx.ollama = FauxOllama([Reponse(texte="Un haïku sur la mer.")])
    Orchestrateur(ctx).traiter("un petit haïku sur la mer stp")
    assert ctx.ollama.recus[0]["outils"] in (None, [])
    assert any(e["type"] == "classement" for e in ctx.journal.derniers())


def test_domaines_du_classifieur_passent_devant(ctx):
    ctx.registre = _registre()
    ctx.services["classifieur"] = FauxClassifieur(Decision("information", 0.9, [("organisation", 0.9)]))
    ctx.ollama = FauxOllama([appel("resumer_mails"), Reponse(texte="Rien d'important.")])
    Orchestrateur(ctx).traiter("quoi de neuf dans ma boîte ?")   # aucun mot-clé « mail »
    assert ctx.ollama.recus[0]["outils"][0]["function"]["name"] == "resumer_mails"


def test_classifieur_peu_sur_ne_change_rien(ctx):
    ctx.registre = _registre()
    ctx.services["classifieur"] = FauxClassifieur(Decision("redaction", 0.4))
    ctx.ollama = FauxOllama([Reponse(texte="ok")])
    Orchestrateur(ctx).traiter("écris le fichier ~/notes.txt")
    assert ctx.ollama.recus[0]["outils"]
