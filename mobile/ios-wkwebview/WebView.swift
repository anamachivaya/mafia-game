import SwiftUI
import WebKit

struct WebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.configuration.websiteDataStore = .default()
        // Optionally set cookies before load via context.coordinator
        context.coordinator.syncCookiesAndLoad(webView: webView, url: url)
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator() }

    class Coordinator: NSObject, WKNavigationDelegate {
        func syncCookiesAndLoad(webView: WKWebView, url: URL) {
            // Example: set a cookie named "device_id" or "player_name" before loading the page
            let cookieProps: [HTTPCookiePropertyKey: Any] = [
                .domain: url.host ?? "",
                .path: "/",
                .name: "device_id",
                .value: UUID().uuidString,
                .secure: "TRUE",
                .expires: Date(timeIntervalSinceNow: 60*60*24*365)
            ]
            if let cookie = HTTPCookie(properties: cookieProps) {
                WKWebsiteDataStore.default().httpCookieStore.setCookie(cookie) {
                    DispatchQueue.main.async {
                        webView.load(URLRequest(url: url))
                    }
                }
            } else {
                webView.load(URLRequest(url: url))
            }
        }
    }
}
