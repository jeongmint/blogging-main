import AppKit
import Foundation

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: swift generate_b_server_icon.swift OUTPUT.png\n", stderr)
    exit(1)
}

let canvasSize = NSSize(width: 1024, height: 1024)
guard let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: Int(canvasSize.width),
    pixelsHigh: Int(canvasSize.height),
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 0
) else {
    fputs("Could not create the icon canvas.\n", stderr)
    exit(1)
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)

NSColor.clear.setFill()
NSRect(origin: .zero, size: canvasSize).fill()
NSGraphicsContext.current?.shouldAntialias = true
NSGraphicsContext.current?.imageInterpolation = .high

let pen = "🖊️" as NSString
let font = NSFont(name: "Apple Color Emoji", size: 760)
    ?? NSFont.systemFont(ofSize: 760)
let attributes: [NSAttributedString.Key: Any] = [.font: font]
let penSize = pen.size(withAttributes: attributes)
let origin = NSPoint(
    x: (canvasSize.width - penSize.width) / 2,
    y: (canvasSize.height - penSize.height) / 2 + 14
)

pen.draw(at: origin, withAttributes: attributes)
NSGraphicsContext.restoreGraphicsState()

guard let pngData = bitmap.representation(using: .png, properties: [:]) else {
    fputs("Could not render the pen icon.\n", stderr)
    exit(1)
}

try pngData.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
