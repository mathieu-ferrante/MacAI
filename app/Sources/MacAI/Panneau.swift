import AppKit
import SwiftUI

/// Panneau flottant façon Spotlight : apparaît au centre de l'écran, au-dessus des autres fenêtres.
final class Panneau: NSPanel {
    init(etat: Etat) {
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
        contentView = NSHostingView(rootView: VuePanneau(fermer: { [weak self] in self?.orderOut(nil) })
            .environmentObject(etat))
    }

    override var canBecomeKey: Bool { true }

    func basculer() {
        if isVisible && isKeyWindow {
            orderOut(nil)
        } else {
            montrer()
        }
    }

    func montrer() {
        if let ecran = NSScreen.main {
            let f = ecran.visibleFrame
            setFrameOrigin(NSPoint(x: f.midX - frame.width / 2, y: f.midY - frame.height / 2 + f.height * 0.12))
        }
        NSApp.activate()
        makeKeyAndOrderFront(nil)
    }

    override func cancelOperation(_ sender: Any?) {
        orderOut(nil)  // Échap ferme le panneau (la demande en cours continue)
    }
}

struct VuePanneau: View {
    @EnvironmentObject var etat: Etat
    @FocusState private var focus: Bool
    var fermer: () -> Void

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
                    ForEach(etat.etapes) { e in ligneEtape(e) }
                    if let c = etat.confirmation { carteConfirmation(c) }
                    if !etat.reponse.isEmpty {
                        Text(LocalizedStringKey(etat.reponse)).textSelection(.enabled).font(.body)
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
    }

    private var barreSaisie: some View {
        HStack(spacing: 10) {
            Image(systemName: etat.ecoute ? "waveform" : "sparkle")
                .font(.title2).foregroundStyle(etat.ecoute ? Color.red : Color.accentColor)
                .symbolEffect(.pulse, isActive: etat.ecoute || etat.occupe)
            TextField(etat.ecoute ? "J'écoute…" : "Demande-moi n'importe quoi sur ton Mac…", text: $etat.saisie)
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
                .buttonStyle(.plain).help("Parler (ou maintiens la touche Fn)")
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

    private func carteConfirmation(_ c: DemandeConfirmation) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(c.phrase, systemImage: "exclamationmark.shield.fill").foregroundStyle(.orange).font(.callout.bold())
            HStack {
                Button("Refuser") { etat.repondre(false) }.keyboardShortcut(.cancelAction)
                Button("Confirmer") { etat.repondre(true) }.keyboardShortcut(.defaultAction).buttonStyle(.borderedProminent)
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
            Picker("", selection: $etat.modeOral) {
                Label("Écrit", systemImage: "text.alignleft").tag(false)
                Label("Oral", systemImage: "speaker.wave.2").tag(true)
            }
            .pickerStyle(.segmented).frame(width: 170).labelsHidden()
            Spacer()
            Circle().fill(etat.connecte ? .green : .orange).frame(width: 7, height: 7)
            Text(etat.connecte ? "Local · prêt" : etat.statutMoteur).font(.caption).foregroundStyle(.secondary)
        }
    }
}
