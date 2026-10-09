import XCTest

final class CoachingFlowTests: XCTestCase {
    private let app = XCUIApplication()
    private var password = ""
    private var origin = ""
    private var fixtureLoginSucceeded = false

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

    private func reveal(_ element: XCUIElement) {
        _ = element.waitForExistence(timeout: 3)
        for _ in 0..<6 {
            if element.exists && element.isHittable { return }
            app.swipeUp()
        }
        for _ in 0..<10 {
            if element.exists && element.isHittable { return }
            app.swipeDown()
        }
        XCTFail("Expected control was not found or could not be reached.")
    }

    private func tap(_ element: XCUIElement) {
        reveal(element)
        element.tap()
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

    private func enableToggle(_ identifier: String) {
        let toggle = app.switches[identifier]
        XCTAssertTrue(toggle.waitForExistence(timeout: 10))
        if toggle.value as? String != "1" {
            let control = toggle.switches.firstMatch
            if control.exists { tap(control) }
            else {
                // SwiftUI can expose the whole form row as a Switch; its knob is on the trailing edge.
                toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
            }
        }
        let enabled = expectation(for: NSPredicate(format: "value == '1'"), evaluatedWith: toggle)
        wait(for: [enabled], timeout: 5)
    }

    private func assertScreen(_ element: XCUIElement, timeout: TimeInterval = 20) {
        let arrived = element.waitForExistence(timeout: timeout)
        let message = app.alerts.firstMatch.exists
            ? app.alerts.firstMatch.staticTexts.allElementsBoundByIndex.map { $0.label }.joined(separator: " · ")
            : "Expected screen did not appear."
        XCTAssertTrue(arrived, message)
        if arrived { fixtureLoginSucceeded = true }
    }

    override func tearDownWithError() throws {
        // Only revoke the generated fixture session after a successful fixture login.
        // An existing session detected during setup is left untouched.
        if fixtureLoginSucceeded {
            if app.alerts.firstMatch.exists { app.alerts.buttons["OK"].tap() }
            if app.buttons["Chiudi"].exists && app.buttons["Chiudi"].isHittable { app.buttons["Chiudi"].tap() }
            if app.tabBars.buttons["Account"].exists { app.tabBars.buttons["Account"].tap() }
            if app.buttons["Esci"].exists && app.buttons["Esci"].isHittable { app.buttons["Esci"].tap() }
        }
        app.terminate()
    }

    private func logout() {
        tap(app.tabBars.buttons["Account"])
        tap(app.buttons["Esci"])
        XCTAssertTrue(app.buttons["auth-submit"].waitForExistence(timeout: 15))
    }

    func testFirstAccessQuestionnaireReviewAndExplicitAdjustment() {
        login("first")
        assertScreen(app.navigationBars["Conosciamoci"])
        XCTAssertFalse(app.tabBars.buttons["Coach"].exists)
        fill(app.descendants(matching: .any).matching(identifier: "profile-goal").firstMatch, with: "Allenarmi con continuita per migliorare la resistenza")
        for nextStep in 2...4 {
            tap(app.buttons["onboarding-continue"])
            let step = app.staticTexts["onboarding-step"]
            let transition = expectation(for: NSPredicate(format: "label CONTAINS %@", "Passaggio \(nextStep) di 5"), evaluatedWith: step)
            wait(for: [transition], timeout: 5)
        }
        enableToggle("availability-0")
        tap(app.buttons["onboarding-continue"])
        let summary = expectation(for: NSPredicate(format: "label CONTAINS 'Passaggio 5 di 5'"), evaluatedWith: app.staticTexts["onboarding-step"])
        wait(for: [summary], timeout: 5)
        XCTAssertTrue(app.buttons["onboarding-save"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["onboarding-save"].isEnabled)
        enableToggle("profile-consent")
        capture("Questionario-prima-della-conferma")
        tap(app.buttons["onboarding-save"])
        assertScreen(app.tabBars.buttons["Coach"])
        reveal(app.buttons["chatgpt-connect"])
        XCTAssertTrue(app.buttons["chatgpt-connect"].isEnabled)
        capture("Coach-collegamento-ChatGPT-esplicito")
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
        enableToggle("adjustment-confirmation")
        XCTAssertTrue(accept.isEnabled)
        tap(accept)
        XCTAssertTrue(app.alerts.firstMatch.waitForExistence(timeout: 15))
        let result = app.alerts.firstMatch.staticTexts.allElementsBoundByIndex.map { $0.label }.joined(separator: " · ")
        XCTAssertTrue(result.contains("versione 2"), result)
        app.alerts.buttons["OK"].tap()
        XCTAssertTrue(app.navigationBars["Consigli"].waitForExistence(timeout: 15))
        tap(app.tabBars.buttons["Review"])
        reveal(app.staticTexts["Versione piano 2"])
        XCTAssertTrue(app.staticTexts["Versione piano 2"].waitForExistence(timeout: 15))
        tap(app.tabBars.buttons["Consigli"])
        XCTAssertFalse(app.buttons["preview-adjustment"].exists)
        capture("Piano-adattato-nessuna-seconda-proposta")
        logout()
    }

    func testHighHeartRateLapKeepsPlanAndHidesProposal() {
        login("context")
        assertScreen(app.tabBars.buttons["Coach"])
        tap(app.tabBars.buttons["Review"])
        XCTAssertTrue(app.staticTexts["workout-title"].waitForExistence(timeout: 15))
        tap(app.tabBars.buttons["Consigli"])
        let decision = app.staticTexts["program-decision"]
        XCTAssertTrue(decision.waitForExistence(timeout: 15))
        XCTAssertTrue(decision.label.contains("Mantieni il piano"))
        XCTAssertFalse(app.buttons["preview-adjustment"].exists)
        capture("Lap-FC-alta-mantieni-il-piano")
        logout()
    }
}
