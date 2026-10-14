import Foundation

/// Client HTTP du moteur local (127.0.0.1 + jeton) et lecture du flux d'événements (SSE).
final class Client {
    private var port = 0
    private var jeton = ""
    private let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 3600
        c.timeoutIntervalForResource = 7 * 24 * 3600
        return URLSession(configuration: c)
    }()

    var pret: Bool { port != 0 }

    /// Lit serveur.json écrit par le moteur au démarrage.
    func chargerInfos() -> Bool {
        let f = Moteur.dossier.appendingPathComponent("serveur.json")
        guard let data = try? Data(contentsOf: f),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let p = json["port"] as? Int, let j = json["jeton"] as? String else { return false }
        port = p
        jeton = j
        return true
    }

    func oublierInfos() { port = 0 }

    private func requete(_ chemin: String, methode: String = "GET", corps: [String: Any]? = nil) -> URLRequest {
        var r = URLRequest(url: URL(string: "http://127.0.0.1:\(port)\(chemin)")!)
        r.httpMethod = methode
        r.setValue(jeton, forHTTPHeaderField: "X-MacAI-Jeton")
        if let corps {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: corps)
        }
        return r
    }

    @discardableResult
    func envoyer(_ chemin: String, _ corps: [String: Any] = [:]) async -> [String: Any]? {
        guard pret else { return nil }
        do {
            let (data, _) = try await session.data(for: requete(chemin, methode: "POST", corps: corps))
            return try JSONSerialization.jsonObject(with: data) as? [String: Any]
        } catch { return nil }
    }

    func lire(_ chemin: String) async -> Any? {
        guard pret else { return nil }
        do {
            let (data, _) = try await session.data(for: requete(chemin))
            return try JSONSerialization.jsonObject(with: data)
        } catch { return nil }
    }

    /// Flux d'événements : appelle `surEvenement` pour chaque message, jusqu'à coupure.
    func ecouter(_ surEvenement: @escaping ([String: Any]) -> Void) async {
        guard pret else { return }
        do {
            let (octets, _) = try await session.bytes(for: requete("/evenements"))
            for try await ligne in octets.lines {
                guard ligne.hasPrefix("data: ") else { continue }
                let json = String(ligne.dropFirst(6))
                if let data = json.data(using: .utf8),
                   let evt = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    await MainActor.run { surEvenement(evt) }
                }
            }
        } catch {}
    }
}
