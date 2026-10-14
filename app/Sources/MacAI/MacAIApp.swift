import AppKit
import ApplicationServices
import ServiceManagement
import SwiftUI

@main
struct MacAIApp: App {
    @NSApplicationDelegateAdaptor(Delegue.self) var delegue

    var body: some Scene {
        MenuBarExtra {
            MenuMacAI().environmentObject(delegue.etat)
        } label: {
            Image(systemName: "brain.head.profile")
        }
    }
}

@MainActor
final class Delegue: NSObject, NSApplicationDelegate {
    static private(set) var partage: Delegue?
    let etat = Etat()
    let raccourcis = Raccourcis()
    lazy var panneau = Panneau(etat: etat)

    func applicationDidFinishLaunching(_ notification: Notification) {
        Delegue.partage = self
        NSApp.setActivationPolicy(.accessory)  // pas d'icône dans le Dock
        demanderAutorisations()
        etat.demarrer()
        raccourcis.surRaccourci = { [weak self] in self?.panneau.basculer() }
        raccourcis.surDebutParole = { [weak self] in
            guard let self else { return }
            self.panneau.montrer()
            self.etat.commencerEcoute()
        }
        raccourcis.surFinParole = { [weak self] in self?.etat.finirEcoute() }
        raccourcis.installer()
        // Démarrage automatique à l'ouverture de session.
        // Une seule fois : si l'utilisateur le désactive dans Réglages > Ouverture, on respecte son choix.
        if !UserDefaults.standard.bool(forKey: "ouvertureInscrite") {
            try? SMAppService.mainApp.register()
            UserDefaults.standard.set(true, forKey: "ouvertureInscrite")
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        etat.moteur.arreter()
    }

    /// Accessibilité (piloter les fenêtres, touche Fn) et Enregistrement de l'écran (vision) : demandés une fois.
    private func demanderAutorisations() {
        let options = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        if !CGPreflightScreenCaptureAccess() {
            _ = CGRequestScreenCaptureAccess()
        }
    }
}

struct MenuMacAI: View {
    @EnvironmentObject var etat: Etat

    var body: some View {
        Text(etat.connecte ? "MacAI — prêt (100 % local)" : "MacAI — \(etat.statutMoteur)")
        Divider()
        Button("Ouvrir le panneau   ⌥Espace") {
            Delegue.partage?.panneau.montrer()
        }
        Toggle("Réponses à l'oral", isOn: $etat.modeOral)
        Menu("Touche pour parler") {
            Button("Fn (maintenue)") { choisirTouche("fn") }
            Button("Option droite (maintenue)") { choisirTouche("option_droite") }
        }
        Divider()
        Button("Indexer mes fichiers maintenant") { Task { await etat.client.envoyer("/indexer") } }
        Button("Ouvrir les réglages (macai.toml)") {
            NSWorkspace.shared.open(Moteur.dossier.appendingPathComponent("macai.toml"))
        }
        Button("Ouvrir le journal") {
            NSWorkspace.shared.open(Moteur.dossier.appendingPathComponent("moteur.log"))
        }
        Button("Redémarrer le moteur") { etat.moteur.redemarrer() }
        Divider()
        Button("Quitter MacAI") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }

    private func choisirTouche(_ t: String) {
        UserDefaults.standard.set(t, forKey: "touchePourParler")
        Delegue.partage?.raccourcis.touchePourParler = t
    }
}
