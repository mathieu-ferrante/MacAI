import Foundation

/// Lance le moteur Python (`python -m macai serveur`), le relance s'il s'arrête, l'arrête à la fermeture.
/// Lancé par l'app, il hérite de ses autorisations macOS (Accessibilité, Automatisation, Micro…).
@MainActor
final class Moteur {
    nonisolated static let dossier = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/MacAI")

    private var processus: Process?
    private var relances = 0
    private var arretVoulu = false
    /// Relance différée en attente (après un arrêt ou « Redémarrer ») : annulée par arreter().
    private var relanceEnAttente: Task<Void, Never>?
    var surEtat: ((String) -> Void)?

    /// Chemin du Python de l'environnement installé par installer.sh (lancement.json).
    private func python() -> String? {
        let f = Moteur.dossier.appendingPathComponent("lancement.json")
        guard let data = try? Data(contentsOf: f),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let py = json["python"] as? String,
              FileManager.default.isExecutableFile(atPath: py) else { return nil }
        return py
    }

    func demarrer() {
        guard processus?.isRunning != true else { return }  // jamais deux moteurs
        relanceEnAttente?.cancel()
        relanceEnAttente = nil
        arretVoulu = false
        guard let py = python() else {
            surEtat?("Moteur introuvable : relance ./installer.sh")
            return
        }
        let infos = Moteur.dossier.appendingPathComponent("serveur.json")
        if let pid = orphelin(infos) {
            // On attend sa fin : en s'arrêtant, il effacerait le serveur.json du nouveau moteur.
            kill(pid, SIGTERM)
            surEtat?("Arrêt de l'ancien moteur…")
            demarrerApresFin(pid, infos)
            return
        }
        // Ancien fichier serveur.json : le client attendra le nouveau.
        try? FileManager.default.removeItem(at: infos)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = ["-m", "macai", "serveur"]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        p.environment = env
        let journal = Moteur.dossier.appendingPathComponent("moteur.log")
        tournerJournal(journal)
        if !FileManager.default.fileExists(atPath: journal.path) {
            FileManager.default.createFile(atPath: journal.path, contents: nil)
        }
        if let h = try? FileHandle(forWritingTo: journal) {
            h.seekToEndOfFile()  // on garde la trace des démarrages précédents
            p.standardOutput = h
            p.standardError = h
        }
        p.qualityOfService = .userInitiated
        p.terminationHandler = { [weak self] fini in
            Task { @MainActor in
                guard let self, self.processus === fini else { return }  // ancien processus : ignoré
                self.surArret()
            }
        }
        do {
            try p.run()
            processus = p
            surEtat?("Démarrage…")
        } catch {
            surEtat?("Impossible de lancer le moteur : \(error.localizedDescription)")
        }
    }

    /// Moteur resté d'un plantage précédent de l'app (ou d'un « Redémarrer ») : pid noté dans serveur.json,
    /// encore vivant, pas le nôtre, et c'est bien `macai serveur` (un pid peut avoir été réattribué).
    private func orphelin(_ infos: URL) -> pid_t? {
        guard let data = try? Data(contentsOf: infos),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pid = (json["pid"] as? NSNumber)?.int32Value, pid > 1,
              pid != getpid(), pid != processus?.processIdentifier,
              kill(pid, 0) == 0,  // 0 : le processus existe encore
              Moteur.estMoteurMacAI(pid) else { return nil }
        return pid
    }

    /// Arguments du processus (sysctl KERN_PROCARGS2) : contiennent « macai » et « serveur » ?
    private static func estMoteurMacAI(_ pid: pid_t) -> Bool {
        var mib: [Int32] = [CTL_KERN, KERN_PROCARGS2, pid]
        var taille = 0
        guard sysctl(&mib, 3, nil, &taille, nil, 0) == 0, taille > 4 else { return false }
        var tampon = [UInt8](repeating: 0, count: taille)
        guard sysctl(&mib, 3, &tampon, &taille, nil, 0) == 0 else { return false }
        // argc (4 octets), chemin de l'exécutable, puis arguments séparés par des zéros.
        let morceaux = tampon.prefix(taille).dropFirst(4).split(separator: 0)
            .compactMap { String(bytes: $0, encoding: .utf8) }
        return morceaux.contains("macai") && morceaux.contains("serveur")
    }

    /// Attend (5 s au plus, puis SIGKILL) la fin de l'ancien moteur, efface son serveur.json et démarre.
    private func demarrerApresFin(_ pid: pid_t, _ infos: URL) {
        relanceEnAttente = Task { @MainActor [weak self] in
            var essais = 0
            while kill(pid, 0) == 0 && essais < 50 {
                try? await Task.sleep(nanoseconds: 100_000_000)
                guard !Task.isCancelled else { return }
                essais += 1
            }
            if kill(pid, 0) == 0 {
                kill(pid, SIGKILL)
                try? await Task.sleep(nanoseconds: 200_000_000)
                guard !Task.isCancelled else { return }
            }
            try? FileManager.default.removeItem(at: infos)
            self?.demarrer()
        }
    }

    /// Journal de plus de 5 Mo : renommé en moteur.log.1 (l'ancien est remplacé).
    private func tournerJournal(_ journal: URL) {
        let fm = FileManager.default
        guard let taille = (try? fm.attributesOfItem(atPath: journal.path))?[.size] as? NSNumber,
              taille.intValue > 5 * 1024 * 1024 else { return }
        let ancien = journal.appendingPathExtension("1")
        try? fm.removeItem(at: ancien)
        try? fm.moveItem(at: journal, to: ancien)
    }

    private func surArret() {
        processus = nil
        guard !arretVoulu else { return }
        relances += 1
        if relances > 5 {
            surEtat?("Le moteur s'arrête sans cesse : voir ~/Library/Application Support/MacAI/moteur.log")
            return
        }
        surEtat?("Moteur arrêté, relance…")
        let delai = Double(min(relances * 2, 10))
        relancerApres(delai)
    }

    private func relancerApres(_ secondes: Double) {
        relanceEnAttente?.cancel()
        relanceEnAttente = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(secondes * 1_000_000_000))
            guard !Task.isCancelled else { return }
            self?.demarrer()
        }
    }

    /// Appelé par Etat après 60 s de connexion continue : un moteur qui plante en boucle reste compté.
    func reinitialiserRelances() { relances = 0 }

    func arreter() {
        arretVoulu = true
        relanceEnAttente?.cancel()
        relanceEnAttente = nil
        processus?.terminate()
        processus = nil
    }

    func redemarrer() {
        arreter()
        relances = 0
        relancerApres(1)
    }
}
