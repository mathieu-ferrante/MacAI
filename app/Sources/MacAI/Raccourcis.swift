import AppKit
import ApplicationServices
import Carbon.HIToolbox

/// Option + Espace (raccourci global Carbon : aucune autorisation requise) et touche maintenue pour parler.
@MainActor
final class Raccourcis {
    private var raccourci: EventHotKeyRef?
    private var gestionnaire: EventHandlerRef?
    private var moniteurGlobal: Any?
    private var moniteurLocal: Any?
    private var appuiDepuis: Date?
    private var ecouteLancee = false
    private var minuterie: Timer?

    var surRaccourci: (@MainActor () -> Void)?
    var surDebutParole: (@MainActor () -> Void)?
    var surFinParole: (@MainActor () -> Void)?

    /// Touche pour parler : "fn" (défaut) ou "option_droite".
    var touchePourParler: String = UserDefaults.standard.string(forKey: "touchePourParler") ?? "fn"

    func installer() {
        installerOptionEspace()
        installerPourParler()
    }

    // MARK: - Option + Espace

    private func installerOptionEspace() {
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let soi = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(GetApplicationEventTarget(), { _, _, donnees in
            guard let donnees else { return noErr }
            let r = Unmanaged<Raccourcis>.fromOpaque(donnees).takeUnretainedValue()
            Task { @MainActor in r.surRaccourci?() }
            return noErr
        }, 1, &type, soi, &gestionnaire)
        let id = EventHotKeyID(signature: OSType(0x4D414149), id: 1)  // 'MAAI'
        RegisterEventHotKey(UInt32(kVK_Space), UInt32(optionKey), id, GetApplicationEventTarget(), 0, &raccourci)
    }

    // MARK: - Touche maintenue pour parler

    private func installerPourParler() {
        // AppKit appelle ces moniteurs sur le fil principal.
        let traiter: (NSEvent) -> Void = { [weak self] e in
            MainActor.assumeIsolated { self?.changementModificateurs(e) }
        }
        // Surveillance globale : nécessite l'autorisation Accessibilité (demandée au premier lancement).
        moniteurGlobal = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged, handler: traiter)
        moniteurLocal = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged) { e in traiter(e); return e }
        if !AXIsProcessTrusted() { attendreAccessibilite(traiter) }
    }

    /// Le moniteur global ne reçoit rien tant que l'Accessibilité n'est pas accordée : on le réinstalle ensuite.
    private func attendreAccessibilite(_ traiter: @escaping (NSEvent) -> Void) {
        Task { @MainActor [weak self] in
            while !AXIsProcessTrusted() {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
            guard let self else { return }
            if let m = self.moniteurGlobal { NSEvent.removeMonitor(m) }
            self.moniteurGlobal = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged, handler: traiter)
        }
    }

    private func toucheEnfoncee(_ e: NSEvent) -> Bool? {
        switch touchePourParler {
        case "option_droite":
            guard e.keyCode == UInt16(kVK_RightOption) else { return nil }
            return e.modifierFlags.contains(.option)
        default:
            guard e.keyCode == UInt16(kVK_Function) else { return nil }
            return e.modifierFlags.contains(.function)
        }
    }

    private func changementModificateurs(_ e: NSEvent) {
        guard let enfoncee = toucheEnfoncee(e) else {
            // Autre touche combinée (ex. Fn + flèche) : ce n'est pas une prise de parole.
            if appuiDepuis != nil && !ecouteLancee { annulerAppui() }
            return
        }
        if enfoncee {
            appuiDepuis = Date()
            // Appui maintenu 0,3 s : on commence à écouter (un appui bref garde son rôle habituel).
            minuterie = Timer.scheduledTimer(withTimeInterval: 0.3, repeats: false) { [weak self] _ in
                MainActor.assumeIsolated {
                    guard let self, self.appuiDepuis != nil else { return }
                    self.ecouteLancee = true
                    self.surDebutParole?()
                }
            }
        } else {
            if ecouteLancee { surFinParole?() }
            annulerAppui()
        }
    }

    private func annulerAppui() {
        minuterie?.invalidate()
        minuterie = nil
        appuiDepuis = nil
        ecouteLancee = false
    }
}
