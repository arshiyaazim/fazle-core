# VoiceDock AI re-verification and gap audit

Date: 2026-10-23
Scope rechecked: master prompt, with implementation priority limited to Phase 1 and Phase 2 as explicitly requested.

## Corrections made during re-verification

- Prevented intentional Pause and Cancel from being overwritten by late `SpeechRecognizer.ERROR_CLIENT` callbacks.
- Made the dictation state coordinator Android-independent and added deterministic tests for pause, resume, finish, cancel, late errors, bounded recovery, and retry-budget reset.
- Preserved partial text on Cancel rather than silently dropping it.
- Added the explicit PROCESSING transition during Finish.
- Changed the dismissed overlay service from sticky to non-sticky.
- Added the missing Settings control to the floating panel.
- Bounded overlay coordinates to the visible screen and removed the no-limits window flag.
- Added service startup guards for revoked microphone/overlay permission and foreground-service security failures.
- Added recognition initialization/start exception handling.
- Added persisted Bengali/English recognition selection with an explicit mixed-language provider limitation.
- Added a real manual-capture screen rather than routing Capture to the library.
- Made capture writes atomic.
- Disabled Android cloud backup for local-only MVP records.
- Added Android CI for JDK 17, SDK 35, unit tests, lint, debug assembly, and APK/report artifacts.

## Requirement coverage matrix

| Area | Re-verification result |
|---|---|
| Repository/environment inspection | Complete. Existing Python project preserved; Android project isolated. Local environment still lacks JDK/SDK. |
| Android shell / Gradle Kotlin DSL | Implemented; CI is the authoritative build environment. |
| Floating button/panel | Implemented in source: drag, expand, minimize, dismiss, persisted bounded position, foreground notification, denial guards. Physical-device verification remains required. |
| Continuous logical dictation | Implemented with a provider-neutral engine, explicit phases, persisted segments, bounded reconnect, pause/resume/finish/cancel/clear, and overlap removal. Physical microphone behavior remains provider/device-dependent. |
| Bengali and English | Language selection and Bengali/English cleanup tests exist. Mixed-language recognition depends on the installed Android service and is not claimed as universally supported. |
| Faithful cleanup | Implemented conservatively and unit-tested. Automatic semantic punctuation and AI-Structured mode are not Phase 2-complete. |
| Review/insertion fallback | Editable review, Copy, and Share implemented. IME and Accessibility insertion are Phase 6 and absent. |
| Explicit capture | Share Sheet, PROCESS_TEXT, and manual text capture implemented with preview and unique records. Files/SAF are Phase 4 and absent. |
| Durable knowledge system | Basic private-file capture persistence only. Room, FTS, entities, migrations, search, collections, and RAG are Phase 4 and absent. |
| AI providers/router | Absent by design pending Phase 3. No AI/provider capability is claimed. |
| Gmail/Drive/GitHub | Absent by design pending Phase 5. No account access is claimed. |
| Security | Explicit permissions, no hard-coded secrets, cleartext disabled, backup disabled, no background clipboard/screen collection, and privacy documentation. Keystore applies when credentials arrive in Phase 3/5. |
| Automated tests | Core merger, formatter, and dictation coordinator tests exist. Instrumentation/device tests are still absent. |
| APK | Produced only if Android CI/build succeeds. No local APK is claimed because local Android tooling is unavailable. |

## Master-prompt gaps intentionally not represented as complete

The current project is not the complete seven-phase product. The following remain: Room/SQLite and migrations, WorkManager jobs, SAF file import, document parsers/OCR, FTS/RAG, AI provider adapters and routing, encrypted provider credentials, budgets/usage, custom IME, optional Accessibility service, OAuth connectors, account sync, all fourteen final screens, instrumentation tests, release signing, and production release/privacy review.

No placeholder connector/provider modules were created, because empty modules would imply capability that does not exist.

## Remaining device risks

- OEM overlay restrictions and window behavior.
- Recognition service language support and timeout semantics.
- Foreground microphone-service behavior across Android/OEM versions.
- Notification denial behavior on Android 13+.
- External app Share Sheet and PROCESS_TEXT interoperability.
- Rotation, multi-window, font scaling, TalkBack, and small-screen layout checks.

Use the manual checklist in `README.md` after obtaining the CI APK or building with Android Studio.
