# Al-Rifa’i Android floating assistant UI

The VoiceDock Android shell now presents its overlay as the **Al-Rifa’i Assistant operational workspace**. This is an Android adaptation of the supplied web-panel concept; it is not a Next.js component.

## Implemented behavior

- A movable 58 dp launcher defaults near the bottom-right and is always clamped to the visible display.
- On phones below 600 dp width, the assistant opens as a full-width bottom sheet. On larger displays it opens as a 400 dp draggable panel with persisted, bounded coordinates.
- Header actions provide expand/collapse, minimize, and close.
- Microphone, AI, and local-data indicators are separate. Recognition finishing never displays as AI generation, and AI remains explicitly `offline` because no provider is configured.
- The transcript area shows only the current local draft and its display timestamp; it does not invent sources or business data.
- The composer accepts multiline instructions, capture selection, microphone control, and local review. Submitting opens the editor and explicitly does not send a message.
- Pause, Resume, Finish, and Clear remain available during dictation.
- Persistent tabs provide focused Capture, Knowledge, AI Write, and Settings summaries and route to implemented app screens.
- Touch controls have a minimum 44 dp target. Status regions use polite accessibility live regions, and microphone errors issue an announcement.

## Security boundary

This MVP has no authenticated Al-Rifa’i business API connection. It cannot read Vessel Register, Accounts, Review, WhatsApp, PostgreSQL, employee, vessel, or cash records. The UI labels data as local and AI as offline rather than simulating access.

Any future business API adapter must reuse server-side authentication and authorization. Android UI state must never be treated as authorization. Admin, Super Admin, Supervisor, Accountant gates, and WA-02 restrictions must be enforced by the existing backend for every request. All mutations must remain draft → review → authorized approval; imported text must never authorize an action.

## Still requiring device verification

Overlay focus and keyboard behavior, bottom-sheet sizing, large fonts, TalkBack order, rotation, multi-window, status announcements, OEM overlay restrictions, and recognition behavior require an Android device or emulator. The GitHub runner remains unavailable because of the repository account billing lock, so these are not represented as tested.
