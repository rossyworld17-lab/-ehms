# EHMS Staff — Android app and Google Play (release 1.4)

The Android app is a **Trusted Web Activity** (TWA): a small, signed Android package that opens the hotel's own
EHMS staff system (`https://<domain>/staff`) full-screen in Chrome's engine, with the hotel's icon and name, no
browser bar, and Android's verified-link security. Every screen, permission check and update comes from the
server, so the app never goes out of date and holds no hotel data on the phone. This is the approach Google
recommends for publishing web apps on Play, and it passes the Play Store's quality checks when the site is a PWA
(EHMS 1.4 is: web manifest, service worker, offline page, maskable icons).

Where Chrome is not installed, the app falls back to Android's WebView automatically.

```
android/                         Gradle project (Android Gradle Plugin 8.9, target SDK 36, minimum Android 7.0)
  gradle.properties              ehms.host / appName / applicationId / versionCode / versionName
  app/src/main/res/              icons (adaptive), splash, colours
  store/                         512×512 Play icon and 1024×500 feature graphic
.github/workflows/android.yml    builds the signed .aab (for Play) and a test .apk on GitHub
```

## 1. One-time: create the upload key
On any computer with Java 17 (or Android Studio) installed:
```bash
keytool -genkeypair -v -keystore ehms-upload.jks -alias ehms -keyalg RSA -keysize 4096 -validity 10000
```
Choose strong passwords and **keep the `.jks` file and passwords safe** (password manager plus an offline copy).
Never commit the key (the repository's `.gitignore` blocks `*.jks`).

## 2. One-time: give the key to GitHub
In the repository on GitHub: **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | the key file in base64: `base64 -w0 ehms-upload.jks` (macOS: `base64 -i ehms-upload.jks`; Windows PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("ehms-upload.jks"))`) |
| `ANDROID_KEYSTORE_PASSWORD` | the keystore password |
| `ANDROID_KEY_ALIAS` | `ehms` (or the alias you chose) |
| `ANDROID_KEY_PASSWORD` | the key password |

Without these secrets the workflow still builds, but the bundle is not signed for Play.

## 3. Build the app
GitHub → **Actions → Android app → Run workflow**, and fill in:
- **host**: the hotel's live domain without `https://`, e.g. `crestviewhotel.com`
- **app_name**: the name under the icon, e.g. `Crestview Staff`
- **application_id**: a unique, permanent ID, e.g. `com.crestviewhotel.staff` (it can never change once published)
- **version_code**: 1 for the first upload, then +1 for every new upload
- **version_name**: shown to users, e.g. `1.4.0`

After about 5 minutes, download the artifact `ehms-staff-<version>-<code>`. It contains:
- `app-release.aab` — upload this to Google Play
- `app-debug.apk` — install directly on a test phone (allow "install unknown apps")
- `fingerprint.txt` — the SHA-256 fingerprint of your upload key (also shown on the run's summary page)

To build on your own computer instead: `cd android && ./gradlew bundleRelease -Pehms.host=crestviewhotel.com ...`
with `EHMS_KEYSTORE_FILE`, `EHMS_KEYSTORE_PASSWORD`, `EHMS_KEY_ALIAS`, `EHMS_KEY_PASSWORD` set.

## 4. Link the app to the website (Digital Asset Links)
Android only opens the app full-screen (without a browser bar) if the website confirms it owns the app. EHMS
publishes `https://<domain>/.well-known/assetlinks.json` automatically from two settings in the server's `.env`:
```
EHMS_ANDROID_PACKAGE=com.crestviewhotel.staff
EHMS_ANDROID_SHA256=<upload key fingerprint>,<Play App Signing fingerprint>
```
- The upload key fingerprint is in `fingerprint.txt`.
- The **Play App Signing** fingerprint appears in Play Console after the first upload: **Test and release → Setup →
  App signing → App signing key certificate → SHA-256**. Add it, comma-separated, because Play re-signs the app
  with its own key.

Then run `docker compose up -d` and open `https://<domain>/.well-known/assetlinks.json` to check.

## 5. Publish on Google Play
1. Create a Google Play developer account (play.google.com/console, one-time US$25). Organisation accounts need a
   D-U-N-S number; personal accounts created after November 2023 must run a closed test with at least 12 testers for
   14 days before production access.
2. **Create app** → app name, default language, App, Free.
3. **Store listing**: short and full description, the 512×512 icon (`android/store/play-icon-512.png`), the feature
   graphic (`android/store/feature-graphic-1024x500.png`) and at least two phone screenshots (sign in on the test APK
   and take screenshots of the dashboard, front desk and housekeeping screens).
4. **App content**:
   - Privacy policy URL: `https://<domain>/privacy` (edit the text in **Administration → Website → Privacy notice**).
   - App access: the app requires a login. Give reviewers a test account with a limited role (e.g. Front Desk,
     without two-step verification) on your live or staging server, and say it is for hotel staff.
   - Ads: no ads. Content rating: complete the questionnaire (business/productivity app, no user-generated public
     content). Target audience: 18+. News app: no. Government app: no.
   - **Data safety** (suggested answers — check them against your own use):
     - Data collected: name, email address, phone number (account management); app activity (actions recorded in
       the audit trail, for security and compliance). Optionally photos/files if staff upload documents.
     - Data is encrypted in transit: yes. Users can request deletion: yes (through the hotel's administrator).
     - Data shared with third parties: no (the hotel's own server).
5. **Test and release → Internal testing** → create a release → upload `app-release.aab` → add testers' emails →
   roll out. Testers install from the Play link. Then promote to **Closed**, and later **Production**.
6. Play reviews the first release (usually 1–7 days).

## 6. Updating the app
Because the app shows the live system, **most updates need no new app release**: update the server (`deploy/update.sh`)
and every phone has the new version the next time the app opens. Release a new `.aab` (with version_code + 1) only to
change the name, icon, domain or Android target level. Google requires the target SDK to be raised every year (the
build uses 36).

## 7. iPhone and other devices
Staff on iPhone, tablets or computers use the same system in the browser at `https://<domain>/staff`; in Safari,
**Share → Add to Home Screen** installs it like an app (the installable web app, PWA).

## Troubleshooting
| Symptom | Fix |
|---|---|
| A browser bar shows at the top of the app | assetlinks.json is missing or wrong: check `EHMS_ANDROID_PACKAGE`, both SHA-256 fingerprints, and that `https://<domain>/.well-known/assetlinks.json` loads. Android caches the check; reinstall the app after fixing. |
| "This site can't be reached" | the host in the workflow input is wrong, or the server or its certificate is down (`/api/health`). |
| Play rejects the bundle as unsigned | add the four `ANDROID_*` secrets and run the workflow again. |
| "Version code already used" | increase version_code. |
