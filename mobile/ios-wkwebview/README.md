iOS WKWebView starter project for Mafia Game

This folder contains a minimal Swift/Xcode project skeleton to load your hosted web app at https://mafia-game-1002.onrender.com using a WKWebView and demonstrate cookie sync.

You must open the Xcode project on macOS to build and run on a device/simulator.

Instructions (on macOS):

1. Open Xcode and create a new project. Alternatively copy the provided source files into a new Xcode project.

2. In Xcode set the Bundle Identifier, Team, and signing.

3. Add the following files into your project (or replace the App target's ContentView / App files with the provided ones):
   - WebView.swift
   - ContentView.swift
   - MafiaApp.swift

4. Update the URL in ContentView.swift if necessary (currently points to https://mafia-game-1002.onrender.com).

5. To pre-populate a cookie before loading, there's a helper function in WebView.swift showing how to set cookies using WKWebsiteDataStore.httpCookieStore.

6. Build and run on a simulator or device.

Files in this folder:
- WebView.swift: WKWebView wrapper with cookie helper
- ContentView.swift: SwiftUI view embedding the WebView
- MafiaApp.swift: Application entrypoint (SwiftUI App)

If you'd like, I can generate a full Xcode project file (.xcodeproj) but that must be downloaded and opened in Xcode on macOS to sign and build.
