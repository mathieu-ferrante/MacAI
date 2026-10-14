// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "MacAI",
    platforms: [.macOS(.v26)],
    targets: [
        .executableTarget(
            name: "MacAI",
            path: "Sources/MacAI",
            swiftSettings: [.swiftLanguageMode(.v5)],
            linkerSettings: [.linkedFramework("Carbon")]
        )
    ]
)
