import AppKit
import SwiftUI

/// Panneau flottant façon Spotlight : apparaît au centre de l'écran, au-dessus des autres fenêtres.
final class Panneau: NSPanel {
    private let etat: Etat

    init(etat: Etat) {
        self.etat = etat
        super.init(contentRect: NSRect(x: 0, y: 0, width: 640, height: 420),
                   styleMask: [.titled, .fullSizeContentView, .resizable],
                   backing: .buffered, defer: false)
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        isMovableByWindowBackground = true
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        hidesOnDeactivate = false
        isReleasedWhenClosed = false
        standardWindowButton(.closeButton)?.isHidden = true
        standardWindowButton(.miniaturizeButton)?.isHidden = true
        standardWindowButton(.zoomButton)?.isHidden = true
        contentView = NSHostingView(rootView: VuePanneau(fermer: { [weak self] in self?.fermer() })
            .environmentObject(etat))
    }

    override var canBecomeKey: Bool { true }

    func basculer() {
        if isVisible && isKeyWindow {
            fermer()
        } else {
            montrer()
        }
    }

    /// `auto` : ouvert par MacAI (plan à valider), pas par l'utilisateur : une fermeture par Échap reste
    /// valable (pas d'écoute automatique).
    func montrer(auto: Bool = false) {
        if !auto { etat.ecouteAutoInterdite = false }
        if let ecran = NSScreen.main {
            let f = ecran.visibleFrame
            setFrameOrigin(NSPoint(x: f.midX - frame.width / 2, y: f.midY - frame.height / 2 + f.height * 0.12))
        }
        NSApp.activate()
        makeKeyAndOrderFront(nil)
        etat.apparitions += 1  // le champ de saisie reprend le focus
    }

    override func cancelOperation(_ sender: Any?) {
        fermer()  // Échap ferme le panneau (la demande en cours continue)
        etat.attente = nil  // une consigne attendue (texte sélectionné, zone) est abandonnée
    }

    /// Fermé par l'utilisateur : la voix se tait et le micro ne se rouvre plus tout seul.
    func fermer() {
        orderOut(nil)
        etat.panneauFerme()
    }
}

struct VuePanneau: View {
    @EnvironmentObject var etat: Etat
    @FocusState private var focus: Bool
    var fermer: () -> Void

    /// Réponses orales seules : panneau réduit (étapes résumées en une ligne).
    private var reduit: Bool { etat.modeReponses == .orales }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            barreSaisie
            if !etat.connecte {
                Label(etat.statutMoteur, systemImage: "hourglass").foregroundStyle(.secondary)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    if !etat.derniereDemande.isEmpty && (etat.occupe || !etat.reponse.isEmpty) {
                        Text(etat.derniereDemande).font(.callout).foregroundStyle(.secondary)
                    }
                    if reduit {
                        if !etat.etapes.isEmpty { resumeEtapes }
                    } else {
                        ForEach(etat.etapes) { e in ligneEtape(e) }
                    }
                    if let p = etat.plan { cartePlan(p) }
                    if let c = etat.confirmation { carteConfirmation(c) }
                    if !etat.reponse.isEmpty {
                        // Réponse du modèle (peut reprendre du contenu lu) : seuls les liens https s'ouvrent,
                        // jamais file:, x-apple…, ni d'autres schémas d'applications.
                        Text(LocalizedStringKey(etat.reponse)).textSelection(.enabled).font(.body)
                            .environment(\.openURL, OpenURLAction { url in
                                url.scheme?.lowercased() == "https" ? .systemAction : .discarded
                            })
                    }
                    if !etat.souvenirsAppris.isEmpty {
                        Label("Retenu : " + etat.souvenirsAppris.joined(separator: " · "), systemImage: "brain")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if etat.propositionCompetence && !etat.occupe { carteCompetence }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            barreBas
        }
        .padding(18)
        .frame(minWidth: 520, minHeight: 200)
        .background(.regularMaterial)
        .onAppear { focus = true }
        // Champ désactivé tant que le moteur n'est pas prêt : on redonne le focus une fois connecté.
        .onChange(of: etat.connecte) { _, connecte in
            if connecte { DispatchQueue.main.async { focus = true } }
        }
        .onChange(of: etat.apparitions) { DispatchQueue.main.async { focus = true } }

    }

    private var barreSaisie: some View {
        HStack(spacing: 10) {
            Image(systemName: etat.ecoute ? "waveform" : "sparkle")
                .font(.title2).foregroundStyle(etat.ecoute ? Color.red : Color.accentColor)
                .symbolEffect(.pulse, isActive: etat.ecoute || etat.occupe)
            TextField(etat.ecoute ? "J'écoute…" : etat.attente?.invite ?? "Demande-moi n'importe quoi sur ton Mac…",
                      text: $etat.saisie)
                .textFieldStyle(.plain).font(.title3)
                .focused($focus)
                .onSubmit { etat.envoyer() }
                .disabled(!etat.connecte)
            if etat.occupe {
                Button { etat.arreter() } label: { Image(systemName: "stop.circle.fill").font(.title2) }
                    .buttonStyle(.plain).help("Arrêter")
            } else {
                Button {
                    etat.ecoute ? etat.finirEcoute() : etat.commencerEcoute()
                } label: {
                    Image(systemName: etat.ecoute ? "mic.fill" : "mic").font(.title2)
                }
                .buttonStyle(.plain).help("Parler (ou maintiens ⌥⇧Espace)")
            }
        }
    }

    private func ligneEtape(_ e: Etape) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                switch e.statut {
                case .enCours: ProgressView().controlSize(.small)
                case .ok: Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                case .echec: Image(systemName: "xmark.circle.fill").foregroundStyle(.orange)
                }
                Text(e.texte).font(.callout)
            }
            if !e.detail.isEmpty {
                Text(e.detail).font(.caption).foregroundStyle(.secondary).padding(.leading, 26)
            }
        }
    }

    private var resumeEtapes: some View {
        let finies = etat.etapes.filter { $0.statut != .enCours }.count
        let echecs = etat.etapes.filter { $0.statut == .echec }.count
        return HStack(spacing: 8) {
            if etat.etapes.contains(where: { $0.statut == .enCours }) {
                ProgressView().controlSize(.small)
            } else {
                Image(systemName: echecs > 0 ? "exclamationmark.circle.fill" : "checkmark.circle.fill")
                    .foregroundStyle(echecs > 0 ? .orange : .green)
            }
            Text("\(finies)/\(etat.etapes.count) étape\(etat.etapes.count > 1 ? "s" : "")"
                 + (echecs > 0 ? " · \(echecs) en échec" : ""))
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    /// « Montre-moi avant de faire » : rien ne part sans un clic sur Valider (pas de raccourci Entrée).
    private func cartePlan(_ p: PropositionPlan) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Voici ce que je vais faire", systemImage: "list.number").font(.callout.bold())
            ForEach(Array(p.etapes.enumerated()), id: \.offset) { i, e in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("\(i + 1).").monospacedDigit().foregroundStyle(.secondary)
                    Text(verbatim: e).textSelection(.enabled)
                }
                .font(.callout)
            }
            if etat.modifierPlan {
                TextField("Ce qu'il faut changer (ex. : ne touche pas au dossier Photos)", text: $etat.correctionPlan)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { envoyerCorrection() }
                HStack {
                    Button("Retour") { etat.modifierPlan = false }
                    Button("Refaire le plan") { envoyerCorrection() }
                        .disabled(etat.correctionPlan.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            } else {
                HStack {
                    Button("Annuler") { etat.repondrePlan(false) }
                    Button("Modifier…") { etat.modifierPlan = true }
                    Button("Valider") { etat.repondrePlan(true) }.buttonStyle(.borderedProminent)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(.blue.opacity(0.08)))
    }

    private func envoyerCorrection() {
        let c = etat.correctionPlan.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !c.isEmpty else { return }
        etat.repondrePlan(false, correction: c)
    }

    private func carteConfirmation(_ c: DemandeConfirmation) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(c.phrase, systemImage: "exclamationmark.shield.fill").foregroundStyle(.orange).font(.callout.bold())
            HStack {
                Button("Refuser") { etat.repondre(false) }.keyboardShortcut(.cancelAction)
                // Pas de raccourci Entrée : une action sensible ne se confirme que d'un clic.
                Button("Confirmer") { etat.repondre(true) }.buttonStyle(.borderedProminent)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(.orange.opacity(0.12)))
    }

    private var carteCompetence: some View {
        HStack {
            Label("Je peux retenir cette tâche comme compétence pour la refaire d'un coup.", systemImage: "wand.and.stars")
                .font(.callout)
            Spacer()
            Button("Plus tard") { etat.propositionCompetence = false }
            Button("Créer") { etat.creerCompetence() }.buttonStyle(.borderedProminent)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10).fill(.blue.opacity(0.08)))
    }

    private var barreBas: some View {
        HStack {
            Picker("", selection: $etat.modeReponses) {
                Label("Écrit", systemImage: "text.alignleft").tag(ModeReponses.ecrites)
                Label("Oral", systemImage: "speaker.wave.2").tag(ModeReponses.orales)
                Label("Les deux", systemImage: "text.bubble").tag(ModeReponses.ecritesEtOrales)
            }
            .pickerStyle(.segmented).frame(width: 260).labelsHidden()
            .help("Réponses écrites, dites à voix haute, ou les deux")
            Spacer()
            Circle().fill(etat.connecte ? .green : .orange).frame(width: 7, height: 7)
            Text(etat.connecte ? "Local · prêt" : etat.statutMoteur).font(.caption).foregroundStyle(.secondary)
        }
    }
}
