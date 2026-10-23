# Phase 1–2 implementation report

Date: 2026-10-23

## Environment inspection

The repository was an established Python/PostgreSQL backend with no Android build. VoiceDock was therefore added under `voicedock-android/` to avoid colliding with the existing top-level `app/` Python package.

Available in the execution environment:

- Python and Git repository tooling.
- No `java` command or JDK.
- No system Gradle command.
- No `ANDROID_HOME`, Android SDK, emulator, or attached device.

The Gradle 8.10.2 wrapper files are checked in, but dependency resolution/build execution cannot start without Java and an Android SDK.

## Plan and risks

1. Establish an independent native Android shell and permission-safe overlay.
2. Make draft preservation and the dictation state machine the first domain behavior.
3. Add review/copy/share and explicit text capture before direct insertion.
4. Compile/test on JDK 17 + SDK 35, then conduct physical-device acceptance tests.
5. Next, replace basic storage with Room and add the provider/router architecture.

Key risks are provider-dependent `SpeechRecognizer` behavior, OEM foreground-service differences, overlays being blocked by policy or user choice, and lack of physical-device validation in this environment. Android 14+ requires the microphone foreground service to be started while the app is visible and microphone permission is already granted; the UI enforces that order.

## Honest status

Source implementation and pure-logic test source are complete for this increment. Build and tests are **blocked by missing environment tooling**, not reported as passing. No APK has been fabricated. Overlay, microphone, and external-app interoperability still require real-device testing.

## Next concrete step

Install JDK 17 and Android SDK Platform 35, run `./gradlew testDebugUnitTest assembleDebug`, fix any compiler/device findings, and execute the checklist in the project README. After that gate, implement Phase 3 provider contracts, encrypted key storage, free-first routing, and failure-policy tests.
