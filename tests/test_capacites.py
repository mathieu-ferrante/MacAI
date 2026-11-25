"""Capacités ajoutées d'après le journal du Mac : calculs, fermeture groupée, Wi-Fi, mode sombre, installation."""
import subprocess
from types import SimpleNamespace

import pytest

from macai.calcul import CalculImpossible, calculer, en_francais
from macai.outils import applications, systeme
from macai.outils.base import ErreurOutil


@pytest.mark.parametrize("phrase,attendu", [("combien font 5000-964", "4 036"), ("calcule 12 fois 7", "84"),
                                            ("20 % de 150", "30"), ("combien fait 0,1 + 0,2", "0,3"),
                                            ("racine carrée de 144", "12"), ("2^10", "1 024"),
                                            ("combien font 5 000 divisé par 4", "1 250"), ("(3+4)*2", "14")])
def test_calculs(phrase, attendu):
    assert en_francais(calculer(phrase)) == attendu


@pytest.mark.parametrize("phrase", ["combien coûte une Porsche 964", "combien de batterie il me reste",
                                    "mets le volume à 30", "__import__('os').system('id')", "9**9**9"])
def test_pas_un_calcul_ou_refuse(phrase):
    with pytest.raises(CalculImpossible):
        calculer(phrase)


@pytest.fixture
def mac(monkeypatch):
    """lsappinfo et AppleScript simulés."""
    ouvertes = [{"nom": "Google Chrome", "pid": 11, "paquet": "Google Chrome", "id": "com.google.Chrome"},
                {"nom": "Finder", "pid": 12, "paquet": "Finder", "id": "com.apple.finder"},
                {"nom": "Claude", "pid": 13, "paquet": "Claude", "id": "com.anthropic.claudefordesktop"},
                {"nom": "Notes", "pid": 14, "paquet": "Notes", "id": "com.apple.Notes"}]
    scripts = []
    from macai.mac import accessibilite, commun

    def quitter(script, **k):
        scripts.append(script)
        for a in list(ouvertes):
            if a["id"] in script and a["nom"] != "Notes":  # Notes attend un enregistrement
                ouvertes.remove(a)
        return ""
    monkeypatch.setattr(accessibilite, "applis_ouvertes", lambda: list(ouvertes))
    monkeypatch.setattr(commun, "osascript", quitter)
    monkeypatch.setattr(applications.time, "sleep", lambda s: None)
    monkeypatch.setattr(applications, "trouver_application",
                        lambda n: SimpleNamespace(stem={"claude": "Claude", "notes": "Notes"}.get(n.lower().strip(), n)))
    return ouvertes, scripts


def test_fermer_tout_sauf(ctx, mac):
    ouvertes, scripts = mac
    assert "Google Chrome, Claude, Notes" in applications._annonce_fermer({})
    r = applications.fermer_applications(ctx, sauf="Claude")
    assert r.ok and "Google Chrome" in r.texte and "Notes" in r.texte and "Encore ouvert" in r.texte
    assert not any("finder" in s for s in scripts) and not any("claude" in s for s in scripts)
    assert {a["nom"] for a in ouvertes} == {"Finder", "Claude", "Notes"}


def test_wifi_et_mode_sombre(ctx, monkeypatch):
    from macai.mac import commun
    cmds, scripts = [], []

    def executer(cmd, **k):
        cmds.append(cmd)
        if "-listallhardwareports" in cmd:
            return "Hardware Port: Wi-Fi\nDevice: en1\n"
        if "-getairportpower" in cmd:
            return "Wi-Fi Power (en1): Off"
        return ""
    monkeypatch.setattr(commun, "executer", executer)
    monkeypatch.setattr(commun, "osascript", lambda s, **k: scripts.append(s) or "")
    assert systeme.regler_wifi(ctx, False) == "Wi-Fi coupé."
    assert ["/usr/sbin/networksetup", "-setairportpower", "en1", "off"] in cmds
    assert not systeme.regler_wifi(ctx, True).ok  # l'état n'a pas changé : on le dit
    systeme.mode_sombre(ctx, True)
    assert "set dark mode to true" in scripts[-1]


@pytest.fixture
def installation(monkeypatch, tmp_path):
    """hdiutil, ditto et spctl simulés ; « /Applications » remplacé par un dossier temporaire."""
    apps = tmp_path / "Applications"
    apps.mkdir()
    monkeypatch.setattr(applications, "APPLICATIONS", apps)
    etat = {"spctl": "accepted\nsource=Notarized Developer ID", "spctl_code": 0, "appels": []}

    def run(cmd, **k):
        etat["appels"].append(cmd[0])
        if cmd[0].endswith("hdiutil") and cmd[1] == "attach":
            point = cmd[cmd.index("-mountpoint") + 1]
            (tmp_path / "monte").mkdir(exist_ok=True)
            import os
            os.rmdir(point)
            os.symlink(tmp_path / "contenu", point)
        if cmd[0].endswith("ditto"):
            import shutil
            shutil.copytree(cmd[1], cmd[2])
        if cmd[0].endswith("spctl"):
            return subprocess.CompletedProcess(cmd, etat["spctl_code"], "", etat["spctl"])
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    (tmp_path / "contenu" / "Minecraft.app" / "Contents").mkdir(parents=True)
    dmg = tmp_path / "Minecraft.dmg"
    dmg.write_bytes(b"x")
    from macai.outils import fichiers
    monkeypatch.setattr(fichiers, "chemin_interdit", lambda p: False)
    return dmg, apps, etat


def test_installer_depuis_un_dmg(ctx, installation):
    dmg, apps, etat = installation
    r = applications.installer_application(ctx, str(dmg))
    assert r.ok and (apps / "Minecraft.app").is_dir() and "notarié" in r.texte
    assert "hdiutil" in " ".join(etat["appels"])
    assert applications.installer_application(ctx, str(dmg)).sans_effet  # déjà installé


def test_installation_refusee_sans_notarisation(ctx, installation):
    dmg, apps, etat = installation
    etat["spctl"], etat["spctl_code"] = "rejected\nsource=no usable signature", 3
    with pytest.raises(ErreurOutil, match="notariée"):
        applications.installer_application(ctx, str(dmg))
    assert not (apps / "Minecraft.app").exists()


def test_installer_pkg_refuse(ctx, tmp_path, monkeypatch):
    from macai.outils import fichiers
    monkeypatch.setattr(fichiers, "chemin_interdit", lambda p: False)
    (tmp_path / "x.pkg").write_bytes(b"x")
    with pytest.raises(ErreurOutil, match="pkg"):
        applications.installer_application(ctx, str(tmp_path / "x.pkg"))


def test_installer_toujours_confirme(monkeypatch):
    monkeypatch.setenv("MACAI_TOUS_OUTILS", "1")
    from macai.outils.base import charger_tous
    r = charger_tous()
    assert r.get("installer_application").toujours_confirmer
    assert r.get("fermer_applications").risque_pour({}) >= 3


def test_prechauffage_charge_puis_s_efface_devant_une_demande(cfg):
    import threading
    from macai.application import Application
    from .conftest import FauxOllama

    class Lent(FauxOllama):
        def __init__(self):
            super().__init__()
            self.coupe = threading.Event()

        def discuter(self, modele, messages, outils=None, reflexion=False, sur_texte=None, options=None, arret=None):
            if options and options.get("num_predict") == 1:  # préchauffage : attend d'être interrompu
                if arret is not None and arret.wait(5):
                    self.coupe.set()
                    raise InterruptedError
            return super().discuter(modele, messages, outils, reflexion, sur_texte, options, arret)

    o = Lent()
    app = Application(cfg, ollama=o, avec_fond=False)
    assert app.prechauffer() is True
    assert app.prechauffer() is False            # déjà en cours : pas de second chargement
    assert app.traiter_en_fond("quelle heure est-il")
    assert o.coupe.wait(3)                        # la demande a interrompu le préchauffage



def test_recurrence_programmee_sans_modele():
    """Banc du 25/11 : « tous les matins à 8h, fais-moi un résumé… » était parfois fait tout de suite."""
    from macai.agent.rapide import CommandesRapides
    r = CommandesRapides()
    p = r.reconnaitre("tous les matins à 8h, fais-moi un résumé de mes mails et de mon agenda")
    assert p.actions == [("planifier_tache", {"demande": "Fais-moi un résumé de mes mails et de mon agenda",
                                              "frequence": "quotidien", "heure": "08:00"})]
    p = r.reconnaitre("chaque lundi à 9h30 range mes téléchargements")
    assert p.actions[0][1] == {"demande": "Range mes téléchargements", "frequence": "hebdomadaire",
                               "heure": "09:30", "jour": "lundi"}
    assert r.reconnaitre("tous les jours je bois du café") is None
