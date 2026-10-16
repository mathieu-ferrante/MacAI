import Foundation
import UserNotifications

/// Notifications macOS (tâches planifiées terminées en arrière-plan). L'autorisation n'est demandée qu'à la
/// première notification, pas au lancement.
@MainActor
final class Notifications: NSObject, UNUserNotificationCenterDelegate {
    private var autorisationDemandee = false
    /// Clic sur une notification : (description, texte).
    var surClic: (@MainActor (String, String) -> Void)?

    func installer() {
        UNUserNotificationCenter.current().delegate = self
    }

    func publier(description: String, texte: String, ok: Bool) {
        Task {
            let centre = UNUserNotificationCenter.current()
            if !autorisationDemandee {
                autorisationDemandee = true
                _ = try? await centre.requestAuthorization(options: [.alert, .sound])
            }
            let contenu = UNMutableNotificationContent()
            contenu.title = "MacAI — " + description
            let corps = texte.isEmpty ? (ok ? "Terminé." : "Échec.") : texte
            contenu.body = corps.count > 200 ? String(corps.prefix(199)) + "…" : corps
            contenu.userInfo = ["description": description, "texte": texte]
            let requete = UNNotificationRequest(identifier: UUID().uuidString, content: contenu, trigger: nil)
            try? await centre.add(requete)
        }
    }

    // Affichée même quand MacAI est l'application active (panneau ouvert).
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            didReceive response: UNNotificationResponse) async {
        let infos = response.notification.request.content.userInfo
        let description = infos["description"] as? String ?? ""
        let texte = infos["texte"] as? String ?? ""
        await MainActor.run { self.surClic?(description, texte) }
    }
}
