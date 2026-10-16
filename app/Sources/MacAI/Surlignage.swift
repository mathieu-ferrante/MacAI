import AppKit

/// Cadre rouge posé sur une zone de l'écran (« c'est ici ») : fenêtre transparente qui laisse passer les
/// clics, ne prend jamais le focus et disparaît seule après 8 s (ou au surlignage suivant).
@MainActor
final class Surlignage {
    private var fenetre: NSPanel?
    private var generation = 0
    private static let hauteurEtiquette: CGFloat = 24
    private static let marge: CGFloat = 4

    /// `zone` : points, origine en haut à gauche de l'écran principal (celui de la barre des menus).
    func montrer(_ zone: CGRect, texte: String) {
        generation += 1
        let gen = generation
        guard zone.width > 0, zone.height > 0, let principal = NSScreen.screens.first else {
            masquer()
            return
        }
        // Coordonnées Cocoa : origine en bas à gauche de l'écran principal.
        let cadre = NSRect(x: zone.minX, y: principal.frame.maxY - zone.maxY, width: zone.width, height: zone.height)
            .insetBy(dx: -Surlignage.marge, dy: -Surlignage.marge)
        let texteNet = texte.trimmingCharacters(in: .whitespacesAndNewlines)
        let avecEtiquette = !texteNet.isEmpty
        // Étiquette au-dessus du cadre, ou en dessous s'il touche le haut de son écran.
        let ecran = NSScreen.screens.first { $0.frame.intersects(cadre) } ?? principal
        let enHaut = cadre.maxY + Surlignage.hauteurEtiquette + 2 <= ecran.frame.maxY
        let hauteurEtiquette = avecEtiquette ? Surlignage.hauteurEtiquette + 2 : 0
        let largeurEtiquette = avecEtiquette ? min(max(cadre.width, 120), 480) : 0
        var total = cadre
        total.size.width = max(cadre.width, largeurEtiquette)
        total.size.height += hauteurEtiquette
        if !enHaut { total.origin.y -= hauteurEtiquette }

        let f = fenetre ?? Surlignage.creerFenetre()
        fenetre = f
        f.setFrame(total, display: false)
        let vue = NSView(frame: NSRect(origin: .zero, size: total.size))
        let bordure = NSView(frame: NSRect(x: 0, y: enHaut ? 0 : hauteurEtiquette, width: cadre.width, height: cadre.height))
        bordure.wantsLayer = true
        bordure.layer?.borderColor = NSColor.systemRed.cgColor
        bordure.layer?.borderWidth = 3
        bordure.layer?.cornerRadius = 8
        vue.addSubview(bordure)
        if avecEtiquette {
            let etiquette = NSTextField(labelWithString: texteNet)
            etiquette.font = .systemFont(ofSize: 12, weight: .semibold)
            etiquette.textColor = .white
            etiquette.lineBreakMode = .byTruncatingTail
            etiquette.maximumNumberOfLines = 1
            let largeurTexte = min(etiquette.fittingSize.width, largeurEtiquette - 16)
            let fond = NSView(frame: NSRect(x: 0, y: enHaut ? cadre.height + 2 : 0,
                                            width: largeurTexte + 16, height: Surlignage.hauteurEtiquette))
            fond.wantsLayer = true
            fond.layer?.backgroundColor = NSColor.systemRed.cgColor
            fond.layer?.cornerRadius = 6
            etiquette.frame = NSRect(x: 8, y: (Surlignage.hauteurEtiquette - etiquette.fittingSize.height) / 2,
                                     width: largeurTexte, height: etiquette.fittingSize.height)
            fond.addSubview(etiquette)
            vue.addSubview(fond)
        }
        f.contentView = vue
        f.orderFrontRegardless()  // sans activer MacAI
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in
            MainActor.assumeIsolated {
                guard let self, self.generation == gen else { return }
                self.masquer()
            }
        }
    }

    func masquer() {
        generation += 1
        fenetre?.orderOut(nil)
    }

    private static func creerFenetre() -> NSPanel {
        let f = PanneauTraversant(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel],
                                  backing: .buffered, defer: true)
        f.isFloatingPanel = true
        f.level = .screenSaver
        f.backgroundColor = .clear
        f.isOpaque = false
        f.hasShadow = false
        f.ignoresMouseEvents = true  // les clics passent à l'application dessous
        f.hidesOnDeactivate = false
        f.isReleasedWhenClosed = false
        f.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        return f
    }
}

/// Fenêtre qui ne devient jamais active.
private final class PanneauTraversant: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}
