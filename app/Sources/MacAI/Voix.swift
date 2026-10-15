import AVFoundation
import Foundation
import Speech

/// Voix 100 % locale : transcription Apple SpeechAnalyzer (macOS 26+) et synthèse AVSpeechSynthesizer.
/// Le micro n'est ouvert que pendant l'appui sur la touche ; rien ne reste chargé ensuite.
@MainActor
final class Voix: NSObject {
    private let synthese = AVSpeechSynthesizer()
    private var moteurAudio: AVAudioEngine?
    private var analyseur: SpeechAnalyzer?
    private var continuation: AsyncStream<AnalyzerInput>.Continuation?
    private var tacheResultats: Task<Void, Never>?
    private var texteFinal = ""
    private var textePartiel = ""
    private var annule = false          // touche relâchée : posé par terminer() avant toute attente
    private var preparation: Task<Void, Error>?
    private let locale = Locale(identifier: "fr-FR")

    /// Relâchement pendant la préparation : on s'arrête sans erreur.
    private struct Annulee: Error {}

    // MARK: - Écoute

    /// Lance l'écoute tout de suite (de façon synchrone) et renvoie la tâche de préparation.
    /// Si elle échoue, tout est déjà refermé (micro, analyseur).
    func ecouter(_ surPartiel: @escaping @MainActor (String) -> Void) -> Task<Void, Error> {
        annule = false
        let tache = Task { [weak self] in
            guard let self else { return }
            do {
                try await self.preparer(surPartiel)
            } catch is Annulee {
                self.nettoyer()
            } catch {
                self.nettoyer()
                throw error
            }
        }
        preparation = tache
        return tache
    }

    private func verifierAnnulation() throws {
        if annule { throw Annulee() }
    }

    private func preparer(_ surPartiel: @escaping @MainActor (String) -> Void) async throws {
        guard await AVCaptureDevice.requestAccess(for: .audio) else {
            throw NSError(domain: "MacAI", code: 1, userInfo: [NSLocalizedDescriptionKey: "accès au micro refusé (Réglages > Confidentialité > Micro)"])
        }
        try verifierAnnulation()
        texteFinal = ""
        textePartiel = ""
        let transcripteur = SpeechTranscriber(locale: locale, transcriptionOptions: [],
                                              reportingOptions: [.volatileResults], attributeOptions: [])
        // Modèle de voix français fourni par macOS (téléchargé une fois par le système, puis local).
        if let installation = try await AssetInventory.assetInstallationRequest(supporting: [transcripteur]) {
            try verifierAnnulation()
            try await installation.downloadAndInstall()
        }
        try verifierAnnulation()
        let analyseur = SpeechAnalyzer(modules: [transcripteur])
        self.analyseur = analyseur
        guard let formatCible = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcripteur]) else {
            throw NSError(domain: "MacAI", code: 2, userInfo: [NSLocalizedDescriptionKey: "format audio non pris en charge"])
        }
        try verifierAnnulation()
        let (flux, continuation) = AsyncStream<AnalyzerInput>.makeStream()
        self.continuation = continuation

        tacheResultats = Task { [weak self] in
            do {
                for try await r in transcripteur.results {
                    guard let self else { return }
                    let t = String(r.text.characters)
                    if r.isFinal {
                        self.texteFinal += (self.texteFinal.isEmpty ? "" : " ") + t
                        self.textePartiel = ""
                    } else {
                        self.textePartiel = t
                    }
                    surPartiel((self.texteFinal + " " + self.textePartiel).trimmingCharacters(in: .whitespaces))
                }
            } catch {}
        }
        try await analyseur.start(inputSequence: flux)
        try verifierAnnulation()  // relâchée pendant la préparation : on n'ouvre pas le micro

        let audio = AVAudioEngine()
        moteurAudio = audio
        let entree = audio.inputNode
        let formatEntree = entree.outputFormat(forBus: 0)
        entree.installTap(onBus: 0, bufferSize: 4096, format: formatEntree,
                          block: Voix.traitementAudio(formatEntree, formatCible, continuation))
        audio.prepare()
        try audio.start()
    }

    /// Conversion des tampons du micro vers le format de l'analyseur. Fabriquée hors du fil principal
    /// (fonction non isolée) : la fermeture est appelée sur le fil audio, elle ne doit pas hériter de MainActor.
    private nonisolated static func traitementAudio(_ formatEntree: AVAudioFormat, _ formatCible: AVAudioFormat,
                                                    _ continuation: AsyncStream<AnalyzerInput>.Continuation) -> AVAudioNodeTapBlock {
        let convertisseur = AVAudioConverter(from: formatEntree, to: formatCible)
        return { tampon, _ in
            guard let convertisseur else { return }
            let ratio = formatCible.sampleRate / formatEntree.sampleRate
            let capacite = AVAudioFrameCount(Double(tampon.frameLength) * ratio) + 64
            guard let sortie = AVAudioPCMBuffer(pcmFormat: formatCible, frameCapacity: capacite) else { return }
            var fourni = false
            var erreur: NSError?
            convertisseur.convert(to: sortie, error: &erreur) { _, statut in
                if fourni { statut.pointee = .noDataNow; return nil }
                fourni = true
                statut.pointee = .haveData
                return tampon
            }
            if erreur == nil && sortie.frameLength > 0 {
                continuation.yield(AnalyzerInput(buffer: sortie))
            }
        }
    }

    /// Ferme tout sans attendre de résultat (échec ou annulation pendant la préparation).
    private func nettoyer() {
        moteurAudio?.inputNode.removeTap(onBus: 0)
        moteurAudio?.stop()
        moteurAudio = nil
        continuation?.finish()
        continuation = nil
        tacheResultats?.cancel()
        tacheResultats = nil
        if let a = analyseur {
            analyseur = nil
            Task { await a.cancelAndFinishNow() }
        }
    }

    /// Arrête le micro et renvoie (dans la tâche) le texte complet reconnu. L'annulation est posée tout de
    /// suite, avant toute attente : une préparation encore en cours n'ouvrira pas le micro.
    func terminer() -> Task<String, Never> {
        annule = true
        let enCours = preparation
        preparation = nil
        return Task { [weak self] in
            _ = try? await enCours?.value   // attend la fin de la préparation éventuelle
            guard let self else { return "" }
            guard self.moteurAudio != nil else {  // micro jamais ouvert (annulé ou échec)
                self.nettoyer()
                return ""
            }
            self.moteurAudio?.inputNode.removeTap(onBus: 0)
            self.moteurAudio?.stop()
            self.moteurAudio = nil
            self.continuation?.finish()
            self.continuation = nil
            if let analyseur = self.analyseur {
                try? await analyseur.finalizeAndFinishThroughEndOfInput()
            }
            _ = await self.tacheResultats?.value
            self.analyseur = nil
            self.tacheResultats = nil
            return (self.texteFinal + " " + self.textePartiel).trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }

    // MARK: - Synthèse

    private lazy var voixFrancaise: AVSpeechSynthesisVoice? = {
        let voix = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix("fr") }
        // Préférence : voix premium, puis améliorée, puis la voix par défaut.
        return voix.first { $0.quality == .premium } ?? voix.first { $0.quality == .enhanced }
            ?? AVSpeechSynthesisVoice(language: "fr-FR")
    }()

    func parler(_ texte: String) {
        let propre = texte.replacingOccurrences(of: "*", with: "").replacingOccurrences(of: "#", with: "")
        let phrase = AVSpeechUtterance(string: String(propre.prefix(600)))
        phrase.voice = voixFrancaise
        phrase.rate = 0.52
        synthese.stopSpeaking(at: .immediate)
        synthese.speak(phrase)
    }

    func taire() {
        synthese.stopSpeaking(at: .immediate)
    }
}
