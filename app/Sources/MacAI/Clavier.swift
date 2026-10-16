import AppKit
import Carbon.HIToolbox

/// Frappes clavier envoyées à l'application de devant (autorisation Accessibilité de l'app).
@MainActor
enum Clavier {
    /// Tape un texte Unicode au curseur, quelle que soit la disposition du clavier (AZERTY…), par morceaux
    /// de 20 unités UTF-16 au plus (comme taper() du moteur), sans couper un caractère composé.
    static func taper(_ texte: String) async {
        var morceaux: [[UniChar]] = []
        var courant: [UniChar] = []
        for c in texte {
            let u = Array(String(c).utf16)
            if courant.count + u.count > 20 {
                morceaux.append(courant)
                courant = []
            }
            courant += u
        }
        if !courant.isEmpty { morceaux.append(courant) }
        let source = CGEventSource(stateID: .hidSystemState)
        for m in morceaux {
            for appui in [true, false] {
                guard let e = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: appui) else { continue }
                e.flags = []  // aucune touche de modification (Fn, Option) ne s'ajoute au texte
                m.withUnsafeBufferPointer { e.keyboardSetUnicodeString(stringLength: m.count, unicodeString: $0.baseAddress) }
                e.post(tap: .cghidEventTap)
            }
            try? await Task.sleep(nanoseconds: 15_000_000)
        }
    }

    /// Cmd + C dans l'application de devant : la sélection passe dans le presse-papiers.
    static func copierSelection() {
        let source = CGEventSource(stateID: .hidSystemState)
        for appui in [true, false] {
            guard let e = CGEvent(keyboardEventSource: source, virtualKey: CGKeyCode(kVK_ANSI_C), keyDown: appui) else { continue }
            e.flags = .maskCommand
            e.post(tap: .cghidEventTap)
        }
    }
}
