import Foundation

// Helper for stderr printing
func printToStderr(_ string: String) {
    let data = (string + "\n").data(using: .utf8)!
    FileHandle.standardError.write(data)
}
