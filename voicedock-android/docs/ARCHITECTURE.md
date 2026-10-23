# MVP architecture

- `MainActivity` / Compose screens: onboarding, dashboard, editor, captures, and privacy disclosure.
- `OverlayService`: foreground window lifecycle, draggable controls, and fallback actions.
- `SpeechEngine`: provider-neutral recognition contract.
- `AndroidSpeechEngine`: one Android recognition request and accurate provider callbacks.
- `DictationController`: logical session state, persistence, pause/resume, recoverable reconnection, and bounded exponential delay.
- `TranscriptMerger`: deterministic overlap removal across partial/final session boundaries.
- `DraftRepository`: crash/restart recovery for the current draft.
- `CaptureActivity` / `CaptureRepository`: explicit preview and independent UUID-backed local records.
- `FaithfulFormatter`: offline, non-generative cleanup.

The controller, merger, and formatter are separated from Android UI so core behavior can be tested. Phase 3 should introduce `AIProvider`, capability metadata, `ProviderRouter`, paid-approval policy, and encrypted configuration. Phase 4 should migrate captures/drafts into Room with migrations, foreign keys, FTS, source metadata, and repository interfaces.
