"""Assistant de logiciel, démonstration et compétences toutes faites (Accessibilité simulée, aucun accès réel)."""
from types import SimpleNamespace

import pytest

from macai import demonstration as demo
from macai.competences import modeles
from macai.competences.competences import Bibliotheque
from macai.mac import accessibilite as ax
from macai.outils import guide
from macai.outils.base import Outil, Registre, Risque


# --- Accessibilité simulée -------------------------------------------------------------

class El:
    def __init__(self, **attrs):
        self.attrs = attrs


def faux_attribut(el, nom):
    return el.attrs.get(nom) if isinstance(el, El) else None


class FauxAS:
    kAXValueCGPointType, kAXValueCGSizeType = "p", "t"

    @staticmethod
    def AXValueGetValue(val, genre, _):
        return True, val

    @staticmethod
    def AXUIElementCreateApplication(pid):
        return FAUSSE_APP


def item(titre, enfants=None, car=None, mods=0, actif=True):
    attrs = {"AXRole": "AXMenuItem", "AXTitle": titre, "AXEnabled": actif}
    if car:
        attrs.update(AXMenuItemCmdChar=car, AXMenuItemCmdModifiers=mods)
    if enfants:
        attrs["AXChildren"] = [El(AXRole="AXMenu", AXChildren=enfants)]
    return El(**attrs)


def menu_barre(titre, items, x=100):
    return El(AXRole="AXMenuBarItem", AXTitle=titre, AXChildren=[El(AXRole="AXMenu", AXChildren=items)],
              AXPosition=SimpleNamespace(x=x, y=0), AXSize=SimpleNamespace(width=60, height=24))


BARRE = El(AXRole="AXMenuBar", AXChildren=[
    menu_barre("Pomme", []),
    menu_barre("Fichier", [item("Nouveau", car="n"), item(""),
                           item("Exporter", [item("PDF…"), item("Word…"), item("EPUB…")]),
                           item("Enregistrer", car="s"), item("Imprimer…", car="p")], x=40),
    menu_barre("Édition", [item("Annuler", car="z"), item("Rechercher", [item("Rechercher…", car="f")])], x=110),
])
FAUSSE_APP = El(AXMenuBar=BARRE)


@pytest.fixture
def faux_ax(monkeypatch):
    monkeypatch.setattr(ax, "_ax", lambda: FauxAS)
    monkeypatch.setattr(ax, "attribut", faux_attribut)
    monkeypatch.setattr(ax, "pid_application", lambda nom: (42, "Pages"))
    bouton = El(AXRole="AXButton", AXTitle="Exporter le document", AXPosition=SimpleNamespace(x=300, y=200),
                AXSize=SimpleNamespace(width=80, height=30))
    elements = [ax.Element(El(), "AXStaticText", "Titre", ""),
                ax.Element(bouton, "AXButton", "Exporter le document", ""),
                ax.Element(El(), "AXButton", "Partager", ""),
                ax.Element(El(), "AXButton", "Acheter des crédits", "")]
    monkeypatch.setattr(ax, "explorer_fenetre", lambda nom=None, textes=True: ("Pages — Rapport", elements))
    presses = []
    monkeypatch.setattr(ax, "appuyer", lambda el: presses.append(el))
    monkeypatch.setattr(guide.time, "sleep", lambda s: None)
    return SimpleNamespace(elements=elements, presses=presses, bouton=bouton)


def test_chemins_de_menus_et_raccourcis(faux_ax):
    chemins = guide.chemins_menus(BARRE)
    noms = [c["chemin"] for c in chemins]
    assert "Fichier > Exporter > PDF…" in noms and "Édition > Rechercher > Rechercher…" in noms
    assert not any(n.startswith("Pomme") for n in noms)
    assert next(c for c in chemins if c["chemin"] == "Fichier > Enregistrer")["raccourci"] == "⌘S"


def test_classement_francais_et_anglais():
    cands = [{"chemin": c} for c in ["File > Export To > PDF…", "File > Print…", "Edit > Undo", "File > Save"]]
    assert guider_premier(cands, "exporter en PDF") == "File > Export To > PDF…"
    assert guider_premier(cands, "comment on fait pour imprimer") == "File > Print…"
    assert guide.classer("blablabla", cands) == []


def guider_premier(cands, objectif):
    return guide.classer(objectif, cands)[0]["chemin"]


def test_guider(ctx, faux_ax):
    r = guide.guider(ctx, "Pages", "exporter en PDF")
    assert r.ok and r.donnees["menus"][0] == "Fichier > Exporter > PDF…"
    assert "n° 2" in r.texte and "montrer_menu" in r.texte
    assert ctx.services["ax_elements"] is faux_ax.elements  # numéros réutilisables par montrer_element


def test_montrer_element_et_menu(ctx, faux_ax):
    guide.guider(ctx, "Pages", "exporter")
    r = guide.montrer_element(ctx, 2)
    assert r.ok
    assert ctx.evenements[-1] == ("surligner", {"x": 300.0, "y": 200.0, "largeur": 80.0, "hauteur": 30.0,
                                                "texte": "Exporter le document"})
    r = guide.montrer_menu(ctx, "Pages", "Fichier > Exporter > PDF…")
    assert "« Fichier »" in r.texte and "« PDF… »" in r.texte
    assert ctx.evenements[-1][0] == "surligner" and ctx.evenements[-1][1]["x"] == 40.0
    with pytest.raises(guide.ErreurOutil):
        guide.montrer_menu(ctx, "Pages", "Format > Police")


def test_cliquer_libelle(ctx, faux_ax):
    assert "Exporter le document" in guide.cliquer_libelle(ctx, "Pages", "exporter le document")
    assert faux_ax.presses == [faux_ax.bouton]
    with pytest.raises(guide.ErreurOutil):
        guide.cliquer_libelle(ctx, "Pages", "Acheter des crédits")
    with pytest.raises(guide.ErreurOutil):
        guide.cliquer_libelle(ctx, "Pages", "Introuvable")
    assert len(faux_ax.presses) == 1
    assert guide._risque_cliquer_libelle({"application": "Pages", "libelle": "Partager"}) == Risque.SENSIBLE
    assert guide._risque_cliquer_libelle({"application": "Pages", "libelle": "Exporter"}) == Risque.MODIFICATION


# --- Démonstration ------------------------------------------------------------------------

def frappe(texte, app="Pages", **extra):
    return [{"type": "touche", "caractere": c, "application": app, **extra} for c in texte]


def test_conversion_d_une_demonstration():
    evenements = [
        {"type": "clic", "role": "AXDockItem", "libelle": "Pages", "application": "Dock"},
        {"type": "clic", "role": "AXMenuBarItem", "libelle": "Fichier", "application": "Pages"},
        {"type": "clic", "role": "AXMenuItem", "libelle": "PDF…", "application": "Pages",
         "menu": ["Fichier", "Exporter", "PDF…"], "barre": True},
        {"type": "clic", "role": "AXTextField", "libelle": "Nom", "application": "Pages"},
        *frappe("Rapport mai"), {"type": "touche", "special": "effacer", "application": "Pages"},
        *frappe("i"),
        {"type": "clic", "role": "AXButton", "libelle": "Exporter", "application": "Pages"},
        {"type": "clic", "role": "AXButton", "libelle": "Exporter", "application": "Pages"},  # double-clic
        {"type": "clic", "role": "AXGroup", "libelle": "", "application": "Pages"},
        {"type": "raccourci", "touches": "cmd+s", "application": "Pages"},
        {"type": "clic", "role": "AXButton", "libelle": "Envoyer", "application": "MacAI"},  # ignoré
    ]
    actions = demo.regrouper(evenements)
    etapes = [demo._phrase(a) for a in actions]
    assert etapes[0] == "ouvrir Pages"
    assert "menu Fichier > Exporter > PDF… dans Pages" in etapes
    assert "taper « Rapport mai » dans Pages" in etapes
    assert sum("« Exporter »" in e for e in etapes) == 1
    assert any("non rejouable" in e for e in etapes) and not any("MacAI" in e for e in etapes)
    rec = demo.recette(actions, "exporter le rapport")
    assert rec["nom"] == "exporter_le_rapport" and rec["source"] == "demonstration"
    outils = [e["outil"] for e in rec["etapes"]]
    assert outils == ["ouvrir_application", "choisir_menu", "cliquer_libelle", "taper_texte", "cliquer_libelle",
                      "raccourci_clavier"]
    assert rec["etapes"][3]["arguments"]["texte"] == "{texte}" and "texte" in rec["parametres"]
    lignes = demo.apercu(rec)
    assert lignes[1] == "2. menu Fichier > Exporter > PDF… dans Pages" and "{texte}" in lignes[3]


def test_demonstration_ne_garde_aucun_secret():
    evenements = [
        {"type": "clic", "role": "AXButton", "libelle": "Connexion", "application": "Safari"},
        *frappe("motdepasse", app="Safari", secret=True),
        *frappe("4111 1111 1111 1111", app="Notes"),
        {"type": "touche", "special": "entree", "application": "Notes"},
        *frappe("Xk9#pq2!Lm", app="Notes"),
    ]
    actions = demo.regrouper(evenements)
    textes = [a["texte"] for a in actions if a["genre"] == "texte"]
    assert all(t == demo.MASQUE for t in textes) and len(textes) == 3
    assert "motdepasse" not in repr(actions)
    rec = demo.recette(actions)
    assert rec is not None and "taper_texte" not in [e["outil"] for e in rec["etapes"]]
    assert demo.masquer("Bonjour à tous") == "Bonjour à tous"


def test_carte_masquee():
    # Numéro valide (Luhn) : masqué.
    assert demo.masquer("4111 1111 1111 1111") == demo.MASQUE


def test_recette_trop_courte_non_proposee():
    assert demo.recette(demo.regrouper([{"type": "clic", "role": "AXDockItem", "libelle": "Notes",
                                         "application": "Dock"}])) is None


def test_enregistreur_sans_tap(ctx, monkeypatch):
    monkeypatch.setattr(demo.Enregistreur, "_lancer_ecoute", lambda self: None)
    e = demo.obtenir(ctx)
    assert demo.obtenir(ctx) is e
    assert e.demarrer()["ok"] and e.actif
    for ev in [{"type": "clic", "role": "AXButton", "libelle": "Nouveau", "application": "Notes"},
               *frappe("Courses", app="Notes"), {"type": "raccourci", "touches": "cmd+s", "application": "Notes"}]:
        e.ajouter(ev)
    r = e.arreter("note courses")
    assert r["ok"] and not e.actif and r["competence"]["nom"] == "note_courses"
    assert r["etapes"][0] == "ouvrir Notes"
    assert ("demonstration", {"etat": "fin"}) in ctx.evenements
    assert not e.arreter()["ok"]


def test_arret_automatique(ctx, monkeypatch):
    monkeypatch.setattr(demo.Enregistreur, "_lancer_ecoute", lambda self: None)
    e = demo.Enregistreur(ctx, duree_max=0.05)
    e.demarrer()
    e.ajouter({"type": "clic", "role": "AXButton", "libelle": "Nouveau", "application": "Notes"})
    e._minuterie.join(2)
    assert not e.actif
    r = e.arreter()
    assert r["ok"] and "10 minutes" in r["texte"]


def test_autorisation_manquante(ctx, monkeypatch):
    def refus(self):
        raise demo.ErreurOutil(demo.AUTORISATION)
    monkeypatch.setattr(demo.Enregistreur, "_lancer_ecoute", refus)
    with pytest.raises(demo.ErreurOutil, match="Surveillance de l'entrée"):
        demo.Enregistreur(ctx).demarrer()


# --- Compétences toutes faites -----------------------------------------------------------------

def _registre_artcraft(*noms) -> Registre:
    reg = Registre()
    for n in noms:
        reg.ajouter(Outil(nom=n, description=n, fonction=lambda ctx, **a: "ok", groupe="mcp", mac_seulement=False))
    return reg


def test_modeles_utilisent_de_vrais_outils():
    import json
    from pathlib import Path
    cache = Path.home() / "Library/Application Support/MacAI/mcp_cache.json"
    tous = modeles.charger_modeles()
    assert len(tous) >= 5 and all(m["source"] == "modele" for m in tous)
    if not cache.exists():
        pytest.skip("cache MCP absent (poste sans ArtCraft)")
    connus = {f"{s}__{o['name']}" for s, v in json.loads(cache.read_text(encoding="utf-8")).items()
              for o in v.get("outils", [])}
    for m in tous:
        assert modeles.outils_requis(m) <= connus, m["nom"]


def test_modeles_disponibles_et_installation(ctx, tmp_path):
    reg = _registre_artcraft("photocraft__doc_open", "photocraft__doc_export", "photocraft__doc_close")
    dispo = [m["nom"] for m in modeles.modeles_disponibles(reg)]
    assert "convertir_image_jpg" in dispo and "creer_logo_texte" not in dispo
    biblio = Bibliotheque(tmp_path / "competences", reg)
    c = modeles.installer_modele(biblio, "Convertir image JPG")
    assert c.nom == "convertir_image_jpg" and reg.get("competence_convertir_image_jpg") is not None
    assert (tmp_path / "competences" / "convertir_image_jpg.json").exists()
    with pytest.raises(KeyError):
        modeles.installer_modele(biblio, "creer_logo_texte")
    with pytest.raises(KeyError):
        modeles.installer_modele(biblio, "inexistant")
    ctx.registre = reg
    ctx.services["competences"] = biblio
    r = guide.competences_proposees(ctx)
    assert "convertir_image_jpg" in r.texte and "[déjà installée]" in r.texte
    r = guide.installer_competence_modele(ctx, "convertir_image_png")
    assert r.ok and "convertir_image_png" in biblio.competences


def test_outils_du_guide_inscrits():
    from macai.outils.base import charger_tous
    reg = charger_tous()
    for nom in ("guider", "montrer_element", "montrer_menu", "cliquer_libelle", "competences_proposees",
                "installer_competence_modele"):
        assert reg.get(nom) is not None, nom
    assert reg.get("guider").risque == Risque.LECTURE
    assert reg.get("installer_competence_modele").risque == Risque.CREATION
