import AppKit
import ApplicationServices
import Carbon.HIToolbox

/// Option + Espace : ouvre le panneau. Option + Maj + Espace maintenus : parler tant que les touches sont
/// enfoncées (raccourcis globaux Carbon : aucune autorisation requise). Touche Fn maintenue : parler aussi.
@MainActor
final class Raccourcis {
    private var raccourci: EventHotKeyRef?
    private var raccourciParole: EventHotKeyRef?
    private var paroleRaccourciEnCours = false
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

    private static let idPanneau: UInt32 = 1
    private static let idParole: UInt32 = 2

    private func installerOptionEspace() {
        var types = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
                     EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))]
        let soi = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(GetApplicationEventTarget(), { _, evenement, donnees in
            guard let donnees, let evenement else { return noErr }
            let r = Unmanaged<Raccourcis>.fromOpaque(donnees).takeUnretainedValue()
            var id = EventHotKeyID()
            GetEventParameter(evenement, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                              nil, MemoryLayout<EventHotKeyID>.size, nil, &id)
            let appui = GetEventKind(evenement) == UInt32(kEventHotKeyPressed)
            Task { @MainActor in r.raccourciActive(id.id, appui: appui) }
            return noErr
        }, types.count, &types, soi, &gestionnaire)
        let signature = OSType(0x4D414149)  // 'MAAI'
        RegisterEventHotKey(UInt32(kVK_Space), UInt32(optionKey), EventHotKeyID(signature: signature, id: Raccourcis.idPanneau),
                            GetApplicationEventTarget(), 0, &raccourci)
        RegisterEventHotKey(UInt32(kVK_Space), UInt32(optionKey | shiftKey),
                            EventHotKeyID(signature: signature, id: Raccourcis.idParole),
                            GetApplicationEventTarget(), 0, &raccourciParole)
    }

    private func raccourciActive(_ id: UInt32, appui: Bool) {
        switch (id, appui) {
        case (Raccourcis.idPanneau, true):
            surRaccourci?()
        case (Raccourcis.idParole, true):
            // La répétition automatique du clavier renvoie des « appuis » : on n'écoute qu'une fois.
            guard !paroleRaccourciEnCours else { return }
            paroleRaccourciEnCours = true
            surDebutParole?()
        case (Raccourcis.idParole, false):
            guard paroleRaccourciEnCours else { return }
            paroleRaccourciEnCours = false
            surFinParole?()
        default:
            break
        }
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
