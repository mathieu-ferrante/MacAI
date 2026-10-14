import Foundation

/// Lance le moteur Python (`python -m macai serveur`), le relance s'il s'arrête, l'arrête à la fermeture.
/// Lancé par l'app, il hérite de ses autorisations macOS (Accessibilité, Automatisation, Micro…).
final class Moteur {
    static let dossier = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/MacAI")

    private var processus: Process?
    private var relances = 0
    private var arretVoulu = false
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
        arretVoulu = false
        guard let py = python() else {
            surEtat?("Moteur introuvable : relance ./installer.sh")
            return
        }
        // Ancien fichier serveur.json : le client attendra le nouveau.
        try? FileManager.default.removeItem(at: Moteur.dossier.appendingPathComponent("serveur.json"))
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = ["-m", "macai", "serveur"]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        p.environment = env
        let journal = Moteur.dossier.appendingPathComponent("moteur.log")
        FileManager.default.createFile(atPath: journal.path, contents: nil)
        if let h = try? FileHandle(forWritingTo: journal) {
            p.standardOutput = h
            p.standardError = h
        }
        p.qualityOfService = .userInitiated
        p.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.surArret() }
        }
        do {
            try p.run()
            processus = p
            surEtat?("Démarrage…")
        } catch {
            surEtat?("Impossible de lancer le moteur : \(error.localizedDescription)")
        }
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
        DispatchQueue.main.asyncAfter(deadline: .now() + delai) { [weak self] in self?.demarrer() }
    }

    func reinitialiserRelances() { relances = 0 }

    func arreter() {
        arretVoulu = true
        processus?.terminate()
        processus = nil
    }

    func redemarrer() {
        arreter()
        relances = 0
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in self?.demarrer() }
    }
}
