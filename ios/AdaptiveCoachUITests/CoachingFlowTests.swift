import XCTest

final class CoachingFlowTests: XCTestCase {
    private let app = XCUIApplication()
    private var password = ""
    private var origin = ""

    override func setUpWithError() throws {
        continueAfterFailure = false
        password = try XCTUnwrap(ProcessInfo.processInfo.environment["COACH_UI_TEST_PASSWORD"], "Start the disposable UI backend and pass its access configuration to the runner.")
        origin = try XCTUnwrap(ProcessInfo.processInfo.environment["COACH_UI_TEST_ORIGIN"])
        XCTAssertTrue(origin.hasPrefix("http://localhost:"))
        app.launchArguments = ["-AppleLanguages", "(it)", "-AppleLocale", "it_IT"]
        app.launch()
        XCTAssertTrue(app.buttons["auth-submit"].waitForExistence(timeout: 20), "Use a fresh simulator with no existing athlete session.")
    }

    private func fill(_ field: XCUIElement, with value: String) {
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        let old = field.value as? String ?? ""
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: old.count) + value)
    }

    private func tap(_ element: XCUIElement) {
        _ = element.waitForExistence(timeout: 3)
        for _ in 0..<6 {
            if element.exists && element.isHittable { element.tap(); return }
            app.swipeUp()
        }
        for _ in 0..<10 {
            if element.exists && element.isHittable { element.tap(); return }
            app.swipeDown()
        }
        XCTFail("Control exists but could not be reached: \(element.identifier)")
    }

    private func login(_ account: String) {
        fill(app.textFields["service-origin"], with: origin)
        fill(app.textFields["auth-email"], with: "ui-\(account)@example.test")
        fill(app.secureTextFields["auth-password"], with: password)
        tap(app.buttons["auth-submit"])
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func logout() {
        tap(app.tabBars.buttons["Account"])
        tap(app.buttons["Esci"])
        XCTAssertTrue(app.buttons["auth-submit"].waitForExistence(timeout: 15))
    }

    func testFirstAccessQuestionnaireReviewAndExplicitAdjustment() {
        login("first")
        XCTAssertTrue(app.navigationBars["Conosciamoci"].waitForExistence(timeout: 20))
        XCTAssertFalse(app.tabBars.buttons["Coach"].exists)
        fill(app.descendants(matching: .any).matching(identifier: "profile-goal").firstMatch, with: "Allenarmi con continuita per migliorare la resistenza")
        for _ in 0..<3 { tap(app.buttons["onboarding-continue"]) }
        tap(app.switches["availability-0"])
        tap(app.buttons["onboarding-continue"])
        XCTAssertFalse(app.buttons["onboarding-save"].isEnabled)
        tap(app.switches["profile-consent"])
        capture("Questionario-prima-della-conferma")
        tap(app.buttons["onboarding-save"])
        XCTAssertTrue(app.tabBars.buttons["Coach"].waitForExistence(timeout: 20))
        tap(app.tabBars.buttons["Review"])
        XCTAssertTrue(app.staticTexts["workout-title"].waitForExistence(timeout: 15))
        XCTAssertEqual(app.staticTexts["workout-title"].label, "Corsa facile sintetica")
        capture("Review-ultima-seduta")
        tap(app.tabBars.buttons["Consigli"])
        tap(app.buttons["preview-adjustment"])
        let accept = app.buttons["apply-adjustment"]
        XCTAssertTrue(accept.waitForExistence(timeout: 15))
        XCTAssertFalse(accept.isEnabled)
        capture("Proposta-richiede-conferma")
        tap(app.switches["adjustment-confirmation"])
        XCTAssertTrue(accept.isEnabled)
        tap(accept)
        if app.alerts.firstMatch.waitForExistence(timeout: 15) { app.alerts.buttons["OK"].tap() }
        XCTAssertTrue(app.navigationBars["Consigli"].waitForExistence(timeout: 15))
        tap(app.tabBars.buttons["Review"])
        XCTAssertTrue(app.staticTexts["Versione piano 2"].waitForExistence(timeout: 15))
        tap(app.tabBars.buttons["Consigli"])
        XCTAssertFalse(app.buttons["preview-adjustment"].exists)
        capture("Piano-adattato-nessuna-seconda-proposta")
        logout()
    }

    func testHighHeartRateLapKeepsPlanAndHidesProposal() {
        login("context")
        XCTAssertTrue(app.tabBars.buttons["Coach"].waitForExistence(timeout: 20))
        tap(app.tabBars.buttons["Review"])
        XCTAssertTrue(app.staticTexts["workout-title"].waitForExistence(timeout: 15))
        tap(app.tabBars.buttons["Consigli"])
        let decision = app.descendants(matching: .any).matching(identifier: "program-decision").firstMatch
        XCTAssertTrue(decision.waitForExistence(timeout: 15))
        XCTAssertTrue(decision.label.contains("Mantieni il piano"))
        XCTAssertFalse(app.buttons["preview-adjustment"].exists)
        capture("Lap-FC-alta-mantieni-il-piano")
        logout()
    }
}
