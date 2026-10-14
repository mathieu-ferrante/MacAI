import AVFoundation
import Foundation
import Speech

/// Voix 100 % locale : transcription Apple SpeechAnalyzer (macOS 26+) et synthèse AVSpeechSynthesizer.
/// Le micro n'est ouvert que pendant l'appui sur la touche ; rien ne reste chargé ensuite.
final class Voix: NSObject {
    private let synthese = AVSpeechSynthesizer()
    private var moteurAudio: AVAudioEngine?
    private var analyseur: SpeechAnalyzer?
    private var continuation: AsyncStream<AnalyzerInput>.Continuation?
    private var tacheResultats: Task<Void, Never>?
    private var texteFinal = ""
    private var textePartiel = ""
    private let locale = Locale(identifier: "fr-FR")

    // MARK: - Écoute

    func ecouter(_ surPartiel: @escaping (String) -> Void) async throws {
        guard await AVCaptureDevice.requestAccess(for: .audio) else {
            throw NSError(domain: "MacAI", code: 1, userInfo: [NSLocalizedDescriptionKey: "accès au micro refusé (Réglages > Confidentialité > Micro)"])
        }
        texteFinal = ""
        textePartiel = ""
        let transcripteur = SpeechTranscriber(locale: locale, transcriptionOptions: [],
                                              reportingOptions: [.volatileResults], attributeOptions: [])
        // Modèle de voix français fourni par macOS (téléchargé une fois par le système, puis local).
        if let installation = try await AssetInventory.assetInstallationRequest(supporting: [transcripteur]) {
            try await installation.downloadAndInstall()
        }
        let analyseur = SpeechAnalyzer(modules: [transcripteur])
        self.analyseur = analyseur
        guard let formatCible = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcripteur]) else {
            throw NSError(domain: "MacAI", code: 2, userInfo: [NSLocalizedDescriptionKey: "format audio non pris en charge"])
        }
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

        let audio = AVAudioEngine()
        moteurAudio = audio
        let entree = audio.inputNode
        let formatEntree = entree.outputFormat(forBus: 0)
        let convertisseur = AVAudioConverter(from: formatEntree, to: formatCible)
        entree.installTap(onBus: 0, bufferSize: 4096, format: formatEntree) { tampon, _ in
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
        audio.prepare()
        try audio.start()
    }

    /// Arrête le micro et renvoie le texte complet reconnu.
    func terminer() async -> String {
        moteurAudio?.inputNode.removeTap(onBus: 0)
        moteurAudio?.stop()
        moteurAudio = nil
        continuation?.finish()
        continuation = nil
        if let analyseur {
            try? await analyseur.finalizeAndFinishThroughEndOfInput()
        }
        _ = await tacheResultats?.value
        analyseur = nil
        tacheResultats = nil
        let t = (texteFinal + " " + textePartiel).trimmingCharacters(in: .whitespacesAndNewlines)
        return t
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
