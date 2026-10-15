import Foundation
import SwiftUI

struct Etape: Identifiable {
    enum Statut { case enCours, ok, echec }
    let id = UUID()
    let outil: String
    var texte: String
    var statut: Statut
    var detail = ""
}

struct DemandeConfirmation: Identifiable {
    let id: String
    let phrase: String
}

/// État partagé de l'interface : conversation en cours, moteur, voix.
@MainActor
final class Etat: ObservableObject {
    @Published var saisie = ""
    @Published var derniereDemande = ""
    @Published var reponse = ""
    @Published var etapes: [Etape] = []
    @Published var confirmation: DemandeConfirmation?
    @Published var propositionCompetence = false
    @Published var souvenirsAppris: [String] = []
    @Published var occupe = false
    @Published var connecte = false
    @Published var statutMoteur = "Démarrage…"
    @Published var ecoute = false
    /// Incrémenté à chaque affichage du panneau : le champ de saisie reprend le focus.
    @Published var apparitions = 0
    @Published var modeOral: Bool = UserDefaults.standard.bool(forKey: "modeOral") {
        didSet { UserDefaults.standard.set(modeOral, forKey: "modeOral") }
    }

    let client = Client()
    let moteur = Moteur()
    let voix = Voix()
    private var finEcouteEnCours = false   // un seul finirEcoute() à la fois
    private var sessionEcoute = 0          // les résultats partiels d'une écoute finie sont ignorés
    private var arretDemande = false       // « Arrêté. » n'est pas lu à voix haute

    func demarrer() {
        moteur.surEtat = { [weak self] s in self?.statutMoteur = s }
        moteur.demarrer()
        Task { await boucleConnexion() }
    }

    /// Attend que le moteur publie son port, écoute ses événements, recommence s'il redémarre.
    private func boucleConnexion() async {
        while true {
            if client.chargerInfos() {
                if let infos = await client.lire("/etat") as? [String: Any] {
                    connecte = true
                    statutMoteur = "Prêt"
                    // Le moteur peut déjà travailler (reconnexion pendant une demande).
                    occupe = infos["occupe"] as? Bool ?? false
                    if !occupe { confirmation = nil }
                    // Compteur de relances remis à zéro seulement après 60 s de connexion continue :
                    // un moteur qui plante juste après son démarrage finit par être signalé.
                    let stabilite = Task { [weak self] in
                        try? await Task.sleep(nanoseconds: 60_000_000_000)
                        guard !Task.isCancelled else { return }
                        self?.moteur.reinitialiserRelances()
                    }
                    await client.ecouter { [weak self] evt in self?.traiter(evt) }
                    stabilite.cancel()
                    if occupe { demandeInterrompue() }
                }
                connecte = false
                client.oublierInfos()
                // Sans écraser un message du moteur (« s'arrête sans cesse »…) arrivé juste avant.
                if statutMoteur == "Prêt" { statutMoteur = "Reconnexion…" }
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
    }

    /// Flux coupé pendant une demande : plus de « fin » à attendre, on libère l'interface.
    private func demandeInterrompue() {
        occupe = false
        confirmation = nil
        for i in etapes.indices where etapes[i].statut == .enCours { etapes[i].statut = .echec }
        if reponse.isEmpty { reponse = "Le moteur s'est arrêté pendant la demande." }
    }

    // MARK: - Actions

    func envoyer(_ texte: String? = nil) {
        let t = (texte ?? saisie).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, connecte, !occupe else { return }
        saisie = ""
        derniereDemande = t
        reponse = ""
        etapes = []
        propositionCompetence = false
        souvenirsAppris = []
        arretDemande = false
        occupe = true
        Task {
            let r = await client.envoyer("/demande", ["texte": t])
            if r == nil || r?["erreur"] != nil {
                occupe = false
                reponse = (r?["erreur"] as? String) == "occupé" ? "Je termine la demande en cours." : "Le moteur ne répond pas."
            }
        }
    }

    func repondre(_ accepter: Bool) {
        guard let c = confirmation else { return }
        confirmation = nil
        Task { await client.envoyer("/confirmation", ["id": c.id, "accepter": accepter]) }
    }

    func arreter() {
        voix.taire()
        arretDemande = true
        guard connecte else {  // pas de moteur : rien ne renverra « fin »
            occupe = false
            return
        }
        Task { await client.envoyer("/arret") }
    }

    func creerCompetence() {
        propositionCompetence = false
        arretDemande = false
        occupe = true
        etapes = []
        Task {
            if await client.envoyer("/competence") == nil { occupe = false }
        }
    }

    // MARK: - Voix

    // Début et fin sont lancés de façon synchrone (pas dans une Task) : un appui puis un relâchement
    // rapides s'exécutent toujours dans cet ordre, et le micro ne peut pas rester ouvert.

    func commencerEcoute() {
        guard !ecoute, !finEcouteEnCours, connecte else { return }
        voix.taire()
        ecoute = true
        saisie = ""
        sessionEcoute += 1
        let session = sessionEcoute
        let tache = voix.ecouter { [weak self] partiel in
            guard let self, self.ecoute, self.sessionEcoute == session else { return }
            self.saisie = partiel
        }
        Task { [weak self] in
            do {
                try await tache.value
            } catch {
                guard let self, self.sessionEcoute == session else { return }
                self.ecoute = false
                self.reponse = "Micro indisponible : \(error.localizedDescription)"
            }
        }
    }

    func finirEcoute() {
        guard ecoute, !finEcouteEnCours else { return }
        finEcouteEnCours = true
        let fin = voix.terminer()
        Task { [weak self] in
            let texte = await fin.value
            guard let self else { return }
            self.ecoute = false
            self.finEcouteEnCours = false
            if !texte.isEmpty { self.envoyer(texte) }
        }
    }

    // MARK: - Événements du moteur

    func traiter(_ evt: [String: Any]) {
        let type = evt["type"] as? String ?? ""
        switch type {
        case "debut":
            occupe = true
            reponse = ""
            etapes = []
            souvenirsAppris = []
            propositionCompetence = false
            if let d = evt["demande"] as? String { derniereDemande = d }
        case "outil_debut":
            etapes.append(Etape(outil: evt["outil"] as? String ?? "", texte: evt["phrase"] as? String ?? "", statut: .enCours))
        case "outil_fin":
            if let i = etapes.lastIndex(where: { $0.statut == .enCours }) {
                let ok = evt["ok"] as? Bool ?? false
                etapes[i].statut = ok ? .ok : .echec
                if !ok { etapes[i].detail = evt["texte"] as? String ?? "" }
            }
        case "demande_confirmation":
            let phrase = evt["phrase"] as? String ?? "Action sensible"
            confirmation = DemandeConfirmation(id: evt["id"] as? String ?? "", phrase: phrase)
            if modeOral { voix.parler("Je dois confirmer : \(phrase)") }
        case "confirmation_expiree":
            confirmation = nil
        case "texte":
            reponse += evt["morceau"] as? String ?? ""
        case "proposition_competence":
            propositionCompetence = true
        case "souvenirs_appris":
            souvenirsAppris = evt["faits"] as? [String] ?? []
        case "erreur":
            reponse = evt["texte"] as? String ?? "Erreur."
        case "fin":
            for i in etapes.indices where etapes[i].statut == .enCours { etapes[i].statut = .echec }
            occupe = false
            confirmation = nil
            let texte = evt["texte"] as? String ?? ""
            reponse = texte
            if modeOral && !texte.isEmpty && !arretDemande { voix.parler(texte) }
            arretDemande = false
        default:
            break
        }
    }
}
