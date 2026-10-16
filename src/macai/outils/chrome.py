"""Chrome et web : ouvrir, chercher, YouTube, lire la page, cliquer, remplir ; lecture web sans navigateur.

Pilotage par AppleScript + JavaScript : l'utilisateur garde ses sessions (comptes connectés).
Prérequis une fois : Chrome > Présentation > Options pour les développeurs >
« Autoriser JavaScript à partir des Apple Events ».
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from ..mac import commun
from .base import ErreurOutil, Resultat, Risque, interdire_achat, interdire_donnees_bancaires, outil

AIDE_JS = ("Chrome bloque le pilotage des pages. Active une fois : menu Chrome > Présentation > "
           "Options pour les développeurs > « Autoriser JavaScript à partir des Apple Events ».")

INSTANTANE_JS = r"""
(() => {
  const sel = 'a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=tab],' +
              '[role=menuitem],[role=checkbox],[role=option],[contenteditable=true],summary';
  document.querySelectorAll('[data-macai]').forEach(e => e.removeAttribute('data-macai'));
  const out = []; let id = 0;
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight * 2.5) continue;
    const st = getComputedStyle(e);
    if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') continue;
    id++; e.setAttribute('data-macai', id);
    const label = (e.getAttribute('aria-label') || e.innerText || e.value || e.placeholder || e.title ||
                   e.name || e.alt || '').trim().replace(/\s+/g, ' ').slice(0, 90);
    const genre = e.tagName.toLowerCase() + (e.type && e.tagName !== 'BUTTON' ? ':' + e.type : '');
    out.push(id + ' [' + genre + '] ' + label + (e.tagName === 'A' && e.href ? '  → ' + e.href.slice(0, 80) : ''));
    if (id >= 150) break;
  }
  const texte = (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n');
  return JSON.stringify({titre: document.title, url: location.href, elements: out, texte: texte.slice(0, 7000)});
})()
"""


def _chrome() -> str:
    return "Google Chrome"


def chrome_js(ctx, script: str, delai: float = 20) -> str:
    app = ctx.config.chrome.get("application", _chrome()) if ctx else _chrome()
    try:
        return commun.osascript(
            f"tell application {commun.chaine_as(app)} to execute active tab of front window "
            f"javascript {commun.chaine_as(script)}", delai=delai)
    except ErreurOutil as e:
        if "JavaScript" in str(e) and ("Apple Events" in str(e) or "turned off" in str(e) or "désactiv" in str(e)):
            raise ErreurOutil(AIDE_JS) from e
        raise


def ouvrir_onglet(ctx, url: str) -> None:
    app = ctx.config.chrome.get("application", _chrome()) if ctx else _chrome()
    commun.osascript(f"""tell application {commun.chaine_as(app)}
    activate
    if (count of windows) = 0 then make new window
    tell front window
        if URL of active tab is "chrome://newtab/" then
            set URL of active tab to {commun.chaine_as(url)}
        else
            make new tab with properties {{URL:{commun.chaine_as(url)}}}
        end if
    end tell
end tell""")


def attendre_chargement(ctx, delai: float = 12) -> None:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        try:
            if chrome_js(ctx, "document.readyState") == "complete":
                return
        except ErreurOutil:
            pass
        time.sleep(0.4)


@outil("ouvrir_url", "Ouvre une adresse web dans Chrome (nouvel onglet).", "web",
       {"url": ("string", "adresse complète, ex. https://cad.onshape.com")}, risque=Risque.CREATION,
       annonce=lambda a: f"Ouvrir {a['url']}")
def ouvrir_url(ctx, url):
    if not re.match(r"^https?://", url):
        url = "https://" + url.lstrip("/")
    ouvrir_onglet(ctx, url)
    return f"{url} ouvert dans Chrome."


def url_recherche(requete: str, site: str = "google") -> str:
    q = urllib.parse.quote_plus(requete)
    return {"youtube": f"https://www.youtube.com/results?search_query={q}",
            "images": f"https://www.google.com/search?tbm=isch&q={q}",
            "maps": f"https://www.google.com/maps/search/{q}",
            "wikipedia": f"https://fr.wikipedia.org/w/index.php?search={q}"}.get(site, f"https://www.google.com/search?q={q}")


@outil("chrome_rechercher", "Lance une recherche dans Chrome sur Google, YouTube, Google Images, Maps ou Wikipédia.",
       "web", {"requete": ("string", "ce qu'on cherche"),
               "site": ("string", "où chercher", ["google", "youtube", "images", "maps", "wikipedia"])},
       requis=["requete"], risque=Risque.CREATION)
def chrome_rechercher(ctx, requete, site="google"):
    ouvrir_onglet(ctx, url_recherche(requete, site))
    return (f"Recherche « {requete} » ouverte sur {site.capitalize()} dans Chrome. Tu n'as PAS lu les résultats : "
            "pour répondre à une question, utilise recherche_web puis lire_page_web, ou dis que la page est ouverte.")


PREMIERE_VIDEO_JS = r"""
(() => {
  for (const a of document.querySelectorAll('ytd-video-renderer a#video-title, a#video-title')) {
    const h = a.href || '';
    if (h.includes('/watch?v=') && !a.closest('ytd-ad-slot-renderer')) { return h + '|' + (a.title || a.innerText).trim(); }
  }
  return '';
})()
"""


@outil("youtube_lire", "Cherche sur YouTube et lance directement la première vidéo trouvée.", "web",
       {"requete": ("string", "vidéo recherchée, ex. « Daft Punk Get Lucky »")}, risque=Risque.CREATION,
       annonce=lambda a: f"Lancer sur YouTube : {a['requete']}")
def youtube_lire(ctx, requete):
    ouvrir_onglet(ctx, url_recherche(requete, "youtube"))
    attendre_chargement(ctx)
    fin = time.monotonic() + 10
    while time.monotonic() < fin:
        try:
            trouve = chrome_js(ctx, PREMIERE_VIDEO_JS)
        except ErreurOutil as e:
            return Resultat(True, f"Résultats YouTube ouverts pour « {requete} », mais je ne peux pas cliquer : {e}")
        if trouve:
            url, _, titre = trouve.partition("|")
            chrome_js(ctx, f"location.href = {json.dumps(url)}")
            return Resultat(True, f"Lecture de « {titre} » sur YouTube.", {"url": url})
        time.sleep(0.5)
    return Resultat(True, f"Résultats YouTube ouverts pour « {requete} » (aucune vidéo cliquable trouvée).")


@outil("lire_page", "Lit la page Chrome active : titre, adresse, texte et liste numérotée des éléments "
       "cliquables (liens, boutons, champs) à utiliser avec cliquer_page et remplir_page.", "web", {})
def lire_page(ctx):
    brut = chrome_js(ctx, INSTANTANE_JS)
    try:
        d = json.loads(brut)
    except ValueError:
        raise ErreurOutil("Impossible de lire la page (aucune fenêtre Chrome ?).") from None
    texte = (f"Page : {d['titre']}\nAdresse : {d['url']}\n\nÉléments :\n" + "\n".join(d["elements"]) +
             f"\n\nTexte :\n{d['texte']}")
    return Resultat(True, texte, {"url": d["url"], "titre": d["titre"]})


def _element(n) -> str:
    return f"document.querySelector('[data-macai=\"{int(n)}\"]')"


@outil("cliquer_page", "Clique sur un élément de la page Chrome, par son numéro donné par lire_page.", "web",
       {"numero": ("integer", "numéro de l'élément")}, risque=Risque.MODIFICATION,
       annonce=lambda a: f"Cliquer sur l'élément {a['numero']} de la page")
def cliquer_page(ctx, numero):
    texte = chrome_js(ctx, f"(() => {{ const e = {_element(numero)}; if (!e) return ''; return ((e.innerText || '') "
                           f"+ ' ' + (e.getAttribute('aria-label') || '') + ' ' + (e.value || '')).slice(0, 300); }})()")
    interdire_achat(texte)
    r = chrome_js(ctx, f"(() => {{ const e = {_element(numero)}; if (!e) return 'absent'; "
                       f"e.scrollIntoView({{block: 'center'}}); e.click(); return 'ok'; }})()")
    if r == "absent":
        raise ErreurOutil(f"Élément {numero} introuvable : relis la page avec lire_page (elle a pu changer).")
    time.sleep(0.8)
    attendre_chargement(ctx, 6)
    return f"Clic sur l'élément {numero} effectué."


@outil("remplir_page", "Écrit un texte dans un champ de la page Chrome (numéro donné par lire_page), "
       "et valide avec Entrée si demandé.", "web",
       {"numero": ("integer", "numéro du champ"), "texte": ("string", "texte à écrire"),
        "valider": ("boolean", "appuyer sur Entrée ensuite")}, requis=["numero", "texte"],
       risque=Risque.MODIFICATION, annonce=lambda a: f"Écrire « {a['texte']} » dans le champ {a['numero']}")
def remplir_page(ctx, numero, texte, valider=False):
    interdire_donnees_bancaires(texte)
    interdire_achat(texte)
    js = f"""(() => {{
  const e = {_element(numero)}; if (!e) return 'absent';
  if (e.type === 'password') return 'motdepasse';
  e.focus();
  const t = {json.dumps(str(texte))};
  if (e.isContentEditable) {{ document.execCommand('insertText', false, t); }}
  else {{
    const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, t);
    e.dispatchEvent(new Event('input', {{bubbles: true}})); e.dispatchEvent(new Event('change', {{bubbles: true}}));
  }}
  if ({'true' if valider else 'false'}) {{
    e.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}}));
    if (e.form) e.form.requestSubmit ? e.form.requestSubmit() : e.form.submit();
  }}
  return 'ok';
}})()"""
    r = chrome_js(ctx, js)
    if r == "absent":
        raise ErreurOutil(f"Champ {numero} introuvable : relis la page avec lire_page.")
    if r == "motdepasse":
        raise ErreurOutil("C'est un champ de mot de passe : je ne le remplis pas, c'est à toi de le faire.")
    if valider:
        attendre_chargement(ctx, 8)
    return f"Texte écrit dans le champ {numero}" + (" et validé." if valider else ".")


@outil("naviguer_page", "Dans Chrome : page précédente, suivante, recharger, défiler vers le bas ou le haut.",
       "web", {"action": ("string", "action", ["retour", "suivant", "recharger", "bas", "haut"])},
       risque=Risque.CREATION)
def naviguer_page(ctx, action):
    js = {"retour": "history.back()", "suivant": "history.forward()", "recharger": "location.reload()",
          "bas": "window.scrollBy(0, innerHeight * 0.85)", "haut": "window.scrollBy(0, -innerHeight * 0.85)"}
    if action not in js:
        raise ErreurOutil(f"Action inconnue : {action}")
    chrome_js(ctx, js[action] + "; 'ok'")
    return "C'est fait."


@outil("onglets_chrome", "Liste les onglets ouverts dans Chrome, ou active / ferme l'un d'eux par son numéro.",
       "web", {"action": ("string", "action", ["lister", "activer", "fermer"]),
               "numero": ("integer", "numéro de l'onglet (pour activer ou fermer)")}, requis=["action"],
       risque=lambda a: Risque.MODIFICATION if a.get("action") == "fermer" else Risque.LECTURE)
def onglets_chrome(ctx, action, numero=0):
    app = commun.chaine_as(ctx.config.chrome.get("application", _chrome()))
    if action == "lister":
        brut = commun.osascript(f"""tell application {app}
    set res to ""
    repeat with t in tabs of front window
        set res to res & (title of t) & " — " & (URL of t) & linefeed
    end repeat
    return res
end tell""")
        lignes = [l for l in brut.splitlines() if l.strip()]
        return "\n".join(f"{i}. {l}" for i, l in enumerate(lignes, 1)) or "Aucun onglet."
    n = int(numero)
    if action == "activer":
        commun.osascript(f"tell application {app} to set active tab index of front window to {n}")
        return f"Onglet {n} activé."
    commun.osascript(f"tell application {app} to close tab {n} of front window")
    return f"Onglet {n} fermé."


# --- Web sans navigateur ------------------------------------------------------------

class _Texte(HTMLParser):
    IGNORE = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}

    def __init__(self):
        super().__init__()
        self.parties, self._pile = [], 0
        self.titre, self._dans_titre = "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORE:
            self._pile += 1
        self._dans_titre = tag == "title"
        if tag in ("p", "br", "li", "h1", "h2", "h3", "tr", "div"):
            self.parties.append("\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORE and self._pile:
            self._pile -= 1
        self._dans_titre = False

    def handle_data(self, data):
        if self._dans_titre:
            self.titre += data
        elif not self._pile:
            self.parties.append(data)


def html_vers_texte(page: str) -> tuple[str, str]:
    p = _Texte()
    p.feed(page)
    texte = re.sub(r"[ \t]+", " ", "".join(p.parties))
    return p.titre.strip(), re.sub(r"\n\s*\n+", "\n\n", texte).strip()


def telecharger_page(url: str, delai: float = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                                             "AppleWebKit/605.1.15 (KHTML, like Gecko) Safari/605.1.15",
                                               "Accept-Language": "fr-FR,fr;q=0.9"})
    with urllib.request.urlopen(req, timeout=delai) as r:
        if "html" not in r.headers.get("Content-Type", "html"):
            raise ErreurOutil("Ce lien n'est pas une page web.")
        return r.read(3_000_000).decode(r.headers.get_content_charset() or "utf-8", errors="replace")


@outil("lire_page_web", "Télécharge et lit le texte d'une page web sans l'ouvrir (articles, documentation…).",
       "web", {"url": ("string", "adresse de la page")}, mac_seulement=False)
def lire_page_web(ctx, url):
    url = url_publique(url)
    try:
        titre, texte = html_vers_texte(telecharger_page(url))
    except (OSError, ValueError) as e:
        raise ErreurOutil(f"Page inaccessible : {e}") from e
    return Resultat(True, f"{titre}\n{url}\n\n{texte[:12000]}", {"url": url})


def resultats_recherche(requete: str, nombre: int = 8) -> list[tuple[str, str, str]]:
    """(titre, lien, résumé) des premiers résultats DuckDuckGo (version HTML, sans JavaScript)."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(requete)
    try:
        page = telecharger_page(url)
    except (OSError, ValueError) as e:
        raise ErreurOutil(f"Recherche impossible (connexion ?) : {e}") from e
    resultats = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S):
        lien = m.group(1)
        if "uddg=" in lien:
            lien = urllib.parse.unquote(re.search(r"uddg=([^&]+)", lien).group(1))
        if "duckduckgo.com/y.js" in lien or "ad_provider" in lien:
            continue  # publicités
        titre = html.unescape(re.sub(r"<.*?>", "", m.group(2))).strip()
        resume = html.unescape(re.sub(r"<.*?>", "", m.group(3))).strip()
        resultats.append((titre, lien, resume))
        if len(resultats) >= nombre:
            break
    return resultats


@outil("recherche_web", "Cherche sur internet (DuckDuckGo) et renvoie les premiers résultats (titre, lien, "
       "résumé), sans ouvrir le navigateur.", "web", {"requete": ("string", "recherche")}, mac_seulement=False)
def recherche_web(ctx, requete):
    resultats = resultats_recherche(requete)
    return "\n".join(f"- {t}\n  {l}\n  {r}" for t, l, r in resultats) if resultats else "Aucun résultat."


def url_publique(url: str) -> str:
    """Refuse les adresses locales ou privées (le moteur d'IA, la box, le réseau local) : une page piégée ne doit
    pas pouvoir faire interroger le Mac lui-même."""
    import ipaddress
    import socket
    if not re.match(r"^https?://", url):
        url = "https://" + url
    hote = urllib.parse.urlparse(url).hostname or ""
    try:
        adresses = {i[4][0] for i in socket.getaddrinfo(hote, None)}
    except OSError as e:
        raise ErreurOutil(f"Adresse introuvable : {hote}") from e
    for a in adresses:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ErreurOutil(f"Adresse locale ou privée refusée : {hote}")
    return url


def passages_utiles(texte: str, question: str, nombre: int = 3, taille: int = 380) -> list[str]:
    """Les passages de la page qui partagent le plus de mots avec la question (sans modèle : instantané)."""
    from ..agent.routeur import normaliser
    mots = {m for m in re.findall(r"[a-z0-9]+", normaliser(question)) if len(m) > 3}
    morceaux, courant = [], ""
    for phrase in re.split(r"(?<=[.!?])\s+|\n+", texte):
        if len(courant) + len(phrase) > taille and courant:
            morceaux.append(courant.strip())
            courant = ""
        courant += " " + phrase
    if courant.strip():
        morceaux.append(courant.strip())
    import math
    jeux = [set(re.findall(r"[a-z0-9]+", normaliser(m))) for m in morceaux]
    # Mots rares dans la page = plus parlants (« poste », « Toulon » sont partout, « horaires » non).
    poids = {w: math.log(1 + len(jeux) / (1 + sum(w in j for j in jeux))) for w in mots}
    chiffres = re.compile(r"\b\d{1,2} ?h ?\d{0,2}\b|\b\d{1,2}:\d{2}\b|\d+[,.]?\d* ?(€|eur|euros?)\b|\b(19|20)\d{2}\b",
                          re.I)
    veut_chiffres = bool(re.search(r"horaire|heure|ouvert|ferme|prix|cout|tarif|combien|quand|date|annee",
                                   normaliser(question)))
    notes = []
    for i, (m, jeu) in enumerate(zip(morceaux, jeux)):
        note = sum(poids[w] for w in mots & jeu)
        if veut_chiffres and note > 0:
            note += min(len(chiffres.findall(m)), 4) * 0.6
        notes.append((note, i, m))
    notes.sort(key=lambda x: (-x[0], x[1]))
    gardes = sorted((i, m) for n, i, m in notes[:nombre] if n > 0)
    return [m for _, m in gardes]


@outil("rechercher_et_lire", "Répond à une question d'actualité ou factuelle (horaires, prix, dates, chiffres, "
       "personnes, définitions…) : cherche sur internet, lit les meilleures pages et renvoie les passages utiles "
       "avec leurs sources. Réponds ensuite en citant les sources.", "web",
       {"question": ("string", "la question, ex. « horaires de la poste de Toulon centre »")}, mac_seulement=False,
       mots_cles=["horaires", "prix", "combien coute", "actualite", "qui est", "c'est quand", "quand est",
                  "recherche sur internet", "cherche sur internet", "derniere version", "resultat du match"])
def rechercher_et_lire(ctx, question):
    from concurrent.futures import ThreadPoolExecutor
    resultats = resultats_recherche(question, nombre=6)
    if not resultats:
        return "Aucun résultat trouvé sur internet pour cette question."

    def lire(r):
        titre, lien, resume = r
        try:
            _, texte = html_vers_texte(telecharger_page(url_publique(lien)))
        except (ErreurOutil, OSError, ValueError):
            return titre, lien, [resume] if resume else []
        return titre, lien, passages_utiles(texte, question) or ([resume] if resume else [])

    with ThreadPoolExecutor(max_workers=3) as pool:
        lus = list(pool.map(lire, resultats[:3]))
    blocs = []
    for n, (titre, lien, passages) in enumerate(lus, 1):
        if passages:
            blocs.append(f"Source {n} : {titre} — {lien}\n" + "\n".join(f"« {p[:420]} »" for p in passages))
    if not blocs:
        return "Pages trouvées mais illisibles : " + ", ".join(l for _, l, _ in resultats[:3])
    return ("\n\n".join(blocs) + "\n\nRéponds à la question avec ces passages uniquement, en citant « Source N ». "
            "Si l'information n'y est pas, dis-le.")
