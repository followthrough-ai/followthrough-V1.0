# Followthrough browser extension

The extension is the main Followthrough product: sign up once, choose which apps it may use, and a few minutes after each Granola meeting ends your commitments are completed automatically. It talks to the **Followthrough engine** running on your computer (`python run.py engine`), which does the actual work with the tested pipeline.

## Install (Chrome or Edge)

1. **Start the engine** in the Followthrough folder:
   ```powershell
   python run.py engine
   ```
   To start it automatically when you sign in to Windows:
   ```powershell
   .\engine\install-windows.ps1          # remove with -Uninstall
   ```
2. **Load the extension**
   - Chrome: `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → choose the `extension` folder.
   - Edge: `edge://extensions` → **Developer mode** → **Load unpacked** → choose the `extension` folder.
   - Or unzip `dist/followthrough-extension.zip` (created by `python run.py package-extension`) and load that folder.
3. **Pin it** (puzzle-piece icon → pin) and click the Followthrough icon.

## First run

| Step | What happens |
|---|---|
| **Welcome** | Enter the email your Granola account uses. Autopilot only acts on meetings you own. |
| **Which apps may it use?** | Tick Gmail, Google Calendar, Slack, Airtable. Actions in unticked apps are never sent; they're listed for you instead. |
| **Turn on autopilot** | Leave **Act for real** on and confirm. Turn it off to run in preview mode (you see what it would do, nothing is sent). |

That's it. The engine checks Granola every 2 minutes. When a meeting's AI summary is ready, it extracts the commitments, matches people and records, completes the allowed actions and shows a notification with the result.

## Popup

- **Status card** — autopilot on / paused / preview, allowed apps, last check. Toggle to pause. **Check now** polls immediately. **Open dashboard** opens the website.
- **Recent meetings** — one entry per meeting: ✅ done · ⏭ already done · ❌ failed (with reason) · 📝 previewed · 🚫 skipped (app not allowed) · ❓ needs you.
- **Badge** shows the number of items that need your input; **off** means the engine isn't running.
- **Settings (⚙)** — email, allowed apps, act for real, only my meetings, check interval, engine address.

## Safety

- Nothing is sent until you turn on **Act for real** (with a confirmation). The engine can also be armed by `FOLLOWTHROUGH_MODE=real` in `.env`.
- Ambiguous names or records become questions, never guesses.
- The same meeting is never processed twice, and the same action is never repeated.
- The engine listens only on your computer (`127.0.0.1`) and accepts cross-origin requests only from browser extensions.

## Permissions

| Permission | Why |
|---|---|
| `storage` | Remember the engine address and the last notification |
| `alarms` | Check the engine once a minute in the background |
| `notifications` | Tell you when a meeting's tasks are done |
| `http://127.0.0.1/*`, `http://localhost/*` | Talk to the local engine |

No data is sent anywhere by the extension itself; the engine talks only to the services you configured.
