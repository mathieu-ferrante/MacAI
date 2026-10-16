import AVFoundation
import Foundation
import Speech

/// Voix 100 % locale : transcription Apple SpeechAnalyzer (macOS 26+) et synthèse AVSpeechSynthesizer.
/// Le micro n'est ouvert que pendant l'appui sur la touche, ou quelques secondes après une réponse dite
/// (conversation vocale, confirmation à voix haute) ; rien ne reste chargé ensuite.
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

    private var finParole: (@MainActor (Bool) -> Void)?
    private var derniereReplique: ObjectIdentifier?

    override init() {
        super.init()
        synthese.delegate = self
    }

    /// Une lecture est en cours (ou en file d'attente).
    var parle: Bool { finParole != nil || synthese.isSpeaking }

    private lazy var voixFrancaise: AVSpeechSynthesisVoice? = {
        let voix = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix("fr") }
        // Préférence : voix premium, puis améliorée, puis la voix par défaut ; français de France d'abord.
        func meilleure(_ q: AVSpeechSynthesisVoiceQuality) -> AVSpeechSynthesisVoice? {
            voix.first { $0.quality == q && $0.language == "fr-FR" } ?? voix.first { $0.quality == q }
        }
        return meilleure(.premium) ?? meilleure(.enhanced) ?? AVSpeechSynthesisVoice(language: "fr-FR")
    }()

    /// Lit `texte` phrase par phrase (Markdown et adresses retirés, `limite` caractères au plus).
    /// `fin(true)` : lecture allée jusqu'au bout ; `fin(false)` : interrompue (taire(), nouvelle lecture).
    func parler(_ texte: String, limite: Int = 1500, fin: (@MainActor (Bool) -> Void)? = nil) {
        taire()
        let phrases = Voix.phrasesAParler(texte, limite: limite)
        guard !phrases.isEmpty else {
            fin?(true)
            return
        }
        finParole = fin
        for p in phrases {
            let replique = AVSpeechUtterance(string: p)
            replique.voice = voixFrancaise
            replique.rate = 0.52
            derniereReplique = ObjectIdentifier(replique)
            synthese.speak(replique)
        }
    }

    /// Coupe la voix tout de suite (Échap, touche pour parler, nouvelle demande).
    func taire() {
        let fin = finParole
        finParole = nil
        derniereReplique = nil
        synthese.stopSpeaking(at: .immediate)
        fin?(false)
    }

    private func repliqueFinie(_ id: ObjectIdentifier) {
        guard id == derniereReplique else { return }
        derniereReplique = nil
        let fin = finParole
        finParole = nil
        fin?(true)
    }

    /// Texte prêt à être dit : sans Markdown, adresses remplacées par « lien », coupé en phrases,
    /// limité à `limite` caractères (coupé à la fin d'une phrase).
    nonisolated static func phrasesAParler(_ texte: String, limite: Int) -> [String] {
        var t = texte
        func remplacer(_ motif: String, _ par: String) {
            t = t.replacingOccurrences(of: motif, with: par, options: .regularExpression)
        }
        remplacer("(?s)```.*?```", " (bloc de code) ")
        remplacer("!?\\[([^\\]]*)\\]\\([^)]*\\)", "$1")        // [texte](adresse) → texte
        // Adresses (sans la ponctuation qui les suit) : « lien ».
        remplacer("(https?|ftp|file)://[^\\s)>\\]]*[^\\s)>\\].,;:!?]", "lien")
        remplacer("\\bwww\\.[^\\s)>\\]]*[^\\s)>\\].,;:!?]", "lien")
        remplacer("(?m)^\\s*([-*+•]|>)+\\s+", "")                 // puces, citations
        remplacer("(?m)^\\s*\\|?[-:| ]{3,}\\|?\\s*$", "")           // séparateurs de tableau
        remplacer("[*#`~|>]", " ")
        remplacer("(?<=\\w)_(?=\\w)", " ")
        remplacer("_", "")
        remplacer("([^.!?:;,\\s])[ \\t]*\\n+", "$1. ")             // une ligne sans ponctuation = une phrase
        remplacer("\\s+", " ")
        t = t.trimmingCharacters(in: .whitespacesAndNewlines)
        var phrases: [String] = []
        var total = 0
        var tronque = false
        t.enumerateSubstrings(in: t.startIndex..., options: .bySentences) { sous, _, _, arret in
            guard let p = sous?.trimmingCharacters(in: .whitespaces), !p.isEmpty else { return }
            if total + p.count > limite {
                if phrases.isEmpty { phrases.append(String(p.prefix(limite)) + "…") }
                tronque = true
                arret = true
                return
            }
            phrases.append(p)
            total += p.count
        }
        if tronque { phrases.append("La suite est dans le panneau.") }
        return phrases
    }
}

extension Voix: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        let id = ObjectIdentifier(utterance)
        Task { @MainActor in self.repliqueFinie(id) }
    }
}
