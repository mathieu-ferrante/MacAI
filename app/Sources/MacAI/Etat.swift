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

/// Plan proposé par le moteur avant d'agir (« montre-moi avant de faire »).
struct PropositionPlan: Identifiable {
    let id: String
    let demande: String
    let etapes: [String]
}

/// Forme des réponses : écrites (panneau), orales (voix, panneau réduit) ou les deux.
enum ModeReponses: String, CaseIterable {
    case ecrites, orales, ecritesEtOrales

    var titre: String {
        switch self {
        case .ecrites: return "Écrites"
        case .orales: return "Orales"
        case .ecritesEtOrales: return "Écrites et orales"
        }
    }

    var oral: Bool { self != .ecrites }

    /// Choix enregistré ; l'ancien réglage « Réponses à l'oral » (modeOral) est repris une fois.
    static func enregistre() -> ModeReponses {
        let d = UserDefaults.standard
        if let s = d.string(forKey: "modeReponses"), let m = ModeReponses(rawValue: s) { return m }
        let m: ModeReponses = d.bool(forKey: "modeOral") ? .ecritesEtOrales : .ecrites
        d.set(m.rawValue, forKey: "modeReponses")
        d.removeObject(forKey: "modeOral")
        return m
    }
}

/// Réglages du moteur (GET /reglages) : alertes, plan, briefing, classement.
struct Reglages {
    static let alertes = [("batterie", "Batterie faible"), ("memoire", "Mémoire saturée"),
                          ("disque", "Disque presque plein"), ("rendez_vous", "Rendez-vous dans 15 min"),
                          ("telechargements", "Téléchargement terminé")]
    var autonomie = ""
    var alertes: [String: Bool] = [:]
    var plan = "complexe"
    var briefingActif = false
    var briefingHeure = "08:00"
    var classement = false

    init(_ j: [String: Any]) {
        autonomie = j["autonomie"] as? String ?? ""
        alertes = j["alertes"] as? [String: Bool] ?? [:]
        plan = j["plan"] as? String ?? "complexe"
        let b = j["briefing"] as? [String: Any] ?? [:]
        briefingActif = b["actif"] as? Bool ?? false
        briefingHeure = b["heure"] as? String ?? "08:00"
        classement = j["classement"] as? Bool ?? false
    }
}

/// Écoute ouverte sans touche, juste après une phrase dite par MacAI.
private enum Suivi {
    case conversation            // question de suite (conversation vocale)
    case confirmation(String)    // oui / non pour une action sensible (id)
    case plan(String)            // oui / non pour un plan proposé (id)
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
    @Published var plan: PropositionPlan? {
        didSet {
            if plan?.id != oldValue?.id {  // nouveau plan : la carte repart de zéro
                modifierPlan = false
                correctionPlan = ""
            }
        }
    }
    /// Carte du plan : champ « Modifier… » ouvert et son texte.
    @Published var modifierPlan = false
    @Published var correctionPlan = ""
    @Published var reglages: Reglages?
    @Published var demonstrationEnCours = false {
        didSet { if demonstrationEnCours != oldValue { surDemonstration?(demonstrationEnCours) } }
    }
    @Published var modeReponses: ModeReponses = ModeReponses.enregistre() {
        didSet {
            UserDefaults.standard.set(modeReponses.rawValue, forKey: "modeReponses")
            if !modeReponses.oral { taireTout() }
        }
    }
    /// Après une réponse dite, le micro se rouvre seul pour la suite (jamais après Échap).
    @Published var conversationVocale: Bool = UserDefaults.standard.bool(forKey: "conversationVocale") {
        didSet {
            UserDefaults.standard.set(conversationVocale, forKey: "conversationVocale")
            if !conversationVocale, case .conversation? = suivi { annulerSuivi() }
        }
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
    /// « Écouter » (⌥⇧T) : le texte de fin est lu à voix haute au lieu d'être affiché.
    private var lireALaFin = false
    /// Écoute automatique en cours (sans touche) et son numéro de session.
    private var suivi: Suivi?
    private var sessionSuivi = 0
    private var texteSuivi = ""
    private var dernierChangementSuivi = Date()
    /// Touche pour parler appuyée pendant une écoute automatique : l'écoute normale démarre après sa fermeture.
    private var relanceEcoute = false
    /// Panneau fermé (Échap) : plus aucune écoute automatique jusqu'à sa prochaine ouverture.
    var ecouteAutoInterdite = false

    /// Consigne tapée (ou dite) alors que le panneau attendait autre chose qu'une demande.
    var surConsigne: (@MainActor (Attente, String) -> Void)?
    /// Fin d'une demande discrète : (réussite, message).
    var surFinDiscrete: (@MainActor (Bool, String) -> Void)?
    /// Tâche planifiée terminée en arrière-plan : (description, texte, réussite).
    var surTacheTerminee: (@MainActor (String, String, Bool) -> Void)?
    /// Texte à lire à voix haute (« Écouter » du menu ⌥⇧T).
    var surLecture: (@MainActor (String) -> Void)?
    /// Écoute automatique : texte de l'indicateur, nil pour le masquer.
    var surSuivi: (@MainActor (String?) -> Void)?
    /// Message bref pour l'indicateur : (réussite, texte).
    var surMessage: (@MainActor (Bool, String) -> Void)?
    /// Alerte du moteur (batterie, rendez-vous…) : (titre, texte, type).
    var surAlerte: (@MainActor (String, String, String) -> Void)?
    /// Zone à surligner à l'écran : (rectangle en points, origine en haut à gauche de l'écran principal ; texte).
    var surSurligner: (@MainActor (CGRect, String) -> Void)?
    /// Démonstration en cours ou finie (indicateur permanent).
    var surDemonstration: (@MainActor (Bool) -> Void)?
    /// Plan proposé : le panneau doit être visible pour le valider.
    var surPlan: (@MainActor () -> Void)?
    /// Le panneau est-il à l'écran ? (pas d'écoute de suite s'il est caché)
    var panneauVisible: (@MainActor () -> Bool)?

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
                    Task { await chargerReglages() }
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
                demonstrationEnCours = false  // un moteur relancé n'enregistre plus rien
                plan = nil
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
        plan = nil
        lireALaFin = false
        annulerSuivi()
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
        voix.taire()
        annulerSuivi()
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
    /// `lire` : le texte de fin est passé à surLecture (lu à voix haute) au lieu d'être affiché.
    func lancer(_ chemin: String, _ corps: [String: Any], libelle: String, discret: String? = nil,
                fichier: URL? = nil, lire: Bool = false) async -> String? {
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
        lireALaFin = lire
        fichierEnCours = fichier
        voix.taire()
        annulerSuivi()
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
        lireALaFin = false
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
        if case .confirmation? = suivi { annulerSuivi() }
        voix.taire()
        Task { await client.envoyer("/confirmation", ["id": c.id, "accepter": accepter]) }
    }

    /// Réponse au plan proposé. Avec une correction, le moteur refait le plan (et peut en proposer un autre) :
    /// « accepter » reste alors à false, rien n'est lancé sans nouveau plan validé.
    func repondrePlan(_ accepter: Bool, correction: String? = nil) {
        guard let p = plan else { return }
        plan = nil
        if case .plan? = suivi { annulerSuivi() }
        voix.taire()
        var corps: [String: Any] = ["id": p.id, "accepter": accepter]
        if let c = correction?.trimmingCharacters(in: .whitespacesAndNewlines), !c.isEmpty {
            corps["accepter"] = false
            corps["correction"] = c
        }
        Task {
            if await client.envoyer("/plan", corps) == nil { surMessage?(false, "Le moteur n'a pas reçu la réponse au plan.") }
        }
    }

    // MARK: - Réglages du moteur

    func chargerReglages() async {
        guard connecte, let j = await client.lire("/reglages") as? [String: Any] else { return }
        reglages = Reglages(j)
    }

    /// Envoie une partie des réglages (mêmes formes que GET /reglages). `local` met l'affichage à jour tout
    /// de suite ; en cas d'échec, les réglages du moteur sont relus.
    func changerReglages(_ corps: [String: Any], local: (inout Reglages) -> Void) {
        guard connecte, var r = reglages else {
            surMessage?(false, "MacAI n'est pas encore prêt.")
            return
        }
        local(&r)
        reglages = r
        Task {
            let (statut, json) = await client.poster("/reglages", corps)
            if statut != 0 && statut < 300, let json, json["erreur"] == nil {
                reglages = Reglages(json)
            } else {
                surMessage?(false, json?["erreur"] as? String ?? "Réglage non enregistré.")
                await chargerReglages()
            }
        }
    }

    func changerAlerte(_ cle: String, _ actif: Bool) {
        var alertes = reglages?.alertes ?? [:]
        alertes[cle] = actif
        changerReglages(["alertes": alertes]) { $0.alertes = alertes }
    }

    func changerPlan(_ valeur: String) {
        changerReglages(["plan": valeur]) { $0.plan = valeur }
    }

    func changerBriefing(actif: Bool? = nil, heure: String? = nil) {
        guard let r = reglages else {
            surMessage?(false, "MacAI n'est pas encore prêt.")
            return
        }
        let a = actif ?? r.briefingActif
        let h = heure ?? r.briefingHeure
        changerReglages(["briefing": ["actif": a, "heure": h]]) {
            $0.briefingActif = a
            $0.briefingHeure = h
        }
    }

    func changerClassement(_ actif: Bool) {
        changerReglages(["classement": actif]) { $0.classement = actif }
    }

    // MARK: - Démonstration

    /// Début de l'enregistrement : (réussite, texte du moteur).
    func debuterDemonstration() async -> (Bool, String) {
        let (statut, json) = await client.poster("/demonstration/debut")
        guard statut != 0 else { return (false, "Le moteur ne répond pas.") }
        let ok = json?["ok"] as? Bool ?? false
        if ok { demonstrationEnCours = true }
        return (ok, json?["texte"] as? String ?? json?["erreur"] as? String ?? (ok ? "Démonstration en cours." : "Enregistrement impossible."))
    }

    /// Fin de l'enregistrement : (réussite, texte, étapes retenues).
    func finirDemonstration(_ nom: String) async -> (Bool, String, [String]) {
        let (statut, json) = await client.poster("/demonstration/fin", ["nom": nom])
        guard statut != 0 else { return (false, "Le moteur ne répond pas.", []) }
        let ok = json?["ok"] as? Bool ?? false
        if ok { demonstrationEnCours = false }
        return (ok, json?["texte"] as? String ?? json?["erreur"] as? String ?? "", json?["etapes"] as? [String] ?? [])
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
        if suivi != nil || (relanceEcoute && finEcouteEnCours) {
            // Écoute automatique ouverte : on la referme, l'écoute normale suit (si la touche est encore tenue).
            relanceEcoute = true
            annulerSuivi()
            return
        }
        guard !ecoute, !dictee, !finEcouteEnCours, connecte else { return }
        voix.taire()
        ecouteAutoInterdite = false
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
        if relanceEcoute && !ecoute {  // touche relâchée avant la fin de l'écoute automatique
            relanceEcoute = false
            return
        }
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
        if suivi != nil {  // l'écoute automatique est refermée ; la dictée se relance d'un nouvel appui
            annulerSuivi()
            return false
        }
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

    // MARK: - Voix : coupure, écoute automatique

    /// Coupe la voix et referme une écoute automatique.
    func taireTout() {
        voix.taire()
        annulerSuivi()
    }

    /// Échap (dans n'importe quelle application) : n'agit que si MacAI parle ou écoute de lui-même.
    func echap() {
        guard voix.parle || suivi != nil else { return }
        taireTout()
    }

    /// Panneau fermé par l'utilisateur : silence, et plus d'écoute automatique jusqu'à sa réouverture.
    func panneauFerme() {
        ecouteAutoInterdite = true
        taireTout()
    }

    /// Les réponses sont dites et l'écoute automatique est permise.
    private var ecouteAutoPermise: Bool {
        modeReponses.oral && !ecouteAutoInterdite && connecte && !ecoute && !dictee && !finEcouteEnCours && suivi == nil
    }

    /// Ouvre le micro sans touche : s'arrête seul après `silence` secondes sans parole, ou 1,5 s après la
    /// fin de la phrase. Mêmes règles que l'écoute normale (une session à la fois, annulation, nettoyage).
    private func ecouterSuivi(_ s: Suivi, silence: TimeInterval) {
        guard ecouteAutoPermise else { return }
        suivi = s
        sessionEcoute += 1
        sessionSuivi = sessionEcoute
        let session = sessionSuivi
        texteSuivi = ""
        let invite: String
        switch s {
        case .conversation: invite = "Je t'écoute…"
        case .confirmation, .plan: invite = "Je t'écoute… (oui ou non)"
        }
        surSuivi?(invite)
        let tache = voix.ecouter { [weak self] partiel in
            guard let self, self.suivi != nil, self.sessionSuivi == session, !self.finEcouteEnCours else { return }
            if partiel != self.texteSuivi {
                self.texteSuivi = partiel
                self.dernierChangementSuivi = Date()
                self.surSuivi?(partiel.isEmpty ? invite : partiel)
            }
        }
        Task { [weak self] in
            do {
                try await tache.value
            } catch {
                guard let self, self.sessionSuivi == session, self.suivi != nil else { return }
                self.suivi = nil
                self.surSuivi?(nil)
                self.surMessage?(false, "Micro indisponible : \(error.localizedDescription)")
                return
            }
            // Micro ouvert : le délai de silence commence maintenant (pas pendant la préparation).
            let debut = Date()
            self?.dernierChangementSuivi = debut
            while true {
                try? await Task.sleep(nanoseconds: 250_000_000)
                guard let self, self.sessionSuivi == session, self.suivi != nil, !self.finEcouteEnCours else { return }
                let maintenant = Date()
                let texte = self.texteSuivi
                if texte.isEmpty && maintenant.timeIntervalSince(debut) > silence {
                    self.terminerSuivi(garder: false)  // rien dit : on s'arrête sans bruit
                    return
                }
                if !texte.isEmpty && (maintenant.timeIntervalSince(self.dernierChangementSuivi) > 1.5
                                      || maintenant.timeIntervalSince(debut) > 30) {
                    self.terminerSuivi(garder: true)
                    return
                }
            }
        }
    }

    /// Referme le micro sans rien envoyer.
    private func annulerSuivi() {
        terminerSuivi(garder: false)
    }

    private func terminerSuivi(garder: Bool) {
        guard let s = suivi, !finEcouteEnCours else { return }
        finEcouteEnCours = true
        let session = sessionSuivi
        let fin = voix.terminer()
        Task { [weak self] in
            let texte = await fin.value
            guard let self else { return }
            self.finEcouteEnCours = false
            if self.sessionSuivi == session { self.suivi = nil }
            self.surSuivi?(nil)
            if garder { self.suiviEntendu(s, texte) }
            if self.relanceEcoute {
                self.relanceEcoute = false
                self.commencerEcoute()
            }
        }
    }

    private func suiviEntendu(_ s: Suivi, _ texte: String) {
        guard !texte.isEmpty else { return }
        switch s {
        case .conversation:
            if Etat.finDeConversation(texte) {
                surMessage?(true, "Conversation terminée")
            } else {
                envoyer(texte)
            }
        case .confirmation(let id):
            guard confirmation?.id == id, let oui = Etat.ouiOuNon(texte) else { return }  // ambigu : on attend un clic
            repondre(oui)
        case .plan(let id):
            guard plan?.id == id, let oui = Etat.ouiOuNon(texte) else { return }
            repondrePlan(oui)
        }
    }

    /// Texte en minuscules, sans accents ni ponctuation, entouré d'espaces (« d'accord » → « d accord »).
    private static func normaliser(_ texte: String) -> String {
        let t = texte.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "fr_FR"))
            .replacingOccurrences(of: "[^a-z0-9]+", with: " ", options: .regularExpression)
        return " " + t.trimmingCharacters(in: .whitespaces) + " "
    }

    private static func contient(_ t: String, _ mots: [String]) -> Bool {
        mots.contains { t.contains(" \($0) ") }
    }

    /// « Merci », « stop, c'est tout », « terminé »… : rien d'autre que des mots de fin (« merci, ouvre
    /// Safari » est une vraie demande).
    static func finDeConversation(_ texte: String) -> Bool {
        var t = normaliser(texte)
        let fins = ["c est tout", "ca suffit", "ca ira", "stop", "merci", "termine", "terminee", "fini"]
        guard contient(t, fins) else { return false }
        for f in fins { t = t.replacingOccurrences(of: " \(f) ", with: "  ") }
        let politesse: Set<Substring> = ["beaucoup", "bien", "ok", "bon", "alors", "oui", "non", "pour", "le", "moment",
                                         "maintenant", "macai", "c", "est", "ca", "sera", "tout", "et", "a", "plus", "super"]
        return t.split(separator: " ").allSatisfy { politesse.contains($0) }
    }

    /// true : oui clair ; false : non clair ; nil : ambigu (jamais d'acceptation dans le doute).
    static func ouiOuNon(_ texte: String) -> Bool? {
        let t = normaliser(texte)
        let mots = t.split(separator: " ").count
        let oui = contient(t, ["oui", "vas y", "confirme", "je confirme", "d accord", "ok", "okay", "ouais"])
        let non = contient(t, ["non", "annule", "annuler", "stop", "refuse", "arrete", "pas", "ne", "n"])
        if oui && !non && mots <= 4 { return true }
        if non && !oui && contient(t, ["non", "annule", "annuler", "stop", "refuse", "arrete"]) { return false }
        return nil
    }

    // MARK: - Événements du moteur

    /// Réponses orales : dit la question puis écoute 6 s un oui ou un non (la carte reste pour un clic).
    private func demanderAVoixHaute(_ question: String, _ s: Suivi) {
        guard modeReponses.oral, !ecouteAutoInterdite else { return }
        if suivi != nil { annulerSuivi() }
        voix.parler(question) { [weak self] jusquAuBout in
            guard let self, jusquAuBout else { return }
            self.ecouterSuivi(s, silence: 6)
        }
    }

    private static func resumePlan(_ p: PropositionPlan) -> String {
        let n = p.etapes.count
        guard n > 0 else { return "Je propose un plan. Je le fais ?" }
        let premieres = p.etapes.prefix(5).map { $0.trimmingCharacters(in: CharacterSet(charactersIn: " .")) }
        let reste = n > 5 ? " ; et \(n - 5) autres" : ""
        return "Je propose \(n) étape\(n > 1 ? "s" : "") : " + premieres.joined(separator: " ; ") + reste + ". Je le fais ?"
    }

    func traiter(_ evt: [String: Any]) {
        let type = evt["type"] as? String ?? ""
        switch type {
        case "debut":
            occupe = true
            reponse = ""
            etapes = []
            souvenirsAppris = []
            propositionCompetence = false
            plan = nil
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
            let id = evt["id"] as? String ?? ""
            confirmation = DemandeConfirmation(id: id, phrase: phrase)
            demanderAVoixHaute("\(phrase). Tu confirmes ?", .confirmation(id))
        case "plan_propose":
            let p = PropositionPlan(id: evt["id"] as? String ?? "", demande: evt["demande"] as? String ?? "",
                                    etapes: evt["etapes"] as? [String] ?? [])
            plan = p
            surPlan?()
            demanderAVoixHaute(Etat.resumePlan(p), .plan(p.id))
        case "alerte":
            surAlerte?(evt["titre"] as? String ?? "Alerte", evt["texte"] as? String ?? "", evt["type"] as? String ?? "")
        case "demonstration":
            demonstrationEnCours = (evt["etat"] as? String) == "en_cours"
        case "surligner":
            func nombre(_ cle: String) -> Double { (evt[cle] as? NSNumber)?.doubleValue ?? 0 }
            surSurligner?(CGRect(x: nombre("x"), y: nombre("y"), width: nombre("largeur"), height: nombre("hauteur")),
                          evt["texte"] as? String ?? "")
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
            plan = nil
            annulerSuivi()  // un oui / non attendu n'a plus d'objet
            let texte = evt["texte"] as? String ?? ""
            reponse = texte
            effacerFichierEnCours()
            if let m = messageDiscret {
                messageDiscret = nil
                if let e = erreurDiscrete {
                    surFinDiscrete?(false, e)
                } else if lireALaFin {
                    surLecture?(texte)
                } else {
                    surFinDiscrete?(true, m)
                }
                erreurDiscrete = nil
            } else if modeReponses.oral && !texte.isEmpty && !arretDemande {
                voix.parler(texte) { [weak self] jusquAuBout in
                    // Conversation vocale : la suite s'écoute seule, sauf panneau fermé ou voix coupée.
                    guard let self, jusquAuBout, self.conversationVocale, !self.occupe,
                          self.panneauVisible?() ?? false else { return }
                    self.ecouterSuivi(.conversation, silence: 8)
                }
            }
            lireALaFin = false
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
