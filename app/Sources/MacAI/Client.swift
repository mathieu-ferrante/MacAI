import Foundation

/// Client HTTP du moteur local (127.0.0.1 + jeton) et lecture du flux d'événements (SSE).
/// Sur le fil principal : port et jeton ne sont jamais lus pendant qu'on les change.
@MainActor
final class Client {
    private var port = 0
    private var jeton = ""
    private let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        // Le moteur envoie un « ping » toutes les 15 s sur le flux : 45 s sans rien = connexion perdue.
        c.timeoutIntervalForRequest = 45
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

    private func requete(_ chemin: String, methode: String = "GET", corps: [String: Any]? = nil,
                         delai: TimeInterval? = 10) -> URLRequest {
        var r = URLRequest(url: URL(string: "http://127.0.0.1:\(port)\(chemin)")!)
        r.httpMethod = methode
        // Requêtes simples : le moteur répond tout de suite (les demandes longues tournent en fond).
        if let delai { r.timeoutInterval = delai }
        r.setValue(jeton, forHTTPHeaderField: "X-MacAI-Jeton")
        if let corps {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: corps)
        }
        return r
    }

    private static func statut(_ r: URLResponse) -> Int { (r as? HTTPURLResponse)?.statusCode ?? 0 }

    /// Renvoie la réponse JSON ; aussi pour 409 (« occupé ») que l'appelant affiche.
    @discardableResult
    func envoyer(_ chemin: String, _ corps: [String: Any] = [:]) async -> [String: Any]? {
        guard pret else { return nil }
        do {
            let (data, r) = try await session.data(for: requete(chemin, methode: "POST", corps: corps))
            let s = Client.statut(r)
            guard s < 300 || s == 409 else { return nil }
            return try JSONSerialization.jsonObject(with: data) as? [String: Any]
        } catch { return nil }
    }

    func lire(_ chemin: String) async -> Any? {
        guard pret else { return nil }
        do {
            let (data, r) = try await session.data(for: requete(chemin))
            guard Client.statut(r) < 300 else { return nil }
            return try JSONSerialization.jsonObject(with: data)
        } catch { return nil }
    }

    /// Flux d'événements : appelle `surEvenement` pour chaque message, jusqu'à coupure.
    func ecouter(_ surEvenement: @escaping @MainActor ([String: Any]) -> Void) async {
        guard pret else { return }
        do {
            let (octets, r) = try await session.bytes(for: requete("/evenements", delai: nil))
            guard Client.statut(r) < 300 else { return }
            for try await ligne in octets.lines {
                guard ligne.hasPrefix("data: ") else { continue }
                let json = String(ligne.dropFirst(6))
                if let data = json.data(using: .utf8),
                   let evt = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    surEvenement(evt)
                }
            }
        } catch {}
    }
}
