"""Apple Vision (natif, local, sur le Neural Engine) : texte dans les images et étiquettes de contenu."""
from __future__ import annotations

from pathlib import Path

from ..outils.base import ErreurOutil


def _vision():
    try:
        import Vision  # pyobjc-framework-Vision
        from Foundation import NSURL
    except ImportError as e:
        raise ErreurOutil("Apple Vision indisponible (macOS uniquement).") from e
    return Vision, NSURL


def _gestionnaire(source):
    Vision, NSURL = _vision()
    if isinstance(source, (str, Path)):
        return Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(source)), None)
    return Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(source, None)


def lire_texte(source, rapide: bool = False) -> str:
    """OCR d'une image (chemin ou CGImage) ; renvoie les lignes dans l'ordre de lecture."""
    Vision, _ = _vision()
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast if rapide
                             else Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(["fr-FR", "en-US"])
    req.setUsesLanguageCorrection_(True)
    ok, err = _gestionnaire(source).performRequests_error_([req], None)
    if not ok:
        raise ErreurOutil(f"Lecture du texte impossible : {err}")
    obs = sorted(req.results() or [], key=lambda o: (-round(o.boundingBox().origin.y, 2), o.boundingBox().origin.x))
    return "\n".join(o.topCandidates_(1)[0].string() for o in obs if o.topCandidates_(1))


def etiquettes(source, seuil: float = 0.25, maximum: int = 12) -> list[str]:
    """Ce que montre l'image (« cat », « sofa », « beach »…), en anglais — l'index est multilingue."""
    Vision, _ = _vision()
    req = Vision.VNClassifyImageRequest.alloc().init()
    ok, err = _gestionnaire(source).performRequests_error_([req], None)
    if not ok:
        return []
    res = sorted(req.results() or [], key=lambda o: -o.confidence())
    return [o.identifier().replace("_", " ") for o in res if o.confidence() >= seuil][:maximum]


def images_pdf(chemin: Path, pages_max: int = 10):
    """Rend les pages d'un PDF scanné en images pour l'OCR."""
    try:
        import Quartz
        from Foundation import NSURL
    except ImportError as e:
        raise ErreurOutil("Rendu PDF indisponible (macOS uniquement).") from e
    doc = Quartz.PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(str(chemin)))
    if doc is None:
        return
    for i in range(min(doc.pageCount(), pages_max)):
        page = doc.pageAtIndex_(i)
        boite = page.boundsForBox_(Quartz.kPDFDisplayBoxMediaBox)
        echelle = 2000 / max(boite.size.width, boite.size.height, 1)
        img = page.thumbnailOfSize_forBox_((boite.size.width * echelle, boite.size.height * echelle),
                                           Quartz.kPDFDisplayBoxMediaBox)
        res = img.CGImageForProposedRect_context_hints_(None, None, None)
        cg = res[0] if isinstance(res, tuple) else res  # pyobjc renvoie (image, rect) selon la version
        if cg is not None:
            yield cg


def ocr_pdf(chemin: Path, pages_max: int = 10) -> str:
    return "\n\n".join(lire_texte(cg) for cg in images_pdf(chemin, pages_max))
