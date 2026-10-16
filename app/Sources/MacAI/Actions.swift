import AppKit

/// Actions lancées depuis n'importe quelle application : dictée, texte sélectionné, zone de l'écran,
/// annulation, tâches planifiées. Règle commune : tant que le moteur doit lire quelque chose dans
/// l'application de l'utilisateur (sélection), MacAI ne s'active pas ; le panneau ne s'ouvre qu'ensuite.
@MainActor
final class Actions {
    private let etat: Etat
    private let panneau: Panneau
    private let indicateur: Indicateur
    private var menuOuvert = false         // la répétition du clavier n'ouvre pas deux menus
    private var captureEnCours = false
    private var roleEnCours: String?       // rôle de la touche maintenue au moment de l'appui
    private var appPrecedente: NSRunningApplication?
    private var cibleMenu: CibleMenu?      // NSMenuItem.target est faible : on la garde
    private var indicateurEcoute = false   // l'indicateur montre l'écoute automatique
    private var indicateurLecture = false  // l'indicateur montre « Lecture… »
    /// Indicateur permanent sous le principal : « Démonstration en cours ».
    private lazy var indicateurDemonstration = Indicateur(rang: 1)

    init(etat: Etat, panneau: Panneau, indicateur: Indicateur) {
        self.etat = etat
        self.panneau = panneau
        self.indicateur = indicateur
        etat.surConsigne = { [weak self] attente, consigne in self?.consigneRecue(attente, consigne) }
        etat.surFinDiscrete = { [weak self] ok, message in
            if ok { self?.indicateur.reussite(message) } else { self?.indicateur.erreur(message) }
        }
        etat.surMessage = { [weak self] ok, message in
            if ok { self?.indicateur.reussite(message) } else { self?.indicateur.erreur(message) }
        }
        etat.surLecture = { [weak self] texte in self?.lire(texte) }
        etat.surSuivi = { [weak self] texte in self?.montrerEcoute(texte) }
        etat.surDemonstration = { [weak self] enCours in self?.montrerDemonstration(enCours) }
    }

    // MARK: - Voix : indicateurs

    /// Écoute automatique (conversation, oui / non) : « Je t'écoute… » puis ce qui est entendu.
    private func montrerEcoute(_ texte: String?) {
        if let texte {
            indicateurEcoute = true
            indicateurLecture = false
            indicateur.montrer(texte, symbole: "mic.fill", couleur: .red)
        } else if indicateurEcoute {
            indicateurEcoute = false
            indicateur.masquer()
        }
    }

    /// « Écouter » (⌥⇧T) : le texte sélectionné est lu ; Échap ou la touche pour parler l'arrêtent.
    private func lire(_ texte: String) {
        guard !texte.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            indicateur.erreur("Rien à lire.")
            return
        }
        indicateurLecture = true
        indicateurEcoute = false
        indicateur.montrer("Lecture…  (Échap pour arrêter)", symbole: "speaker.wave.2.fill")
        etat.voix.parler(texte, limite: 20_000) { [weak self] _ in
            guard let self, self.indicateurLecture else { return }
            self.indicateurLecture = false
            self.indicateur.masquer()
        }
    }

    private func montrerDemonstration(_ enCours: Bool) {
        if enCours {
            indicateurDemonstration.montrer("Démonstration en cours", symbole: "record.circle", couleur: .red)
        } else {
            indicateurDemonstration.masquer()
        }
    }

    // MARK: - Touche maintenue (Fn ou Option droite)

    /// Rôle de la touche maintenue : "dicter" (défaut) ou "parler".
    static var roleTouche: String { UserDefaults.standard.string(forKey: "roleFn") ?? "dicter" }

    func debutToucheMaintenue() {
        let role = Actions.roleTouche
        roleEnCours = role
        if role == "parler" {
            panneau.montrer()
            etat.commencerEcoute()
            return
        }
        // Dictée : le panneau ne s'ouvre pas, l'application de devant garde le focus.
        let lancee = etat.commencerDictee({ [weak self] partiel in
            self?.indicateur.montrer(partiel.isEmpty ? "Dictée…" : partiel, symbole: "mic.fill", couleur: .red)
        }, erreur: { [weak self] message in
            self?.indicateur.erreur(message)
        })
        if lancee {
            indicateur.montrer("Dictée…", symbole: "mic.fill", couleur: .red)
        } else {
            roleEnCours = nil
        }
    }

    func finToucheMaintenue() {
        guard let role = roleEnCours else { return }
        roleEnCours = nil
        if role == "parler" {
            etat.finirEcoute()
            return
        }
        etat.finirDictee { [weak self] texte in
            guard let self else { return }
            self.indicateur.masquer()
            guard !texte.isEmpty else { return }
            Task { await Clavier.taper(texte) }
        }
    }

    // MARK: - Texte sélectionné (⌥⇧T)

    private struct ActionTexte {
        let titre: String
        let action: String
        let sortie: String
        let enCours: String   // indicateur pendant le travail (sortie remplacer / copier)
        let reussite: String
    }

    private static let actionsTexte: [ActionTexte] = [
        ActionTexte(titre: "Corriger", action: "corriger", sortie: "remplacer",
                    enCours: "Correction…", reussite: "Texte corrigé"),
        ActionTexte(titre: "Reformuler", action: "reformuler", sortie: "remplacer",
                    enCours: "Reformulation…", reussite: "Texte reformulé"),
        ActionTexte(titre: "Traduire", action: "traduire", sortie: "remplacer",
                    enCours: "Traduction…", reussite: "Texte traduit"),
        ActionTexte(titre: "Résumer", action: "resumer", sortie: "afficher", enCours: "", reussite: ""),
        ActionTexte(titre: "Expliquer", action: "expliquer", sortie: "afficher", enCours: "", reussite: ""),
        ActionTexte(titre: "Répondre à ce message", action: "repondre", sortie: "afficher", enCours: "", reussite: ""),
    ]

    func menuTexte() {
        guard !menuOuvert, pretPourAction() else { return }
        appPrecedente = NSWorkspace.shared.frontmostApplication
        var elements: [ElementMenu] = Actions.actionsTexte.map { a in
            .choix(a.titre) { [weak self] in self?.lancerTexte(a) }
        }
        elements.insert(.separateur, at: 3)
        elements.append(.separateur)
        elements.append(.choix("Écouter") { [weak self] in self?.lancerLecture() })
        elements.append(.choix("Autre consigne…") { [weak self] in self?.demanderConsigneTexte() })
        _ = ouvrirMenu("Texte sélectionné", elements)
    }

    /// Appelé juste après le choix dans le menu, l'application de l'utilisateur encore devant : le moteur
    /// lit la sélection pendant la requête, le panneau ne s'ouvre qu'après sa réponse.
    private func lancerTexte(_ a: ActionTexte) {
        let discret = a.sortie != "afficher"
        Task {
            if let erreur = await etat.lancer("/texte", ["action": a.action, "sortie": a.sortie],
                                              libelle: "\(a.titre) le texte sélectionné",
                                              discret: discret ? a.reussite : nil) {
                indicateur.erreur(erreur)
                return
            }
            if discret {
                indicateur.montrer(a.enCours, symbole: "sparkle")  // remplacé par le message de fin
            } else {
                panneau.montrer()
            }
        }
    }

    /// « Écouter » : le moteur renvoie la sélection telle quelle (sans modèle), l'app la lit à voix haute.
    /// Pas de panneau : l'application de l'utilisateur reste devant.
    private func lancerLecture() {
        Task {
            if let erreur = await etat.lancer("/texte", ["action": "lire", "sortie": "afficher"],
                                              libelle: "Écouter le texte sélectionné", discret: "", lire: true) {
                indicateur.erreur(erreur)
                return
            }
            // La fin a pu arriver pendant la requête (la lecture a alors déjà commencé).
            if etat.occupe { indicateur.montrer("Lecture…", symbole: "speaker.wave.2.fill", duree: 15) }
        }
    }

    /// « Autre consigne… » : le panneau doit prendre le focus pour la saisie, ce qui peut faire perdre la
    /// sélection. On la copie donc d'abord (Cmd + C dans l'application de devant, 150 ms pour que le
    /// presse-papiers soit à jour) : le moteur se rabat sur le presse-papiers s'il ne lit plus de sélection.
    /// À l'envoi, l'application d'origine est remise devant avant la requête (voir consigneRecue).
    private func demanderConsigneTexte() {
        Clavier.copierSelection()
        Task {
            try? await Task.sleep(nanoseconds: 150_000_000)
            preparerAttente(.texte)
        }
    }

    // MARK: - Zone de l'écran (⌥⇧S)

    func regarderZone() {
        guard !captureEnCours, !menuOuvert, pretPourAction() else { return }
        captureEnCours = true
        let fichier = FileManager.default.temporaryDirectory
            .appendingPathComponent("macai-zone-\(UUID().uuidString).png")
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        p.arguments = ["-i", "-x", fichier.path]  // sélection à la souris, sans son ; Échap = pas de fichier
        p.terminationHandler = { [weak self] _ in
            Task { @MainActor in self?.zoneCapturee(fichier) }
        }
        do {
            try p.run()
        } catch {
            captureEnCours = false
            indicateur.erreur("Capture d'écran impossible : \(error.localizedDescription)")
        }
    }

    private func zoneCapturee(_ fichier: URL) {
        captureEnCours = false
        let taille = (try? FileManager.default.attributesOfItem(atPath: fichier.path)[.size] as? Int) ?? 0
        guard taille > 0 else {  // Échap : rien n'a été capturé
            try? FileManager.default.removeItem(at: fichier)
            return
        }
        // Filet de sécurité : la capture ne reste jamais plus de 10 minutes (question jamais posée…).
        DispatchQueue.main.asyncAfter(deadline: .now() + 600) {
            try? FileManager.default.removeItem(at: fichier)
        }
        let choix: [(String, String)] = [("Expliquer", "expliquer"), ("Traduire", "traduire"),
                                         ("Extraire le texte", "texte"), ("Extraire le tableau (Excel)", "tableau")]
        var elements: [ElementMenu] = choix.map { titre, action in
            .choix(titre) { [weak self] in self?.lancerImage(fichier, action: action, libelle: titre) }
        }
        elements.append(.separateur)
        elements.append(.choix("Poser une question…") { [weak self] in self?.preparerAttente(.image(fichier)) })
        if !ouvrirMenu("Zone de l'écran", elements) {
            try? FileManager.default.removeItem(at: fichier)
        }
    }

    private func lancerImage(_ fichier: URL, action: String, libelle: String, question: String? = nil) {
        var corps: [String: Any] = ["chemin": fichier.path, "action": action]
        if let question { corps["question"] = question }
        Task {
            if let erreur = await etat.lancer("/image", corps, libelle: "Zone de l'écran : \(libelle)", fichier: fichier) {
                indicateur.erreur(erreur)
                return
            }
            panneau.montrer()
        }
    }

    // MARK: - Consigne saisie dans le panneau

    private func preparerAttente(_ attente: Attente) {
        guard !etat.occupe else {
            indicateur.erreur("Je termine la demande en cours.")
            return
        }
        etat.derniereDemande = ""
        etat.reponse = ""
        etat.etapes = []
        etat.saisie = ""
        etat.attente = attente
        panneau.montrer()
    }

    private func consigneRecue(_ attente: Attente, _ consigne: String) {
        switch attente {
        case .image(let fichier):
            lancerImage(fichier, action: "libre", libelle: consigne, question: consigne)
        case .texte:
            // L'application d'origine repasse devant le temps de la requête : sa sélection est souvent encore là.
            panneau.orderOut(nil)
            appPrecedente?.activate()
            Task {
                try? await Task.sleep(nanoseconds: 300_000_000)
                if let erreur = await etat.lancer("/texte", ["action": "libre", "consigne": consigne, "sortie": "afficher"],
                                                  libelle: consigne) {
                    indicateur.erreur(erreur)
                    return
                }
                panneau.montrer()
            }
        }
    }

    // MARK: - Menu 🧠

    func annulerDerniereAction() {
        guard etat.connecte else {
            indicateur.erreur("MacAI n'est pas encore prêt.")
            return
        }
        Task {
            let (ok, texte) = await etat.annulerDerniereAction()
            if ok {
                indicateur.montrer(texte, symbole: "arrow.uturn.backward.circle.fill", couleur: .green, duree: 4)
            } else {
                indicateur.erreur(texte)
            }
        }
    }

    func supprimerTache(_ t: TachePlanifiee) {
        NSApp.activate()
        let alerte = NSAlert()
        alerte.messageText = "Supprimer la tâche planifiée ?"
        alerte.informativeText = "« \(t.description) »" + (t.frequence.isEmpty ? "" : " (\(t.frequence))")
        alerte.addButton(withTitle: "Supprimer").hasDestructiveAction = true
        alerte.addButton(withTitle: "Annuler")
        guard alerte.runModal() == .alertFirstButtonReturn else { return }
        Task {
            if let erreur = await etat.supprimerTache(t.id) {
                indicateur.erreur(erreur)
            } else {
                indicateur.reussite("Tâche supprimée")
            }
        }
    }

    /// Heure du briefing du matin (HH:MM).
    func demanderHeureBriefing() {
        guard let r = etat.reglages else {
            indicateur.erreur("MacAI n'est pas encore prêt.")
            return
        }
        NSApp.activate()
        let alerte = NSAlert()
        alerte.messageText = "Heure du briefing du matin"
        alerte.informativeText = "Format HH:MM, par exemple 08:30."
        let champ = NSTextField(string: r.briefingHeure)
        champ.frame = NSRect(x: 0, y: 0, width: 120, height: 24)
        alerte.accessoryView = champ
        alerte.window.initialFirstResponder = champ
        alerte.addButton(withTitle: "Enregistrer")
        alerte.addButton(withTitle: "Annuler")
        guard alerte.runModal() == .alertFirstButtonReturn else { return }
        let saisie = champ.stringValue.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "h", with: ":")
        let parties = saisie.split(separator: ":", omittingEmptySubsequences: false)
        guard parties.count <= 2, let h = Int(parties[0]), (0...23).contains(h),
              let m = parties.count == 2 ? (parties[1].isEmpty ? 0 : Int(parties[1])) : 0, (0...59).contains(m) else {
            indicateur.erreur("Heure invalide : « \(champ.stringValue) » (format HH:MM).")
            return
        }
        let heure = String(format: "%02d:%02d", h, m)
        etat.changerBriefing(heure: heure)
        indicateur.reussite("Briefing à \(heure)")
    }

    /// Démonstration : début, ou fin avec le nom de la compétence ; le résultat s'affiche dans le panneau.
    func basculerDemonstration() {
        guard etat.connecte else {
            indicateur.erreur("MacAI n'est pas encore prêt.")
            return
        }
        guard etat.demonstrationEnCours else {
            Task {
                let (ok, texte) = await etat.debuterDemonstration()
                if ok {
                    indicateur.montrer(texte, symbole: "record.circle", couleur: .red, duree: 5)
                } else {
                    indicateur.erreur(texte)
                }
            }
            return
        }
        NSApp.activate()
        let alerte = NSAlert()
        alerte.messageText = "Terminer la démonstration"
        alerte.informativeText = "Quel nom donner à cette démonstration ? (ex. : exporter le devis en PDF)"
        let champ = NSTextField(string: "")
        champ.placeholderString = "Nom"
        champ.frame = NSRect(x: 0, y: 0, width: 280, height: 24)
        alerte.accessoryView = champ
        alerte.window.initialFirstResponder = champ
        alerte.addButton(withTitle: "Enregistrer")
        alerte.addButton(withTitle: "Continuer la démonstration")
        guard alerte.runModal() == .alertFirstButtonReturn else { return }
        let nom = champ.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !nom.isEmpty else {
            indicateur.erreur("Donne un nom à la démonstration (elle continue).")
            return
        }
        Task {
            let (ok, texte, etapes) = await etat.finirDemonstration(nom)
            guard ok || !texte.isEmpty else {
                indicateur.erreur("La démonstration n'a pas pu être enregistrée.")
                return
            }
            var resultat = texte
            if !etapes.isEmpty {
                resultat += (resultat.isEmpty ? "" : "\n\n")
                    + etapes.enumerated().map { "\($0.offset + 1). \($0.element)" }.joined(separator: "\n")
            }
            afficherResultatTache("Démonstration « \(nom) »", resultat)
        }
    }

    /// Clic sur la notification d'une tâche planifiée : son résultat s'affiche dans le panneau.
    func afficherResultatTache(_ description: String, _ texte: String) {
        if !etat.occupe {
            etat.attente = nil
            etat.derniereDemande = description
            etat.etapes = []
            etat.reponse = texte
        }
        panneau.montrer()
    }

    // MARK: - Outils

    /// Moteur prêt et libre ; sinon le dit dans l'indicateur.
    private func pretPourAction() -> Bool {
        guard etat.connecte else {
            indicateur.erreur("MacAI n'est pas encore prêt.")
            return false
        }
        guard !etat.occupe else {
            indicateur.erreur("Je termine la demande en cours.")
            return false
        }
        return true
    }

    private enum ElementMenu {
        case choix(String, @MainActor () -> Void)
        case separateur
    }

    /// Menu contextuel à l'emplacement de la souris, sans activer MacAI. Renvoie true si un choix a été fait.
    private func ouvrirMenu(_ titre: String, _ elements: [ElementMenu]) -> Bool {
        menuOuvert = true
        defer { menuOuvert = false }
        let menu = NSMenu(title: titre)
        menu.autoenablesItems = false
        let entete = NSMenuItem(title: titre, action: nil, keyEquivalent: "")
        entete.isEnabled = false
        menu.addItem(entete)
        let cible = CibleMenu()
        cibleMenu = cible
        for e in elements {
            switch e {
            case .separateur:
                menu.addItem(.separator())
            case .choix(let t, let faire):
                let item = NSMenuItem(title: t, action: #selector(CibleMenu.choisir(_:)), keyEquivalent: "")
                item.target = cible
                item.tag = cible.actions.count
                cible.actions.append(faire)
                menu.addItem(item)
            }
        }
        return menu.popUp(positioning: nil, at: NSEvent.mouseLocation, in: nil)
    }
}

/// Cible des éléments de menu : chaque élément exécute sa fermeture.
@MainActor
private final class CibleMenu: NSObject {
    var actions: [@MainActor () -> Void] = []

    @objc func choisir(_ sender: NSMenuItem) {
        guard actions.indices.contains(sender.tag) else { return }
        actions[sender.tag]()
    }
}
