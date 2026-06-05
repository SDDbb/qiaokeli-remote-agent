# NexusDeck Android

NexusDeck is the mobile control console for the `remote-agent` desktop service.
It connects to the Fedora host through the NexusDeck HTTP API over Tailscale.

中文手机端使用说明见 [USAGE.md](USAGE.md)。

## Quick Start

1. On the Fedora host, print pairing info:

   ```bash
   python3 scripts/remote_agent_api.py --pairing-json
   ```

2. Start the API service:

   ```bash
   systemctl --user enable --now qiaokeli-nexusdeck-api.service
   ```

3. Open this `nexusdeck-android/` directory in Android Studio.

4. In the app Settings tab, enter the API base URL and bearer token.

The first version exposes Deck, Agent, Phone, Files, and Settings tabs. Phone
automation goes through the desktop's authorized ADB connection; the app does
not request Android Accessibility permissions in this phase.
