"""Pannes relevées dans le journal réel du Mac (octobre-novembre 2026), rejouées : réponses inventées, faux succès,
mauvaise application ouverte, plans hors-sol, Stop sans effet pendant que le modèle calcule."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from macai.agent.orchestrateur import REFUS, Orchestrateur, bilan_honnete
from macai.agent.rapide import CommandesRapides
from macai.llm.ollama import AppelOutil, ErreurOllama, Ollama, Reponse
from macai.mac import accessibilite, commun
from macai.outils import applications
from macai.outils.base import ErreurOutil, Registre, Resultat, Risque, outil

from .conftest import FauxOllama, appel


def _t(nom, ok, texte, agit=True, effet=None):
    return {"outil": nom, "arguments": {}, "ok": ok, "agit": agit, "texte": texte,
            "effet": (ok and agit) if effet is None else effet}


# --- Bilan honnête : la trace fait foi ------------------------------------------------------------

def test_bilan_cas_reels_du_journal():
    # 23/10 : « J'ai déplacé le fichier… » après deux déplacements échoués (seule la recherche avait réussi).
    trace = [_t("chercher_partout", True, "- /a.dmg", agit=False),
             _t("deplacer", False, "/Users/m/Downloads/a.dmg n'existe pas. Utilise rechercher_fichiers pour le retrouver."),
             _t("deplacer", False, "/Users/m/Downloads/a.dmg n'existe pas. Utilise rechercher_fichiers pour le retrouver.")]
    b = bilan_honnete("J'ai déplacé le fichier vers le bureau sous le nom Minecraft.dmg.", trace)
    assert b == "Je n'ai pas réussi à le faire : /Users/m/Downloads/a.dmg n'existe pas."
    # 19/10 : « Finder s'est fermé automatiquement » alors que la fermeture avait été refusée par l'outil.
    trace = [_t("applications_ouvertes", True, "Ouvertes : Claude", agit=False),
             _t("quitter_application", False, "Finder fait partie de macOS et reste toujours ouvert : je ne le ferme pas.")]
    b = bilan_honnete("Claude est toujours ouvert, Finder s'est fermé automatiquement.", trace)
    assert b.startswith("Je n'ai pas réussi à le faire : Finder fait partie de macOS")
    # 20/11 : « Les services lancés ont été fermés » alors que rien n'était ouvert.
    trace = [_t("quitter_application", True, "Terminal n'était pas ouvert.", effet=False),
             _t("quitter_application", True, "Safari n'était pas ouvert.", effet=False)]
    assert bilan_honnete("Les services lancés ont été fermés.", trace) == \
        "Terminal n'était pas ouvert. Safari n'était pas ouvert."


def test_bilan_ne_touche_pas_ce_qui_est_vrai():
    reussi = [_t("lire", True, "contenu", agit=False), _t("deplacer", True, "Déplacé")]
    assert bilan_honnete("Fichier déplacé.", reussi) == "Fichier déplacé."
    # Un échec rattrapé ensuite par le même outil n'est pas signalé.
    rattrape = [_t("ouvrir_fichier", False, "x n'existe pas."), _t("ouvrir_fichier", True, "x.pdf est ouvert.")]
    assert bilan_honnete("Le fichier est ouvert.", rattrape) == "Le fichier est ouvert."
    # Une question (pas une action demandée) et une simple lecture gardent la réponse du modèle.
    echec = [_t("ouvrir_url", False, "Chrome ne répond pas.")]
    assert bilan_honnete("La Poste ouvre à 9 h (Source 1).", echec, imperatif=False) == "La Poste ouvre à 9 h (Source 1)."
    assert bilan_honnete("Rien trouvé.", [_t("lire", False, "boum", agit=False)]) == "Rien trouvé."


def test_bilan_etape_echouee_signalee_refus_et_mauvais_usage():
    mixte = [_t("ouvrir_application", True, "Chrome est ouvert."),
             _t("cliquer_page", False, "Élément 3 introuvable : relis la page avec lire_page (elle a pu changer).")]
    b = bilan_honnete("J'ai lancé la vidéo.", mixte)
    assert b.startswith("J'ai lancé la vidéo.") and "une étape n'a pas abouti (cliquer_page)" in b
    assert "Élément 3 introuvable" in b
    assert bilan_honnete("ok", [_t("corbeille", False, REFUS)]) == "D'accord, je ne le fais pas."
    usage = [_t("taper_texte", False, "Paramètre manquant : application. Paramètres de taper_texte : texte (…).")]
    assert bilan_honnete("C'est tapé.", usage) == \
        "Je n'ai pas réussi à le faire : je n'ai pas su utiliser « taper_texte » correctement."


def _registre_fermer():
    reg = Registre()

    @outil("deplacer", "Déplace", "fichiers", {"source": ("string", ""), "destination": ("string", "")},
           risque=Risque.MODIFICATION, mac_seulement=False, registre=reg)
    def deplacer(ctx, source, destination):
        raise ErreurOutil(f"{source} n'existe pas. Utilise rechercher_fichiers pour le retrouver.")

    @outil("chercher", "Cherche", "fichiers", {"requete": ("string", "")}, mac_seulement=False, registre=reg)
    def chercher(ctx, requete):
        return "- /tmp/autre.dmg"

    @outil("quitter_application", "Quitte", "applications", {"nom": ("string", "")}, risque=Risque.MODIFICATION,
           mac_seulement=False, registre=reg)
    def quitter(ctx, nom):
        return Resultat(True, f"{nom} n'était pas ouvert.", sans_effet=True)
    return reg


def _quitter(nom):  # « nom » est aussi le premier paramètre de l'aide appel()
    return Reponse(appels=[AppelOutil("quitter_application", {"nom": nom})])


def test_reponse_inventee_remplacee_dans_la_boucle(ctx):
    ctx.registre = _registre_fermer()
    ctx.ollama = FauxOllama([appel("chercher", requete="minecraft"),
                             appel("deplacer", source="/tmp/autre.dmg", destination="~/Desktop/Minecraft.dmg"),
                             Reponse(texte="J'ai déplacé le fichier sur le bureau, l'installation est prête.")])
    texte = Orchestrateur(ctx).traiter("j'ai un fichier minecraft sur mon bureau fais le marcher")
    assert texte == "Je n'ai pas réussi à le faire : /tmp/autre.dmg n'existe pas."
    fin = [d for t, d in ctx.evenements if t == "fin"][-1]
    assert fin["texte"] == texte  # l'interface affiche la version vérifiée, pas le texte diffusé


def test_fermer_une_appli_deja_fermee_n_est_pas_un_succes(ctx):
    ctx.registre = _registre_fermer()
    ctx.ollama = FauxOllama([_quitter("Terminal"), _quitter("Safari"),
                             Reponse(texte="Les services lancés ont été fermés.")])
    texte = Orchestrateur(ctx).traiter("ferme tous les services lancés")
    assert texte == "Terminal n'était pas ouvert. Safari n'était pas ouvert."
    # Réponse vide du modèle : « C'est fait. » seulement si une action a vraiment eu un effet.
    ctx.ollama = FauxOllama([_quitter("Notes"), Reponse(texte=""), Reponse(texte="")])
    assert Orchestrateur(ctx).traiter("ferme Notes maintenant") == "Notes n'était pas ouvert."


# --- Applications : ni suggestion trompeuse, ni dossier pris pour une appli --------------------------

@pytest.fixture
def commandes(monkeypatch, tmp_path):
    faites = []
    monkeypatch.setattr(commun, "executer", lambda cmd, **k: faites.append(cmd) or "")
    for nom in ["FilmCraft.app", "SoundCraft.app", "Shortcuts.app", "Finder.app", "Safari.app"]:
        (tmp_path / "apps" / nom).mkdir(parents=True)
    monkeypatch.setattr(applications, "DOSSIERS_APPS", [str(tmp_path / "apps")])
    monkeypatch.setattr(applications, "_cache", None)
    return faites


def test_application_absente_sans_proposition(ctx, commandes):
    with pytest.raises(ErreurOutil) as e:  # 23/10 : « Vouliez-vous : FilmCraft… ? » → le modèle ouvrait FilmCraft
        applications.ouvrir_application(ctx, "Minecraft")
    assert "introuvable" in str(e.value) and "pas installée" in str(e.value)
    assert "FilmCraft" not in str(e.value) and "Vouliez" not in str(e.value) and commandes == []


def test_dossier_ouvert_au_lieu_d_une_appli(ctx, commandes, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Documents").mkdir()
    for nom in ["Téléchargements", "le dossier Téléchargements", "mes documents"]:
        r = applications.ouvrir_application(ctx, nom)
        assert r.ok and "Dossier" in r.texte
    assert commandes == [["open", str(tmp_path / "Downloads")]] * 2 + [["open", str(tmp_path / "Documents")]]
    assert applications.dossier_connu("Safari") is None and applications.dossier_connu("Bureau") is None  # absent


def test_quitter_sans_effet_et_applis_protegees(ctx, commandes, monkeypatch):
    monkeypatch.setattr(accessibilite, "applis_ouvertes", lambda: [])
    r = applications.quitter_application(ctx, "Safari")
    assert r.ok and r.sans_effet and "n'était pas ouvert" in r.texte
    with pytest.raises(ErreurOutil, match="fait partie de macOS"):
        applications.quitter_application(ctx, "Finder")
    monkeypatch.setattr(commun, "executer", lambda cmd, **k: (
        'ASN:0x0-0x1-"Claude": ASN:0x0-0x2-"Finder": ASN:0x0-0x3-"Google_Chrome":' if "visibleProcessList" in cmd else ""))
    texte = applications.applications_ouvertes(ctx).texte
    assert texte.splitlines()[0] == "Ouvertes : Claude, Google Chrome"
    assert "ne se ferment pas) : Finder" in texte


# --- Plan : écrit avec les outils réels ---------------------------------------------------------------

def test_plan_redige_avec_les_outils_disponibles(ctx):
    ctx.registre = _registre_fermer()
    ctx.ollama = FauxOllama([Reponse(texte="1. Quitter Chrome\n2. Quitter Claude\n3. Vérifier")])
    ctx.demander_plan = lambda ident, etapes: ("refuser", "")
    Orchestrateur(ctx).traiter("ferme Chrome et Claude puis range le dossier")
    consigne = ctx.ollama.recus[0]["messages"][0]["content"]
    assert "- Quitte" in consigne and "quitter_application" not in consigne and "N'invente ni bouton" in consigne
    from macai.agent.orchestrateur import lire_plan
    assert lire_plan("1. ranger_dossier\n2. Fermer Chrome\n3. envoyer_mail(destinataire)") == ["Fermer Chrome"]


# --- Stop : coupe le calcul en cours, même avant le premier mot -----------------------------------------

class _OllamaLent(BaseHTTPRequestHandler):
    """Faux Ollama : `avant` s de silence avant les en-têtes, un morceau, puis `apres` s de silence."""
    avant = apres = 0.0

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            time.sleep(self.avant)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            self.wfile.write(json.dumps({"message": {"content": "Bon"}}).encode() + b"\n")
            self.wfile.flush()
            time.sleep(self.apres)
            self.wfile.write(json.dumps({"message": {"content": "jour"}, "done": True}).encode() + b"\n")
        except OSError:
            pass  # client parti : c'est ce qu'on teste

    def log_message(self, *a):
        pass


@pytest.fixture
def ollama_lent():
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _OllamaLent)
    serveur.daemon_threads = True
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    yield Ollama(hote=f"http://127.0.0.1:{serveur.server_address[1]}")
    serveur.shutdown()
    serveur.server_close()
    _OllamaLent.avant = _OllamaLent.apres = 0.0


@pytest.mark.parametrize("avant,apres", [(5.0, 0.0), (0.0, 5.0)])  # pendant le chargement / pendant la réponse
def test_stop_coupe_le_calcul(ollama_lent, avant, apres):
    _OllamaLent.avant, _OllamaLent.apres = avant, apres
    arret = threading.Event()
    threading.Timer(0.3, arret.set).start()
    debut = time.monotonic()
    with pytest.raises(InterruptedError):
        ollama_lent.discuter("m", [{"role": "user", "content": "x"}], sur_texte=lambda t: None, arret=arret)
    assert time.monotonic() - debut < 2.0  # sans la coupure : 5 s


def test_flux_arretable_normal_et_erreurs(ollama_lent):
    arret = threading.Event()
    assert ollama_lent.discuter("m", [], arret=arret).texte == "Bonjour"
    mort = Ollama(hote="http://127.0.0.1:9")  # personne n'écoute
    with pytest.raises(ErreurOllama, match="injoignable"):
        mort.discuter("m", [], arret=arret)


def test_stop_pendant_la_demande_repond_arrete(ctx):
    class OllamaInterrompu(FauxOllama):
        def discuter(self, *a, arret=None, **k):
            assert arret is ctx.arret  # l'orchestrateur transmet bien l'événement « Stop »
            raise InterruptedError
    ctx.registre = _registre_fermer()
    ctx.ollama = OllamaInterrompu()
    assert Orchestrateur(ctx, CommandesRapides()).traiter("raconte-moi une longue histoire") == "Arrêté."
    assert [e["texte"] for e in ctx.journal.derniers() if e["type"] == "reponse"] == ["Arrêté."]
