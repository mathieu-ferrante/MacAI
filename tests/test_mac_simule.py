"""Code propre au Mac, exécuté avec AppleScript et les commandes système simulés."""
import json

import pytest

from macai.mac import commun
from macai.outils import applications, chrome, fenetres, organisation, systeme
from macai.outils.base import ErreurOutil


@pytest.fixture
def scripts(monkeypatch):
    """Enregistre les AppleScript et commandes ; réponses programmables."""
    journal = {"as": [], "cmd": [], "reponses": []}

    def faux_osascript(script, javascript=False, delai=30):
        journal["as"].append(script)
        return journal["reponses"].pop(0) if journal["reponses"] else ""

    def faux_executer(cmd, delai=30, entree=None, verifier=True):
        journal["cmd"].append(cmd)
        return ""

    monkeypatch.setattr(commun, "osascript", faux_osascript)
    monkeypatch.setattr(commun, "executer", faux_executer)
    return journal


def test_echappement_applescript():
    assert commun.chaine_as('il a dit "oui" \\ ok') == '"il a dit \\"oui\\" \\\\ ok"'


def test_chemins_francais(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert commun.chemin("Bureau/notes.txt") == (tmp_path / "Desktop" / "notes.txt").resolve()
    assert commun.chemin("téléchargements") == (tmp_path / "Downloads").resolve()


def test_erreurs_macos_expliquees():
    assert "Automatisation" in commun._expliquer("execution error: Not authorized to send Apple events (-1743)")
    assert "Accessibilité" in commun._expliquer("System Events got an error: -25211")


def test_volume_et_media(ctx, scripts):
    systeme.regler_volume(ctx, 150)
    assert scripts["as"][-1] == "set volume output volume 100 without output muted"
    scripts["reponses"] = ["45"]
    assert systeme.controle_media(ctx, "volume_plus") == "Volume : 55 %."


def test_ouvrir_url_et_recherche(ctx, scripts):
    chrome.ouvrir_url(ctx, "cad.onshape.com")
    assert 'make new tab with properties {URL:"https://cad.onshape.com"}' in scripts["as"][-1]
    chrome.chrome_rechercher(ctx, "tuto blender débutant", "youtube")
    assert "youtube.com/results?search_query=tuto+blender+d%C3%A9butant" in scripts["as"][-1]


def test_youtube_lit_la_premiere_video(ctx, scripts, monkeypatch):
    monkeypatch.setattr(chrome.time, "sleep", lambda s: None)
    scripts["reponses"] = ["", "complete", "https://www.youtube.com/watch?v=abc|Daft Punk - Get Lucky", ""]
    r = chrome.youtube_lire(ctx, "daft punk get lucky")
    assert r.ok and "Get Lucky" in r.texte and r.donnees["url"].endswith("v=abc")
    assert 'location.href = \\"https://www.youtube.com/watch?v=abc\\"' in scripts["as"][-1]


def test_javascript_chrome_desactive(ctx, monkeypatch):
    def refus(script, javascript=False, delai=30):
        raise ErreurOutil("Executing JavaScript through AppleScript is turned off.")
    monkeypatch.setattr(commun, "osascript", refus)
    with pytest.raises(ErreurOutil, match="Apple Events"):
        chrome.lire_page(ctx)


def test_lire_page_et_cliquer(ctx, scripts, monkeypatch):
    monkeypatch.setattr(chrome.time, "sleep", lambda s: None)
    scripts["reponses"] = [json.dumps({"titre": "Onshape", "url": "https://cad.onshape.com",
                                       "elements": ["1 [button] Créer", "2 [input:text] Rechercher"],
                                       "texte": "Bienvenue"})]
    r = chrome.lire_page(ctx)
    assert "1 [button] Créer" in r.texte and r.donnees["titre"] == "Onshape"
    scripts["reponses"] = ["Créer", "ok", "complete"]
    assert "Clic" in chrome.cliquer_page(ctx, 1)
    scripts["reponses"] = ["", "absent"]
    with pytest.raises(ErreurOutil, match="relis la page"):
        chrome.cliquer_page(ctx, 99)
    scripts["reponses"] = ["Acheter plus de crédits d'utilisation", "ok"]
    with pytest.raises(ErreurOutil, match="achat"):
        chrome.cliquer_page(ctx, 3)


def test_remplir_refuse_donnees_bancaires(ctx, scripts):
    with pytest.raises(ErreurOutil, match="bancaires"):
        chrome.remplir_page(ctx, 2, "4970 1012 3456 7890")
    scripts["reponses"] = ["motdepasse"]
    with pytest.raises(ErreurOutil, match="mot de passe"):
        chrome.remplir_page(ctx, 2, "texte normal")
    scripts["reponses"] = ["ok"]
    assert "écrit" in chrome.remplir_page(ctx, 2, "carte graphique RTX")   # le mot « carte » est permis


def test_html_vers_texte():
    titre, texte = chrome.html_vers_texte("<html><head><title>Titre</title><script>x()</script></head>"
                                          "<body><nav>menu</nav><p>Bonjour</p><p>le monde</p></body></html>")
    assert titre == "Titre" and "Bonjour" in texte and "menu" not in texte and "x()" not in texte


def test_trouver_application(monkeypatch, tmp_path):
    for nom in ["Google Chrome.app", "Visual Studio Code.app", "Spotify.app", "ArtCraft/PhotoCraft.app"]:
        (tmp_path / nom).mkdir(parents=True)
    monkeypatch.setattr(applications, "DOSSIERS_APPS", [str(tmp_path)])
    monkeypatch.setattr(applications, "_cache", None)
    assert applications.trouver_application("chrome").stem == "Google Chrome"
    assert applications.trouver_application("vscode").stem == "Visual Studio Code"
    assert applications.trouver_application("photocraft").stem == "PhotoCraft"
    assert applications.trouver_application("spotfy").stem == "Spotify"          # faute de frappe
    assert applications.trouver_application("Photoshop") is None


def test_ouvrir_application_inconnue_suggere(ctx, scripts, monkeypatch, tmp_path):
    (tmp_path / "Spotify.app").mkdir()
    monkeypatch.setattr(applications, "DOSSIERS_APPS", [str(tmp_path)])
    monkeypatch.setattr(applications, "_cache", None)
    applications.ouvrir_application(ctx, "spotify")
    assert scripts["cmd"][-1] == ["open", "-a", str(tmp_path / "Spotify.app")]
    with pytest.raises(ErreurOutil, match="introuvable"):
        applications.ouvrir_application(ctx, "Logiciel Imaginaire")


def test_menu_et_raccourcis(ctx, scripts, monkeypatch):
    monkeypatch.setattr(applications, "trouver_application", lambda n: None)
    fenetres.choisir_menu(ctx, "Pages", "Fichier > Exporter vers > PDF…")
    s = scripts["as"][-1]
    assert 'click menu item "PDF…" of menu 1 of menu item "Exporter vers" of menu 1 of menu bar item "Fichier"' in s
    with pytest.raises(ErreurOutil, match="quitter_application"):
        fenetres.raccourci_clavier(ctx, "cmd+q")
    from macai.mac import accessibilite
    accessibilite.raccourci(["cmd", "maj"], "n")
    assert scripts["as"][-1] == 'tell application "System Events" to keystroke "n" using {command down, shift down}'
    accessibilite.raccourci([], "entree")
    assert scripts["as"][-1] == 'tell application "System Events" to key code 36'


def test_coordonnees_vision():
    assert fenetres.extraire_coordonnees('Voici : {"x": 512, "y": 300}') == (512, 300)
    assert fenetres.extraire_coordonnees("(120, 45)") == (120, 45)
    with pytest.raises(ErreurOutil):
        fenetres.extraire_coordonnees("je ne sais pas")


def test_rappel_et_evenement(ctx, scripts):
    organisation.creer_rappel(ctx, "Appeler la banque", "2026-10-15 09:30")
    s = scripts["as"][-1]
    assert "set year of d to 2026" in s and "set month of d to 10" in s and "set hours of d to 9" in s
    assert "remind me date:d" in s and 'name:"Appeler la banque"' in s
    organisation.creer_evenement(ctx, "Réunion", "2026-10-15 14:00", lieu="Toulon")
    assert "set hours of d2 to 15" in scripts["as"][-1] and 'location:"Toulon"' in scripts["as"][-1]
    with pytest.raises(ErreurOutil, match="après le début"):
        organisation.creer_evenement(ctx, "x", "2026-10-15 14:00", "2026-10-15 13:00")


def test_envoyer_mail_toujours_confirme(ctx):
    from macai.outils.base import charger_tous
    o = charger_tous().get("envoyer_mail")
    assert o.toujours_confirmer and "ENVOYER" in o.phrase({"destinataire": "a@b.fr", "sujet": "x", "corps": ""})
