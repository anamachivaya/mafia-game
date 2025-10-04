Capacitor iOS wrapper for Mafia Game

This folder contains a skeleton Capacitor project that points the WebView at your hosted Flask app at https://mafia-game-1002.onrender.com/

Note: To build the iOS app you'll need a macOS machine with Xcode installed.

Quick start (on macOS or Linux for development):

1. Install Node.js (v16+ recommended).
2. From this folder install dependencies:

   npm install @capacitor/cli @capacitor/core

3. Initialize Capacitor (this repo already has a capacitor.config.json but you can re-run if needed):

   npx cap init mafia-app com.example.mafia "Mafia Game"

4. Add iOS platform and open in Xcode (must be run on macOS):

   npx cap add ios
   npx cap open ios

5. In Xcode: set your Team for signing, check provisioning, then build/run on a device or simulator.

Notes:
- This Capacitor setup uses a remote server configuration (server.url) so the app loads your hosted web app instead of bundled local files.
- For App Store submission, consider adding a small native screen or native features (push notifications, a native "About" screen) so the app is not considered a thin web wrapper.
- Ensure your server uses HTTPS (it does) and that cookies use Secure and SameSite=None if needed.
