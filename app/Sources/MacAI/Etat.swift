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
    @Published var modeOral: Bool = UserDefaults.standard.bool(forKey: "modeOral") {
        didSet { UserDefaults.standard.set(modeOral, forKey: "modeOral") }
    }

    let client = Client()
    let moteur = Moteur()
    let voix = Voix()

    func demarrer() {
        moteur.surEtat = { [weak self] s in Task { @MainActor in self?.statutMoteur = s } }
        moteur.demarrer()
        Task { await boucleConnexion() }
    }

    /// Attend que le moteur publie son port, écoute ses événements, recommence s'il redémarre.
    private func boucleConnexion() async {
        while true {
            if client.chargerInfos() {
                if (await client.lire("/etat")) != nil {
                    connecte = true
                    statutMoteur = "Prêt"
                    moteur.reinitialiserRelances()
                    await client.ecouter { [weak self] evt in self?.traiter(evt) }
                }
                connecte = false
                client.oublierInfos()
                statutMoteur = "Reconnexion…"
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
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
        Task { await client.envoyer("/arret") }
    }

    func creerCompetence() {
        propositionCompetence = false
        occupe = true
        etapes = [Etape(outil: "creer_competence", texte: "Création de la compétence…", statut: .enCours)]
        Task { await client.envoyer("/competence") }
    }

    // MARK: - Voix

    func commencerEcoute() {
        guard !ecoute, connecte else { return }
        voix.taire()
        ecoute = true
        saisie = ""
        Task {
            do {
                try await voix.ecouter { [weak self] partiel in
                    Task { @MainActor in self?.saisie = partiel }
                }
            } catch {
                ecoute = false
                reponse = "Micro indisponible : \(error.localizedDescription)"
            }
        }
    }

    func finirEcoute() {
        guard ecoute else { return }
        Task {
            let texte = await voix.terminer()
            ecoute = false
            if !texte.isEmpty { envoyer(texte) }
        }
    }

    // MARK: - Événements du moteur

    func traiter(_ evt: [String: Any]) {
        let type = evt["type"] as? String ?? ""
        switch type {
        case "debut":
            occupe = true
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
            occupe = false
            confirmation = nil
            let texte = evt["texte"] as? String ?? ""
            reponse = texte
            if modeOral && !texte.isEmpty { voix.parler(texte) }
        default:
            break
        }
    }
}
