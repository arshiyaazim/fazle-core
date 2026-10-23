# VoiceDock AI standalone Android application

VoiceDock AI is a standalone native Android application, not a Next.js component, WebView wrapper, or feature loaded by the surrounding Python service. The supplied operational-panel concept has been adapted to Android overlay and phone interaction patterns.

## Implemented behavior

- A movable 58 dp launcher defaults near the bottom-right and is always clamped to the visible display.
- On phones below 600 dp width, the assistant opens as a full-width bottom sheet. On larger displays it opens as a 400 dp draggable panel with persisted, bounded coordinates.
- Header actions provide expand/collapse, minimize, and close.
- Microphone, AI, and local-data indicators are separate. Recognition finishing never displays as AI generation, and AI remains explicitly `offline` because no provider is configured.
- The transcript area shows only the current local draft and its display timestamp; it does not invent sources or business data.
- The composer accepts multiline instructions, capture selection, microphone control, and local review. Submitting opens the editor and explicitly does not send a message.
- Pause, Resume, Finish, Cancel, and Clear remain available during dictation.
- Persistent tabs provide focused Capture, Knowledge, AI Write, and Settings summaries and route to implemented app screens.
- Touch controls have a minimum 44 dp target. Status regions use polite accessibility live regions, and microphone errors issue an announcement.

## Application boundary

The Android app currently uses only its private on-device draft and capture stores. It does not connect to, import, or depend on the surrounding repository’s Python modules, PostgreSQL schema, web authentication, static pages, or deployment services. No business-data capability is simulated.

Future connectors must be optional Android modules using explicit OAuth/API authorization, encrypted credentials, least-privilege scopes, and user review. Imported content must never authorize an external action.

## Still requiring device verification

Overlay focus and keyboard behavior, bottom-sheet sizing, large fonts, TalkBack order, rotation, multi-window, status announcements, OEM overlay restrictions, and recognition behavior require an Android device or emulator. The GitHub runner remains unavailable because of the repository account billing lock, so these are not represented as tested.
