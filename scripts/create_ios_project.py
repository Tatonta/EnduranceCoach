"""Rebuild the dependency-free Xcode project and original, opaque placeholder app icon."""

import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ios"


def identifier(name):
    return hashlib.sha256(name.encode()).hexdigest()[:24].upper()


def openstep(value):
    if isinstance(value, dict):
        return (
            "{\n"
            + "\n".join(f"{json.dumps(key)} = {openstep(item)};" for key, item in value.items())
            + "\n}"
        )
    if isinstance(value, list):
        return "(" + ", ".join(openstep(item) for item in value) + ")"
    return str(value) if isinstance(value, int) else json.dumps(value)


def icon():
    """Draw three track lanes with an accent marker. Original code, no external artwork."""
    path = ROOT / "AdaptiveCoach" / "Assets.xcassets" / "AppIcon.appiconset"
    path.mkdir(parents=True, exist_ok=True)
    width = 1024
    raw = bytearray()
    for y in range(width):
        raw.append(0)
        for x in range(width):
            # Signed distance to a stadium track, centered in a full opaque square.
            distance = math.hypot(x - 512, max(abs(y - 512) - 135, 0))
            track = any(abs(distance - radius) <= 13 for radius in (150, 202, 254))
            marker = math.hypot(x - 766, y - 512) < 37
            raw.extend((111, 246, 199) if marker else (238, 237, 255) if track else (55, 48, 163))

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, width, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    (path / "AppIcon.png").write_bytes(png)
    (path / "Contents.json").write_text(
        json.dumps(
            {
                "images": [
                    {
                        "filename": "AppIcon.png",
                        "idiom": "universal",
                        "platform": "ios",
                        "size": "1024x1024",
                    }
                ],
                "info": {"author": "xcode", "version": 1},
            },
            indent=2,
        )
        + "\n"
    )
    (path.parent / "Contents.json").write_text('{"info":{"author":"xcode","version":1}}\n')


def generate():
    objects = {}

    def add(object_name, **fields):
        key = identifier(object_name)
        objects[key] = fields
        return key

    app_target, test_target, ui_target, project = map(
        identifier, ("app-target", "test-target", "ui-target", "project")
    )
    app_product = add(
        "app-product",
        isa="PBXFileReference",
        explicitFileType="wrapper.application",
        path="AdaptiveCoach.app",
        sourceTree="BUILT_PRODUCTS_DIR",
    )
    test_product = add(
        "test-product",
        isa="PBXFileReference",
        explicitFileType="wrapper.cfbundle",
        path="AdaptiveCoachTests.xctest",
        sourceTree="BUILT_PRODUCTS_DIR",
    )
    ui_product = add(
        "ui-product",
        isa="PBXFileReference",
        explicitFileType="wrapper.cfbundle",
        path="AdaptiveCoachUITests.xctest",
        sourceTree="BUILT_PRODUCTS_DIR",
    )
    ui_source = add(
        "ui-source",
        isa="PBXFileReference",
        lastKnownFileType="sourcecode.swift",
        path="CoachingFlowTests.swift",
        sourceTree="<group>",
    )
    ui_group = add(
        "ui-group",
        isa="PBXGroup",
        children=[ui_source],
        path="AdaptiveCoachUITests",
        sourceTree="<group>",
    )
    app_sources, app_resources, app_children = [], [], []
    for file in sorted((ROOT / "AdaptiveCoach").glob("*.swift")):
        ref = add(
            f"app-file-{file.name}",
            isa="PBXFileReference",
            lastKnownFileType="sourcecode.swift",
            path=file.name,
            sourceTree="<group>",
        )
        app_children.append(ref)
        app_sources.append(add(f"app-build-{file.name}", isa="PBXBuildFile", fileRef=ref))
    for name, kind, resource in (
        ("Info.plist", "text.plist.xml", False),
        ("AdaptiveCoach.entitlements", "text.plist.entitlements", False),
        ("PrivacyInfo.xcprivacy", "text.xml", True),
        ("Assets.xcassets", "folder.assetcatalog", True),
    ):
        ref = add(
            f"app-file-{name}",
            isa="PBXFileReference",
            lastKnownFileType=kind,
            path=name,
            sourceTree="<group>",
        )
        app_children.append(ref)
        if resource:
            app_resources.append(add(f"app-build-{name}", isa="PBXBuildFile", fileRef=ref))
    tests = add(
        "test-source",
        isa="PBXFileReference",
        lastKnownFileType="sourcecode.swift",
        path="ContractTests.swift",
        sourceTree="<group>",
    )
    fixtures = add(
        "test-fixtures",
        isa="PBXFileReference",
        lastKnownFileType="folder",
        path="Fixtures",
        sourceTree="<group>",
    )
    app_group = add(
        "app-group",
        isa="PBXGroup",
        children=app_children,
        path="AdaptiveCoach",
        sourceTree="<group>",
    )
    test_group = add(
        "test-group",
        isa="PBXGroup",
        children=[tests, fixtures],
        path="AdaptiveCoachTests",
        sourceTree="<group>",
    )
    products = add(
        "products",
        isa="PBXGroup",
        children=[app_product, test_product, ui_product],
        name="Products",
        sourceTree="<group>",
    )
    main_group = add(
        "main-group",
        isa="PBXGroup",
        children=[app_group, test_group, ui_group, products],
        sourceTree="<group>",
    )

    def phase(name, kind, files):
        return add(
            name,
            isa=kind,
            buildActionMask=2147483647,
            files=files,
            runOnlyForDeploymentPostprocessing=0,
        )

    common = {
        "SDKROOT": "iphoneos",
        "IPHONEOS_DEPLOYMENT_TARGET": "17.0",
        "SWIFT_VERSION": "5.0",
        "CLANG_ENABLE_MODULES": "YES",
        "ENABLE_USER_SCRIPT_SANDBOXING": "YES",
    }

    def configs(name, settings):
        refs = []
        for configuration in ("Debug", "Release"):
            options = {
                **settings,
                "SWIFT_OPTIMIZATION_LEVEL": "-Onone" if configuration == "Debug" else "-O",
            }
            if configuration == "Debug":
                options.update(
                    {
                        "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "DEBUG",
                        "ENABLE_TESTABILITY": "YES",
                        "DEBUG_INFORMATION_FORMAT": "dwarf",
                    }
                )
            else:
                options["DEBUG_INFORMATION_FORMAT"] = "dwarf-with-dsym"
            refs.append(
                add(
                    f"{name}-{configuration}",
                    isa="XCBuildConfiguration",
                    name=configuration,
                    buildSettings=options,
                )
            )
        return add(
            f"{name}-configs",
            isa="XCConfigurationList",
            buildConfigurations=refs,
            defaultConfigurationIsVisible=0,
            defaultConfigurationName="Release",
        )

    app_configs = configs(
        "app",
        {
            "PRODUCT_NAME": "$(TARGET_NAME)",
            "PRODUCT_BUNDLE_IDENTIFIER": "com.example.AdaptiveCoach",
            "INFOPLIST_FILE": "AdaptiveCoach/Info.plist",
            "CODE_SIGN_ENTITLEMENTS": "AdaptiveCoach/AdaptiveCoach.entitlements",
            "CODE_SIGN_STYLE": "Automatic",
            "CURRENT_PROJECT_VERSION": "1",
            "MARKETING_VERSION": "0.1.0",
            "TARGETED_DEVICE_FAMILY": "1",
            "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator",
            "SUPPORTS_MACCATALYST": "NO",
            "ASSETCATALOG_COMPILER_APPICON_NAME": "AppIcon",
            "SWIFT_EMIT_LOC_STRINGS": "YES",
            "LD_RUNPATH_SEARCH_PATHS": "$(inherited) @executable_path/Frameworks",
        },
    )
    test_configs = configs(
        "test",
        {
            "PRODUCT_NAME": "$(TARGET_NAME)",
            "PRODUCT_BUNDLE_IDENTIFIER": "com.example.AdaptiveCoachTests",
            "GENERATE_INFOPLIST_FILE": "YES",
            "TARGETED_DEVICE_FAMILY": "1",
            "CODE_SIGN_STYLE": "Automatic",
            "TEST_HOST": "$(BUILT_PRODUCTS_DIR)/AdaptiveCoach.app/AdaptiveCoach",
            "BUNDLE_LOADER": "$(TEST_HOST)",
            "LD_RUNPATH_SEARCH_PATHS": "$(inherited) @executable_path/Frameworks @loader_path/Frameworks",
        },
    )
    proxy = add(
        "test-proxy",
        isa="PBXContainerItemProxy",
        containerPortal=project,
        proxyType=1,
        remoteGlobalIDString=app_target,
        remoteInfo="AdaptiveCoach",
    )
    dependency = add(
        "test-dependency", isa="PBXTargetDependency", target=app_target, targetProxy=proxy
    )
    ui_configs = configs(
        "ui",
        {
            "PRODUCT_NAME": "$(TARGET_NAME)",
            "PRODUCT_BUNDLE_IDENTIFIER": "com.example.AdaptiveCoachUITests",
            "GENERATE_INFOPLIST_FILE": "YES",
            "TARGETED_DEVICE_FAMILY": "1",
            "CODE_SIGN_STYLE": "Automatic",
            "TEST_TARGET_NAME": "AdaptiveCoach",
            "LD_RUNPATH_SEARCH_PATHS": "$(inherited) @executable_path/Frameworks @loader_path/Frameworks",
        },
    )
    ui_dependency = add(
        "ui-dependency", isa="PBXTargetDependency", target=app_target, targetProxy=proxy
    )
    add(
        "ui-target",
        isa="PBXNativeTarget",
        buildConfigurationList=ui_configs,
        buildPhases=[
            phase(
                "ui-sources",
                "PBXSourcesBuildPhase",
                [add("ui-build", isa="PBXBuildFile", fileRef=ui_source)],
            ),
            phase("ui-frameworks", "PBXFrameworksBuildPhase", []),
            phase("ui-resources", "PBXResourcesBuildPhase", []),
        ],
        buildRules=[],
        dependencies=[ui_dependency],
        name="AdaptiveCoachUITests",
        productName="AdaptiveCoachUITests",
        productReference=ui_product,
        productType="com.apple.product-type.bundle.ui-testing",
    )
    add(
        "app-target",
        isa="PBXNativeTarget",
        buildConfigurationList=app_configs,
        buildPhases=[
            phase("app-sources", "PBXSourcesBuildPhase", app_sources),
            phase("app-frameworks", "PBXFrameworksBuildPhase", []),
            phase("app-resources", "PBXResourcesBuildPhase", app_resources),
        ],
        buildRules=[],
        dependencies=[],
        name="AdaptiveCoach",
        productName="AdaptiveCoach",
        productReference=app_product,
        productType="com.apple.product-type.application",
    )
    add(
        "test-target",
        isa="PBXNativeTarget",
        buildConfigurationList=test_configs,
        buildPhases=[
            phase(
                "test-sources",
                "PBXSourcesBuildPhase",
                [add("test-build", isa="PBXBuildFile", fileRef=tests)],
            ),
            phase("test-frameworks", "PBXFrameworksBuildPhase", []),
            phase(
                "test-resources",
                "PBXResourcesBuildPhase",
                [add("fixtures-build", isa="PBXBuildFile", fileRef=fixtures)],
            ),
        ],
        buildRules=[],
        dependencies=[dependency],
        name="AdaptiveCoachTests",
        productName="AdaptiveCoachTests",
        productReference=test_product,
        productType="com.apple.product-type.bundle.unit-test",
    )
    add(
        "project",
        isa="PBXProject",
        attributes={
            "LastUpgradeCheck": "1600",
            "TargetAttributes": {
                app_target: {
                    "CreatedOnToolsVersion": "16.0",
                    "SystemCapabilities": {"com.apple.HealthKit": {"enabled": 1}},
                },
                test_target: {"CreatedOnToolsVersion": "16.0", "TestTargetID": app_target},
                ui_target: {"CreatedOnToolsVersion": "16.0", "TestTargetID": app_target},
            },
        },
        buildConfigurationList=configs("project", common),
        compatibilityVersion="Xcode 14.0",
        developmentRegion="it",
        knownRegions=["it", "en", "Base"],
        mainGroup=main_group,
        productRefGroup=products,
        projectDirPath="",
        projectRoot="",
        targets=[app_target, test_target, ui_target],
    )
    path = ROOT / "AdaptiveCoach.xcodeproj"
    path.mkdir(parents=True, exist_ok=True)
    (path / "project.pbxproj").write_text(
        "// !$*UTF8*$!\n"
        + openstep(
            {
                "archiveVersion": 1,
                "classes": {},
                "objectVersion": 56,
                "objects": objects,
                "rootObject": project,
            }
        )
        + "\n"
    )
    scheme_dir = path / "xcshareddata" / "xcschemes"
    scheme_dir.mkdir(parents=True, exist_ok=True)
    app_ref = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{app_target}" BuildableName="AdaptiveCoach.app" BlueprintName="AdaptiveCoach" ReferencedContainer="container:AdaptiveCoach.xcodeproj"/>'
    test_ref = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{test_target}" BuildableName="AdaptiveCoachTests.xctest" BlueprintName="AdaptiveCoachTests" ReferencedContainer="container:AdaptiveCoach.xcodeproj"/>'
    (scheme_dir / "AdaptiveCoach.xcscheme").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1600" version="1.3">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{app_ref}</BuildActionEntry></BuildActionEntries></BuildAction>
<TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES"><Testables><TestableReference skipped="NO">{test_ref}</TestableReference></Testables></TestAction>
<LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0">{app_ref}</BuildableProductRunnable></LaunchAction>
<ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{app_ref}</BuildableProductRunnable></ProfileAction>
<AnalyzeAction buildConfiguration="Debug"/>
<ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
""")
    ui_ref = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{ui_target}" BuildableName="AdaptiveCoachUITests.xctest" BlueprintName="AdaptiveCoachUITests" ReferencedContainer="container:AdaptiveCoach.xcodeproj"/>'
    ui_scheme = (scheme_dir / "AdaptiveCoach.xcscheme").read_text().replace(test_ref, ui_ref)
    (scheme_dir / "AdaptiveCoachUI.xcscheme").write_text(ui_scheme)
    icon()
    return len(app_sources)


if __name__ == "__main__":
    print(f"Generated Xcode project with {generate()} Swift source files")
