# VoiceDock AI — Android MVP

VoiceDock AI is a standalone native Android application. It has its own Gradle root, application ID, Android manifest, source tree, tests, and build lifecycle; it does not import or run the surrounding repository’s backend.

## Implemented

- Kotlin/Gradle Kotlin DSL Android project (minimum API 26, target/compile API 35).
- Compose dashboard, draft editor, local captures, and privacy/permission screens.
- User-initiated overlay and microphone permission setup.
- Foreground-service VoiceDock AI operational assistant with a movable launcher, persisted bounded position, expand, minimize, and dismiss behavior.
- Responsive overlay: phone-width bottom sheet below 600 dp and a draggable 400 dp panel on larger displays.
- Independent microphone, AI-processing, and local-data status indicators plus accessible live status announcements.
- Multiline instruction composer and persistent Capture, Knowledge, AI Write, and Settings tabs; unavailable cloud/business capabilities are labeled offline rather than simulated.
- Android `SpeechRecognizer` adapter behind `SpeechEngine`.
- Logical continuous-dictation controller with explicit listening, temporary-pause, review, and error states.
- Automatic bounded reconnection between provider recognition segments; Pause, Resume, Finish, Cancel preservation, and Clear behavior.
- Persisted finalized/partial draft recovery and overlap-aware segment deduplication.
- Conservative offline Bengali/English spoken punctuation cleanup.
- Editable review plus clipboard and Android share fallback.
- Explicit Share Sheet and `PROCESS_TEXT` capture preview. Every save gets a UUID and a separate local record.
- Unit tests for transcript joining, faithful formatting, dictation lifecycle/retry behavior, and independent microphone/AI status presentation.
- GitHub Actions verification workflow definition for JDK 17, Android SDK 35, tests, lint, and debug assembly; current execution is blocked before runner startup by the repository account billing lock.

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
3. Drag the launcher and verify it remains within the screen. On a phone, verify the panel opens as a bottom sheet; on a 600 dp+ display, verify the 400 dp panel can be repositioned.
4. Expand, collapse, minimize, and close the panel; reopen it and verify the selected tab and expansion preference are retained.
5. Verify Mic, AI, and Local indicators remain independent. AI must continue to show offline during microphone listening and recognition finishing.
6. Tap the microphone, speak English, Bengali, and mixed-language phrases; pause beyond the recognizer timeout and verify the draft remains while it reconnects.
7. Test Pause, Resume, Finish, Cancel, Clear, composer review, and all four tabs.
8. Open the editor, Copy or Share the reviewed draft, and paste it into a normal editable field. Secure/custom targets may reject insertion.
9. Share selected text from another app to VoiceDock AI, edit its preview, save, and confirm it appears under Knowledge.
10. Disable network or interrupt the microphone and confirm the existing committed draft is not removed.
11. Test the keyboard, large font scaling, TalkBack announcements, rotation, and small-screen scrolling.

## Current limitations

- Android recognition capabilities, language models, network need, and timeout behavior depend on the installed recognition service. This app reconnects sessions; it does not promise uninterrupted physical microphone capture.
- The MVP does not yet include Room/FTS, document import/OCR, custom IME, Accessibility insertion, cloud AI providers, OAuth connectors, remote sync, or release signing.
- Captures use private app files and basic local listing rather than the planned Room schema.
- Faithful cleanup is deliberately conservative. AI-structured writing is not active.
- Overlay and speech behavior require a physical Android device or a suitably configured emulator for validation.
- No release APK is produced or claimed until signing and device validation are complete.

See `docs/PHASE_1_2_REPORT.md`, `docs/REVERIFICATION_2026-10-23.md`, `docs/STANDALONE_ANDROID_APP.md`, `docs/APK_BUILD_REPORT_2026-10-23.md`, `docs/PRIVACY.md`, and `docs/ARCHITECTURE.md`.
