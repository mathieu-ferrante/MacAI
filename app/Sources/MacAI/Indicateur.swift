import AppKit
import SwiftUI

/// Petit indicateur flottant en haut de l'écran (dictée, texte corrigé, erreurs). Il ne prend jamais le focus :
/// l'application de l'utilisateur reste devant et reçoit le texte dicté.
final class Indicateur: NSPanel {
    private var generation = 0   // un masquage différé ancien ne cache pas un message plus récent
    private let hote = NSHostingView(rootView: VueIndicateur(texte: "", symbole: "mic.fill", couleur: .red))
    /// 0 : indicateur principal ; 1 : juste en dessous (démonstration en cours, permanent).
    private let rang: Int

    init(rang: Int = 0) {
        self.rang = rang
        super.init(contentRect: NSRect(x: 0, y: 0, width: 200, height: 36),
                   styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: true)
        isFloatingPanel = true
        level = .statusBar
        backgroundColor = .clear
        isOpaque = false
        hasShadow = true
        ignoresMouseEvents = true
        hidesOnDeactivate = false
        isReleasedWhenClosed = false
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        contentView = hote
    }

    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    /// Affiche `texte` ; masqué automatiquement après `duree` secondes si elle est donnée.
    func montrer(_ texte: String, symbole: String, couleur: Color = .accentColor, duree: TimeInterval? = nil) {
        generation += 1
        let gen = generation
        hote.rootView = VueIndicateur(texte: texte, symbole: symbole, couleur: couleur)
        let taille = hote.fittingSize
        let largeur = min(max(taille.width, 120), 560)
        let souris = NSEvent.mouseLocation
        let ecran = NSScreen.screens.first { NSMouseInRect(souris, $0.frame, false) } ?? NSScreen.main
        if let f = ecran?.visibleFrame {
            setFrame(NSRect(x: f.midX - largeur / 2, y: f.maxY - taille.height - 10 - CGFloat(rang) * 46, width: largeur, height: taille.height),
                     display: true)
        }
        orderFrontRegardless()  // sans activer MacAI
        if let duree {
            DispatchQueue.main.asyncAfter(deadline: .now() + duree) { [weak self] in
                MainActor.assumeIsolated {
                    guard let self, self.generation == gen else { return }
                    self.orderOut(nil)
                }
            }
        }
    }

    func masquer() {
        generation += 1
        orderOut(nil)
    }

    func erreur(_ texte: String) {
        montrer(texte, symbole: "exclamationmark.triangle.fill", couleur: .orange, duree: 4)
    }

    func reussite(_ texte: String) {
        montrer(texte, symbole: "checkmark.circle.fill", couleur: .green, duree: 2.5)
    }
}

struct VueIndicateur: View {
    let texte: String
    let symbole: String
    let couleur: Color

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbole).foregroundStyle(couleur)
            // Texte long (dictée) : on garde la fin, c'est ce qui vient d'être dit.
            Text(texte).lineLimit(1).truncationMode(.head)
        }
        .font(.callout)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .frame(maxWidth: 560)
        .background(Capsule().fill(.regularMaterial))
    }
}
