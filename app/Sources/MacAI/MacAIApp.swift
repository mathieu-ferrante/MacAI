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
    lazy var indicateur = Indicateur()
    lazy var actions = Actions(etat: etat, panneau: panneau, indicateur: indicateur)
    let notifications = Notifications()

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
        raccourcis.surDebutTouche = { [weak self] in self?.actions.debutToucheMaintenue() }
        raccourcis.surFinTouche = { [weak self] in self?.actions.finToucheMaintenue() }
        raccourcis.surTexte = { [weak self] in self?.actions.menuTexte() }
        raccourcis.surZone = { [weak self] in self?.actions.regarderZone() }
        raccourcis.installer()
        // Tâches planifiées terminées en arrière-plan : notification macOS ; un clic montre le résultat.
        notifications.installer()
        notifications.surClic = { [weak self] description, texte in
            self?.actions.afficherResultatTache(description, texte)
        }
        etat.surTacheTerminee = { [weak self] description, texte, ok in
            self?.notifications.publier(description: description, texte: texte, ok: ok)
        }
        // Liste des tâches planifiées rafraîchie à l'ouverture d'un menu (dont le menu 🧠).
        NotificationCenter.default.addObserver(forName: NSMenu.didBeginTrackingNotification, object: nil,
                                               queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, self.etat.connecte else { return }
                Task { await self.etat.rafraichirTaches() }
            }
        }
        // Démarrage automatique à l'ouverture de session.
        // Une seule fois : si l'utilisateur le désactive dans Réglages > Ouverture, on respecte son choix.
        // Le drapeau n'est posé que si l'inscription a vraiment réussi (sinon on réessaiera au prochain lancement).
        if !UserDefaults.standard.bool(forKey: "ouvertureInscrite") {
            try? SMAppService.mainApp.register()
            let statut = SMAppService.mainApp.status
            if statut == .enabled || statut == .requiresApproval {
                UserDefaults.standard.set(true, forKey: "ouvertureInscrite")
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        etat.moteur.arreter()
    }

    /// Accessibilité (piloter les fenêtres, touche Fn) et Enregistrement de l'écran (vision) : demandés une
    /// fois par version de l'app (une nouvelle version signée peut devoir être autorisée à nouveau), pas à
    /// chaque lancement.
    private func demanderAutorisations() {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "?"
        let defauts = UserDefaults.standard
        guard defauts.string(forKey: "autorisationsDemandeesVersion") != version else { return }
        defauts.set(version, forKey: "autorisationsDemandeesVersion")
        let options = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        if !CGPreflightScreenCaptureAccess() {
            _ = CGRequestScreenCaptureAccess()
        }
    }
}

struct MenuMacAI: View {
    @EnvironmentObject var etat: Etat
    /// Rôle de la touche maintenue ("dicter" ou "parler") et touche choisie ("fn" ou "option_droite") :
    /// relus par Actions et Raccourcis à chaque appui.
    @AppStorage("roleFn") private var roleFn = "dicter"
    @AppStorage("touchePourParler") private var touche = "fn"

    var body: some View {
        Text(etat.connecte ? "MacAI — prêt (100 % local)" : "MacAI — \(etat.statutMoteur)")
        Divider()
        Button("Ouvrir le panneau   ⌥Espace") {
            Delegue.partage?.panneau.montrer()
        }
        Button("Annuler la dernière action") { Delegue.partage?.actions.annulerDerniereAction() }
            .disabled(!etat.connecte)
        Menu("Tâches planifiées") {
            if etat.taches.isEmpty { Text("Aucune tâche planifiée") }
            ForEach(etat.taches) { t in
                Menu(t.prochaine.isEmpty ? t.description : "\(t.description) — \(t.prochaine)") {
                    if !t.frequence.isEmpty { Text("Fréquence : \(t.frequence)") }
                    Button("Supprimer") { Delegue.partage?.actions.supprimerTache(t) }
                }
            }
        }
        Divider()
        Text("Écrire : ⌥Espace")
        Text(roleFn == "parler" ? "Parler à MacAI : ⌥⇧Espace ou \(nomTouche) maintenus"
                                : "Parler à MacAI : ⌥⇧Espace maintenus")
        if roleFn != "parler" { Text("Dicter : \(nomTouche) maintenue") }
        Text("Texte sélectionné : ⌥⇧T")
        Text("Zone de l'écran : ⌥⇧S")
        Toggle("Réponses à l'oral", isOn: $etat.modeOral)
        Menu("Touche \(nomTouche) maintenue") {
            Toggle("Dicter dans l'application", isOn: Binding(get: { roleFn != "parler" },
                                                               set: { if $0 { roleFn = "dicter" } }))
            Toggle("Parler à MacAI", isOn: Binding(get: { roleFn == "parler" },
                                                    set: { if $0 { roleFn = "parler" } }))
            Divider()
            Toggle("Utiliser Option droite au lieu de Fn", isOn: Binding(get: { touche == "option_droite" },
                                                                          set: { touche = $0 ? "option_droite" : "fn" }))
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

    private var nomTouche: String { touche == "option_droite" ? "Option droite" : "Fn" }
}
