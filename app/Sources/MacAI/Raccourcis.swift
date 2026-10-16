import AppKit
import ApplicationServices
import Carbon.HIToolbox

/// Option + Espace : ouvre le panneau. Option + Maj + Espace maintenus : parler à MacAI tant que les touches
/// sont enfoncées. Option + Maj + T : texte sélectionné. Option + Maj + S : zone de l'écran (raccourcis globaux
/// Carbon : aucune autorisation requise). Touche Fn (ou Option droite) maintenue : dicter, ou parler à MacAI.
@MainActor
final class Raccourcis {
    private var raccourci: EventHotKeyRef?
    private var raccourciParole: EventHotKeyRef?
    private var raccourciTexte: EventHotKeyRef?
    private var raccourciZone: EventHotKeyRef?
    private var paroleRaccourciEnCours = false
    private var gestionnaire: EventHandlerRef?
    private var moniteurGlobal: Any?
    private var moniteurLocal: Any?
    private var moniteurTouchesGlobal: Any?
    private var moniteurTouchesLocal: Any?
    private var appuiDepuis: Date?
    private var ecouteLancee = false
    private var minuterie: Timer?

    var surRaccourci: (@MainActor () -> Void)?
    var surDebutParole: (@MainActor () -> Void)?
    var surFinParole: (@MainActor () -> Void)?
    /// Touche maintenue (Fn ou Option droite) : son rôle (dicter ou parler) est choisi par l'appelant.
    var surDebutTouche: (@MainActor () -> Void)?
    var surFinTouche: (@MainActor () -> Void)?
    /// Appui (même bref) sur la touche pour parler : la voix de MacAI se tait tout de suite.
    var surAppuiTouche: (@MainActor () -> Void)?
    /// Échap, dans n'importe quelle application : coupe la voix ou l'écoute automatique.
    var surEchap: (@MainActor () -> Void)?
    var surTexte: (@MainActor () -> Void)?
    var surZone: (@MainActor () -> Void)?

    /// Touche maintenue : "fn" (défaut) ou "option_droite". Relue à chaque appui (réglée depuis le menu).
    var touchePourParler: String { UserDefaults.standard.string(forKey: "touchePourParler") ?? "fn" }

    func installer() {
        installerOptionEspace()
        installerPourParler()
    }

    // MARK: - Option + Espace

    private static let idPanneau: UInt32 = 1
    private static let idParole: UInt32 = 2
    private static let idTexte: UInt32 = 3
    private static let idZone: UInt32 = 4

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
        RegisterEventHotKey(UInt32(kVK_ANSI_T), UInt32(optionKey | shiftKey),
                            EventHotKeyID(signature: signature, id: Raccourcis.idTexte),
                            GetApplicationEventTarget(), 0, &raccourciTexte)
        RegisterEventHotKey(UInt32(kVK_ANSI_S), UInt32(optionKey | shiftKey),
                            EventHotKeyID(signature: signature, id: Raccourcis.idZone),
                            GetApplicationEventTarget(), 0, &raccourciZone)
    }

    private func raccourciActive(_ id: UInt32, appui: Bool) {
        switch (id, appui) {
        case (Raccourcis.idPanneau, true):
            surRaccourci?()
        case (Raccourcis.idParole, true):
            // La répétition automatique du clavier renvoie des « appuis » : on n'écoute qu'une fois.
            guard !paroleRaccourciEnCours else { return }
            paroleRaccourciEnCours = true
            surAppuiTouche?()
            surDebutParole?()
        case (Raccourcis.idParole, false):
            guard paroleRaccourciEnCours else { return }
            paroleRaccourciEnCours = false
            surFinParole?()
        case (Raccourcis.idTexte, true):
            surTexte?()
        case (Raccourcis.idZone, true):
            surZone?()
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
        // Une vraie touche frappée pendant l'appui (Fn + flèche, Fn + Effacer, Option droite pour { } [ ]
        // sur clavier français) : ce n'est pas une prise de parole. Seuls comptent le fait qu'une touche soit
        // frappée et s'il s'agit d'Échap (qui coupe la voix) ; rien n'est lu ni gardé.
        let touche: (NSEvent) -> Void = { [weak self] e in
            let echap = e.keyCode == UInt16(kVK_Escape)
            MainActor.assumeIsolated {
                if echap { self?.surEchap?() }
                self?.toucheFrappee()
            }
        }
        // Surveillance globale : nécessite l'autorisation Accessibilité (demandée au premier lancement).
        installerMoniteursGlobaux(traiter, touche)
        moniteurLocal = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged) { e in traiter(e); return e }
        moniteurTouchesLocal = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { e in touche(e); return e }
        if !AXIsProcessTrusted() { attendreAccessibilite(traiter, touche) }
    }

    private func installerMoniteursGlobaux(_ traiter: @escaping (NSEvent) -> Void, _ touche: @escaping (NSEvent) -> Void) {
        if let m = moniteurGlobal { NSEvent.removeMonitor(m) }
        if let m = moniteurTouchesGlobal { NSEvent.removeMonitor(m) }
        moniteurGlobal = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged, handler: traiter)
        moniteurTouchesGlobal = NSEvent.addGlobalMonitorForEvents(matching: .keyDown, handler: touche)
    }

    /// Les moniteurs globaux ne reçoivent rien tant que l'Accessibilité n'est pas accordée : on les réinstalle
    /// ensuite. Vérification toutes les 2 s pendant 10 minutes au plus (sinon : au prochain lancement).
    private func attendreAccessibilite(_ traiter: @escaping (NSEvent) -> Void, _ touche: @escaping (NSEvent) -> Void) {
        Task { @MainActor [weak self] in
            var essais = 0
            while !AXIsProcessTrusted() {
                essais += 1
                if essais > 300 { return }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
            self?.installerMoniteursGlobaux(traiter, touche)
        }
    }

    private func toucheFrappee() {
        if appuiDepuis != nil && !ecouteLancee { annulerAppui() }
    }

    private func toucheEnfoncee(_ e: NSEvent) -> Bool? {
        switch touchePourParler {
        case "option_droite":
            guard e.keyCode == UInt16(kVK_RightOption) else { return nil }
            // Drapeau propre à l'Option droite (NX_DEVICERALTKEYMASK) : l'Option gauche maintenue
            // n'empêche pas de voir le relâchement.
            return e.modifierFlags.rawValue & 0x40 != 0
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
            surAppuiTouche?()
            minuterie?.invalidate()
            appuiDepuis = Date()
            // Appui maintenu 0,3 s : on commence à écouter (un appui bref garde son rôle habituel).
            minuterie = Timer.scheduledTimer(withTimeInterval: 0.3, repeats: false) { [weak self] _ in
                MainActor.assumeIsolated {
                    guard let self, self.appuiDepuis != nil else { return }
                    self.ecouteLancee = true
                    self.surDebutTouche?()
                }
            }
        } else {
            if ecouteLancee { surFinTouche?() }
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
