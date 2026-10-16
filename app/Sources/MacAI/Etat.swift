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

/// Tâche planifiée du moteur (GET /taches).
struct TachePlanifiee: Identifiable {
    let id: String
    let description: String
    let frequence: String
    let prochaine: String
}

/// Le panneau attend une consigne pour autre chose qu'une demande ordinaire.
enum Attente {
    case texte                // consigne libre sur le texte sélectionné
    case image(URL)           // question sur une zone de l'écran capturée

    var invite: String {
        switch self {
        case .texte: return "Que faire du texte sélectionné ? (ex. : mets-le en liste à puces)"
        case .image: return "Ta question sur la zone capturée…"
        }
    }
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
    @Published var attente: Attente?
    @Published var taches: [TachePlanifiee] = []
    @Published var modeOral: Bool = UserDefaults.standard.bool(forKey: "modeOral") {
        didSet { UserDefaults.standard.set(modeOral, forKey: "modeOral") }
    }

    let client = Client()
    let moteur = Moteur()
    let voix = Voix()
    private var finEcouteEnCours = false   // un seul finirEcoute() à la fois
    private var sessionEcoute = 0          // les résultats partiels d'une écoute finie sont ignorés
    private var arretDemande = false       // « Arrêté. » n'est pas lu à voix haute
    private var dictee = false             // dictée en cours (le texte part dans l'application de devant)
    /// Demande discrète (texte remplacé ou copié) : pas de panneau, message affiché par l'indicateur à la fin.
    private var messageDiscret: String?
    private var erreurDiscrete: String?
    /// Capture d'écran envoyée au moteur : effacée à la fin de la demande.
    private var fichierEnCours: URL?

    /// Consigne tapée (ou dite) alors que le panneau attendait autre chose qu'une demande.
    var surConsigne: (@MainActor (Attente, String) -> Void)?
    /// Fin d'une demande discrète : (réussite, message).
    var surFinDiscrete: (@MainActor (Bool, String) -> Void)?
    /// Tâche planifiée terminée en arrière-plan : (description, texte, réussite).
    var surTacheTerminee: (@MainActor (String, String, Bool) -> Void)?

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
                    Task { await rafraichirTaches() }
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
        effacerFichierEnCours()
        if messageDiscret != nil {
            messageDiscret = nil
            surFinDiscrete?(false, "Le moteur s'est arrêté pendant la demande.")
        }
    }

    private func effacerFichierEnCours() {
        if let f = fichierEnCours { try? FileManager.default.removeItem(at: f) }
        fichierEnCours = nil
    }

    // MARK: - Actions

    func envoyer(_ texte: String? = nil) {
        let t = (texte ?? saisie).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, connecte, !occupe else { return }
        if let a = attente {  // consigne pour le texte sélectionné ou la zone capturée
            attente = nil
            saisie = ""
            surConsigne?(a, t)
            return
        }
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

    /// Lance une demande spéciale (/texte, /image) et renvoie nil si le moteur l'a acceptée, sinon le message
    /// d'erreur à afficher. `discret` : message de réussite pour l'indicateur (le panneau ne s'ouvre pas).
    /// `fichier` : capture effacée à la fin de la demande (ou tout de suite si elle est refusée).
    func lancer(_ chemin: String, _ corps: [String: Any], libelle: String, discret: String? = nil,
                fichier: URL? = nil) async -> String? {
        guard connecte else {
            if let fichier { try? FileManager.default.removeItem(at: fichier) }
            return "MacAI n'est pas encore prêt."
        }
        guard !occupe else {
            if let fichier { try? FileManager.default.removeItem(at: fichier) }
            return "Je termine la demande en cours."
        }
        attente = nil
        saisie = ""
        derniereDemande = libelle
        reponse = ""
        etapes = []
        propositionCompetence = false
        souvenirsAppris = []
        arretDemande = false
        messageDiscret = discret
        erreurDiscrete = nil
        fichierEnCours = fichier
        occupe = true
        // Les événements (« debut », « fin »…) peuvent arriver avant la réponse : tout est prêt avant l'envoi.
        let (statut, json) = await client.poster(chemin, corps)
        if statut != 0 && statut < 300 && json?["erreur"] == nil { return nil }
        let erreur = json?["erreur"] as? String
        let message = statut == 0 ? "Le moteur ne répond pas."
            : erreur == "occupé" ? "Je termine la demande en cours." : (erreur ?? "Le moteur a refusé la demande.")
        occupe = false  // comme pour /demande : rien ne renverra « fin »
        reponse = message
        messageDiscret = nil
        if fichierEnCours == fichier { effacerFichierEnCours() }
        return message
    }

    func rafraichirTaches() async {
        guard let liste = await client.lire("/taches") as? [[String: Any]] else { return }
        taches = liste.compactMap { t in
            guard let id = t["id"] as? String else { return nil }
            return TachePlanifiee(id: id, description: t["description"] as? String ?? "Tâche",
                                  frequence: t["frequence"] as? String ?? "",
                                  prochaine: t["prochaine"] as? String ?? "")
        }
    }

    /// Supprime une tâche planifiée ; renvoie nil si c'est fait, sinon le message d'erreur.
    func supprimerTache(_ id: String) async -> String? {
        let (statut, json) = await client.poster("/taches/supprimer", ["id": id])
        await rafraichirTaches()
        if statut != 0 && statut < 300 && json?["erreur"] == nil { return nil }
        return statut == 0 ? "Le moteur ne répond pas." : (json?["erreur"] as? String ?? "Suppression impossible.")
    }

    /// Annule la dernière action réversible sur les fichiers : (réussite, texte du moteur).
    func annulerDerniereAction() async -> (Bool, String) {
        let (statut, json) = await client.poster("/annuler")
        guard statut != 0 else { return (false, "Le moteur ne répond pas.") }
        let texte = json?["texte"] as? String ?? json?["erreur"] as? String ?? "Rien à annuler."
        return (json?["ok"] as? Bool ?? false, texte)
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
        guard !ecoute, !dictee, !finEcouteEnCours, connecte else { return }
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

    // MARK: - Dictée

    // Mêmes règles que l'écoute : compteur de session, un seul arrêt à la fois. Le moteur n'est pas utilisé :
    // la dictée marche même s'il redémarre.

    /// Renvoie false si une écoute ou une dictée est déjà en cours.
    @discardableResult
    func commencerDictee(_ surPartiel: @escaping @MainActor (String) -> Void,
                         erreur surErreur: @escaping @MainActor (String) -> Void) -> Bool {
        guard !ecoute, !dictee, !finEcouteEnCours else { return false }
        voix.taire()
        dictee = true
        sessionEcoute += 1
        let session = sessionEcoute
        let tache = voix.ecouter { [weak self] partiel in
            guard let self, self.dictee, self.sessionEcoute == session else { return }
            surPartiel(partiel)
        }
        Task { [weak self] in
            do {
                try await tache.value
            } catch {
                guard let self, self.sessionEcoute == session else { return }
                self.dictee = false
                surErreur("Micro indisponible : \(error.localizedDescription)")
            }
        }
        return true
    }

    /// Arrête le micro et passe le texte final (éventuellement vide) à `surTexte`.
    func finirDictee(_ surTexte: @escaping @MainActor (String) -> Void) {
        guard dictee, !finEcouteEnCours else { return }
        finEcouteEnCours = true
        let fin = voix.terminer()
        Task { [weak self] in
            let texte = await fin.value
            guard let self else { return }
            self.dictee = false
            self.finEcouteEnCours = false
            surTexte(texte)
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
            if messageDiscret != nil { erreurDiscrete = reponse }
        case "fin":
            for i in etapes.indices where etapes[i].statut == .enCours { etapes[i].statut = .echec }
            occupe = false
            confirmation = nil
            let texte = evt["texte"] as? String ?? ""
            reponse = texte
            effacerFichierEnCours()
            if let m = messageDiscret {
                messageDiscret = nil
                if let e = erreurDiscrete { surFinDiscrete?(false, e) } else { surFinDiscrete?(true, m) }
                erreurDiscrete = nil
            } else if modeOral && !texte.isEmpty && !arretDemande {
                voix.parler(texte)
            }
            arretDemande = false
        case "tache_terminee":
            surTacheTerminee?(evt["description"] as? String ?? "Tâche planifiée", evt["texte"] as? String ?? "",
                              evt["ok"] as? Bool ?? true)
            Task { await rafraichirTaches() }
        default:
            break
        }
    }
}
