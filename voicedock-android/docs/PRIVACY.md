# VoiceDock AI MVP privacy and permissions

## Data behavior

The Phase 2 MVP stores dictation drafts in private application preferences and explicit text captures as individual JSON records in private app storage. It does not contain a cloud AI client, analytics SDK, account connector, background clipboard reader, or arbitrary screen reader. It does not send captured content to VoiceDock/Fazle servers.

Speech recognition is supplied by the recognition service installed on the Android device. Depending on the user’s chosen Android recognition provider, speech may be processed on-device or sent to that provider. VoiceDock shows a listening state only after requesting a real recognition session. Users should consult the installed provider’s privacy terms.

## Permissions

- **Microphone:** requested after a user action and used for active dictation.
- **Display over other apps:** opened through Android Settings after a user action; used only for the movable assistant.
- **Foreground service / microphone foreground service:** keeps the visible assistant and active recognition compliant with Android service rules.
- **Notifications (Android 13+):** supports the visible foreground-service notification.

Accessibility permission, contacts, storage-wide access, Gmail, Drive, and GitHub scopes are not requested by this MVP.

## Control and deletion

Users can clear the current draft and delete each local capture from Knowledge. Android cloud backup is disabled for this MVP; uninstalling the application removes its private local records. Clipboard copies are controlled by Android and the destination app after copying. Share actions occur only after the user taps Share.

A future release must add export, retention controls, encrypted credentials, disconnect-all, Room deletion/cascade tests, and a production legal privacy policy before public distribution.
