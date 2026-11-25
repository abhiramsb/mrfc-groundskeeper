# MRFC_GroundsKeeper (pro-clubs-bot)

Discord bot that schedules MRFC Academy EA FC Pro Clubs sessions. A Captain creates a session with a
formation and time, players RSVP for positions from a dropdown, and the bot renders a pitch image with
their avatars and sends reminders before kickoff.

## Commands
`/game create`, `/game edit`, `/game cancel`, `/game kick`, `/game list`, `/timezone`, `/club` (shows new joinees how to find and join the club in game; only visible to the person who runs it).

## Environment variables
| Variable | Meaning |
|---|---|
| `DISCORD_TOKEN` | bot token (required) |
| `CAPTAIN_ROLE_ID` | optional: ID of the **MRFC Captain** role. When set, only this role (and server managers) can create, edit, cancel and kick |
| `SESSIONS_CHANNEL_ID` | optional: ID of `#mrfc-sessions`. When set, `/game create` only works there |
| `CLUB_NAME` | optional: in-game club name shown by `/club`, default `MRFC Academy` |
| `CLUB_EXTRA` | optional: extra note shown at the bottom of `/club` (e.g. platform) |
| `REMIND_MINUTES` | minutes before kickoff to remind, default 15 |
| `DB_PATH` | default `proclubs.db` |
| `DEV_GUILD_ID` | optional: instant command sync to one server while testing |

Bot permissions needed in `#mrfc-sessions`: View Channel, Send Messages, Embed Links, Attach Files,
Read Message History.
