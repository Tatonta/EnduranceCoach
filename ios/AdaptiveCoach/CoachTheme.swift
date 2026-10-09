import SwiftUI
import UIKit

enum CoachTheme {
    static let accent = Color(red: 1, green: 90 / 255, blue: 31 / 255)
    static let background = Color(red: 9 / 255, green: 9 / 255, blue: 9 / 255)
    static let onAccent = Color.black
    static let positive = Color(red: 131 / 255, green: 204 / 255, blue: 156 / 255)
    static let signalSecondary = Color(red: 145 / 255, green: 188 / 255, blue: 237 / 255)

    static func configureAppearance() {
        let surface = UIColor(white: 0.065, alpha: 1)
        let navigation = UINavigationBarAppearance()
        navigation.configureWithOpaqueBackground()
        navigation.backgroundColor = surface
        navigation.titleTextAttributes = [.foregroundColor: UIColor.white]
        navigation.largeTitleTextAttributes = [.foregroundColor: UIColor.white]
        UINavigationBar.appearance().standardAppearance = navigation
        UINavigationBar.appearance().scrollEdgeAppearance = navigation
        let tabs = UITabBarAppearance()
        tabs.configureWithOpaqueBackground()
        tabs.backgroundColor = surface
        UITabBar.appearance().standardAppearance = tabs
        UITabBar.appearance().scrollEdgeAppearance = tabs
    }
}
