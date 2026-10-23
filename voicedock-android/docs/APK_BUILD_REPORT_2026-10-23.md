# VoiceDock AI APK build report

Date: 2026-10-23
Project: standalone native Android application at `voicedock-android/`
Version: `0.2.0` (`versionCode 2`)

## Build-kit execution

The supplied `build-android-apk.sh` was downloaded from the Google Drive folder `Android APK build kit` and executed through the background process tool against the standalone Android Gradle root.

Result: exited at the JDK installation step with code 100. The process was not killed by a 30-second timeout and did not run out of memory.

```text
Failed to fetch deb.debian.org ... Connection failed
Unable to locate package openjdk-21-jdk-headless
```

## Fallback attempts

- JDK 21.0.8 was successfully bootstrapped from the allowed PyPI host using `jdk4py`.
- The checked-in Gradle wrapper then attempted to fetch Gradle 8.10.2.
- `services.gradle.org` was rejected by this sandbox with an SSL handshake termination.
- Direct checks of `dl.google.com` for Android command-line tools, Android Maven artifacts, and SDK packages were also terminated by the sandbox network policy.
- A PyPI Android SDK manager fallback installed, but its required GitHub raw metadata endpoint was likewise blocked; Android packages would still ultimately require Android distribution hosts.
- GitHub Actions cannot provide the build fallback because the repository account is locked due to a billing issue and no runner starts.

## Verification completed without Android toolchain

- Android XML parses successfully.
- Gradle wrapper JAR is structurally valid.
- Kotlin source delimiter/static smoke checks pass.
- No embedded API-key/client-secret assignments were detected.
- The project has a standalone `settings.gradle.kts`, application module, manifest, package, tests, and wrapper; it has no Python/backend runtime dependency.

## APK status

No APK was produced, so no APK was uploaded and no checksum was fabricated. To finish the build in this sandbox, the allowlist must permit the build-kit hosts, or the Drive build-kit folder must also contain offline archives for Gradle 8.10.2, Android SDK Platform 35/build-tools, and required Google Maven dependencies.

When toolchain access is available, run:

```bash
bash build-android-apk.sh /path/to/voicedock-android
```

Then verify:

```bash
md5sum ~/APK/voicedock-android-debug.apk
```
