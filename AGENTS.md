# Instructions for AI agents

- Bots run as macOS launchd agents, not from a terminal: see "Running a Bot as a Background Service" in [README.md](README.md). Never start `run.py` yourself while the service is running; a second copy breaks Telegram polling.
- After changing code or a bot's config, restart the bot with `launchctl kickstart -k gui/$(id -u)/<label>`, then check its log in `~/Library/Logs/` to confirm it reconnected.
- On the owner's Mac Studio, Bub (`bots/harville_bot`) has the label `me.harville.bub` and logs to `~/Library/Logs/bub.log`.
- `bots/*/config.json` holds API keys and tokens and is gitignored. Never print or commit it.
