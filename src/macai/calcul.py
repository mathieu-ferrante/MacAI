"""Calcul exact, sans modèle et sans eval : « combien font 5000-964 », « 12 fois 7 », « 20 % de 150 ».

Vu dans le journal du Mac : « combien font 5000-964 » partait en recherche web (prix d'une Porsche 964).
L'expression est analysée par `ast` et seuls nombres, + − × ÷, puissance, modulo et parenthèses sont permis.
"""
from __future__ import annotations

import ast
import math
import operator
import re

OPERATIONS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
              ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
MOTS = [(r"\bmultipli[ée]e? par\b|\bfois\b|×|\bx\b(?=\s*[\d(])", "*"), (r"\bdivis[ée]e? par\b|÷|:", "/"),
        (r"\bplus\b", "+"), (r"\bmoins\b|−|–", "-"), (r"\bau carr[ée]\b", "**2"), (r"\bau cube\b", "**3"),
        (r"\bpuissance\b|\^", "**"), (r"\bmodulo\b", "%")]


class CalculImpossible(ValueError):
    pass


def _evaluer(n):
    if isinstance(n, ast.Expression):
        return _evaluer(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return n.value
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
        v = _evaluer(n.operand)
        return v if isinstance(n.op, ast.UAdd) else -v
    if isinstance(n, ast.BinOp) and type(n.op) in OPERATIONS:
        a, b = _evaluer(n.left), _evaluer(n.right)
        if isinstance(n.op, ast.Pow) and (abs(b) > 100 or abs(a) > 1e6):
            raise CalculImpossible("puissance trop grande")
        try:
            return OPERATIONS[type(n.op)](a, b)
        except ZeroDivisionError:
            raise CalculImpossible("division par zéro") from None
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "sqrt" and len(n.args) == 1:
        v = _evaluer(n.args[0])
        if v < 0:
            raise CalculImpossible("racine d'un nombre négatif")
        return math.sqrt(v)
    raise CalculImpossible("expression non reconnue")


def expression(texte: str) -> str | None:
    """L'expression mathématique contenue dans une phrase française, ou None s'il n'y en a pas."""
    t = texte.lower().strip().rstrip(" ?!.=")
    t = re.sub(r"^(?:combien (?:font|fait|ca fait|ça fait|égale?|egale?)|calcule(?:-moi)?|fais le calcul(?: de)?|"
               r"c'est combien|ca fait combien|ça fait combien|quel est le r[ée]sultat de|r[ée]sultat de|"
               r"combien|calcul)\s*:?\s*", "", t)
    t = re.sub(r"\s*(?:=|ca fait combien|ça fait combien|font combien|fait combien|egale? combien|égale? combien)$",
               "", t)
    # 20 % de 150 → (20/100*150)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:de|d')\s*(\d+(?:[.,]\d+)?)", r"(\1/100*\2)", t)
    t = re.sub(r"\bla racine(?: carr[ée]e)? de\s*(\d+(?:[.,]\d+)?)|\bracine(?: carr[ée]e)? de\s*(\d+(?:[.,]\d+)?)",
               lambda m: f"sqrt({m.group(1) or m.group(2)})", t)
    for motif, signe in MOTS:
        t = re.sub(motif, f" {signe} ", t)
    t = re.sub(r"(?<=\d)\s(?=\d{3}\b)", "", t)          # 5 000 → 5000
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)               # virgule décimale
    t = re.sub(r"\s+", " ", t).strip()
    if not t or not re.fullmatch(r"[\d\s.+\-*/%()sqrt]+", t) or not re.search(r"\d", t) \
            or not re.search(r"[+\-*/%]|sqrt", t.lstrip("-")):
        return None
    return t


def calculer(texte: str) -> float | int:
    e = expression(texte)
    if e is None:
        raise CalculImpossible("pas de calcul dans cette phrase")
    if len(e) > 200:
        raise CalculImpossible("expression trop longue")
    try:
        arbre = ast.parse(e, mode="eval")
        v = _evaluer(arbre)
    except SyntaxError:
        raise CalculImpossible("expression mal formée") from None
    except RecursionError:
        raise CalculImpossible("expression trop imbriquée") from None
    if isinstance(v, int) and abs(v) > 10 ** 30:
        raise CalculImpossible("résultat trop grand")
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        v = int(v)
    return v


def en_francais(v) -> str:
    """1234.5 → « 1 234,5 » ; arrondi à 10 chiffres significatifs pour ne pas afficher 0,30000000000000004."""
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    texte = f"{v:,.10g}" if abs(v) < 1e15 else f"{v:.6e}"
    if "e" in texte:
        return texte.replace(".", ",")
    entier, _, dec = f"{float(texte.replace(',', '')):,.10f}".rstrip("0").partition(".")
    return entier.replace(",", " ") + ("," + dec if dec else "")
