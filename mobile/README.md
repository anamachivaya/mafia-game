Mobile build options for Mafia Game

This repository now includes two mobile starter options under `mobile/`:

1) capacitor - a Capacitor wrapper configured to load the remote hosted app at https://mafia-game-1002.onrender.com
   - Path: mobile/capacitor
   - Use this to quickly create an iOS app that wraps your hosted website.
   - You'll still need macOS + Xcode to add the iOS platform and build the final IPA.

2) ios-wkwebview - a minimal SwiftUI + WKWebView starter project
   - Path: mobile/ios-wkwebview
   - Use this if you prefer a native iOS project with explicit cookie syncing before page load.
   - Copy the Swift files into an Xcode project and set signing/team.

Capacitor quick commands (run under mobile/capacitor):

```bash
npm install
npx cap add ios   # macOS only
npx cap open ios
```

WKWebView quick steps:
- Open Xcode on macOS
- Create a new SwiftUI App project and replace ContentView.swift, WebView.swift, and App entry with the files under mobile/ios-wkwebview
- Set the bundle id and signing Team, then run on a simulator or device

If you'd like, I can generate a downloadable Xcode project (.xcodeproj) pre-populated with these files, but you will need to open it in Xcode on macOS to set signing and submit to the App Store.
