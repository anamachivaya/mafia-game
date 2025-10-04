import SwiftUI

struct ContentView: View {
    var body: some View {
        WebView(url: URL(string: "https://mafia-game-1002.onrender.com")!)
            .edgesIgnoringSafeArea(.all)
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
