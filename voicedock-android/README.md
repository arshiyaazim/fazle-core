# VoiceDock AI — Android MVP

This directory is an isolated native Android application added without changing the existing Fazle Core Python service. The current increment implements **Phase 1 and a testable Phase 2 MVP**.

## Implemented

- Kotlin/Gradle Kotlin DSL Android project (minimum API 26, target/compile API 35).
- Compose dashboard, draft editor, local captures, and privacy/permission screens.
- User-initiated overlay and microphone permission setup.
- Foreground-service floating assistant with movable, persisted position; expand, minimize, and dismiss behavior.
- Android `SpeechRecognizer` adapter behind `SpeechEngine`.
- Logical continuous-dictation controller with explicit listening, temporary-pause, review, and error states.
- Automatic bounded reconnection between provider recognition segments; Pause, Resume, Finish, Cancel preservation, and Clear behavior.
- Persisted finalized/partial draft recovery and overlap-aware segment deduplication.
- Conservative offline Bengali/English spoken punctuation cleanup.
- Editable review plus clipboard and Android share fallback.
- Explicit Share Sheet and `PROCESS_TEXT` capture preview. Every save gets a UUID and a separate local record.
- Unit tests for transcript joining, faithful formatting, and dictation lifecycle/retry behavior.
- GitHub Actions verification using JDK 17 and Android SDK 35.

## Build

Requirements: JDK 17, Android SDK Platform 35, and Android SDK Build Tools installed.

```bash
cd voicedock-android
export ANDROID_HOME="$HOME/Android/Sdk"   # adjust as needed
./gradlew testDebugUnitTest assembleDebug
```

Debug APK output:

`app/build/outputs/apk/debug/app-debug.apk`

Install to a connected device:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The checked-in wrapper targets Gradle 8.10.2. No API key or OAuth secret is needed for this MVP.

## Device acceptance check

1. Open VoiceDock AI and grant microphone permission from the user-facing setup.
2. Open floating assistant and grant “display over other apps”; return and tap the button again.
3. Drag the bubble; expand and minimize it; restart the service and verify its position is retained.
4. Tap Voice, speak English, Bengali, and mixed-language phrases; pause beyond the recognizer timeout and verify the draft remains while it reconnects.
5. Test Pause, Resume, Finish, Copy, Clear, and dismissal.
6. Paste the copied draft into a normal editable field. Secure/custom targets may reject insertion; clipboard/share remains the supported fallback.
7. Share selected text from another app to VoiceDock AI, edit its preview, save, and confirm it appears under Knowledge.
8. Disable network or interrupt the microphone and confirm the existing committed draft is not removed.

## Current limitations

- Android recognition capabilities, language models, network need, and timeout behavior depend on the installed recognition service. This app reconnects sessions; it does not promise uninterrupted physical microphone capture.
- The MVP does not yet include Room/FTS, document import/OCR, custom IME, Accessibility insertion, cloud AI providers, OAuth connectors, remote sync, or release signing.
- Captures use private app files and basic local listing rather than the planned Room schema.
- Faithful cleanup is deliberately conservative. AI-structured writing is not active.
- Overlay and speech behavior require a physical Android device or a suitably configured emulator for validation.
- No release APK is produced or claimed until signing and device validation are complete.

See `docs/PHASE_1_2_REPORT.md`, `docs/REVERIFICATION_2026-10-23.md`, `docs/PRIVACY.md`, and `docs/ARCHITECTURE.md`.
