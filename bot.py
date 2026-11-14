"""Pro Clubs session scheduler for Discord."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time as _time
from typing import Optional
from zoneinfo import ZoneInfo, available_timezones

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from db import DB
from formations import FORMATIONS, slot_map, slots_for
from render import render_pitch
from timeparse import to_timestamp

load_dotenv()
log = logging.getLogger("proclubs")
logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["DISCORD_TOKEN"]
DB_PATH = os.getenv("DB_PATH", "proclubs.db")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")  # optional: instant command sync to one server
REMIND_MINUTES = int(os.getenv("REMIND_MINUTES", "15"))
CLOSE_AFTER_HOURS = 3
REMIND_LABELS = {
    "channel": "ping in channel",
    "dm": "DM to each player",
    "both": "channel ping + DM",
    "none": "off",
}

db = DB(DB_PATH)
ALL_TZ = sorted(available_timezones())

_avatar_cache: dict[str, bytes] = {}
_http: aiohttp.ClientSession | None = None


async def fetch_avatar(url: str | None) -> bytes | None:
    """Download (and cache) an avatar image; never raises."""
    global _http
    if not url:
        return None
    if url in _avatar_cache:
        return _avatar_cache[url]
    try:
        if _http is None:
            _http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        async with _http.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
        if len(_avatar_cache) > 500:
            _avatar_cache.clear()
        _avatar_cache[url] = data
        return data
    except Exception:
        log.warning("avatar fetch failed for %s", url)
        return None


def avatar_url_for(user: discord.abc.User) -> str:
    return user.display_avatar.replace(size=128, format="png").url


# --------------------------------------------------------------------------
# Message rendering
# --------------------------------------------------------------------------
async def build_message(session) -> tuple[discord.Embed, discord.File]:
    sid = session["id"]
    rsvps = db.rsvps(sid)
    players = [r for r in rsvps if r["status"] == "in"]
    avatars = await asyncio.gather(*(fetch_avatar(r["avatar_url"]) for r in players))
    taken = {r["slot"]: r["name"] for r in players}
    taken_img = {r["slot"]: (r["name"], av) for r, av in zip(players, avatars)}
    subs = [r["name"] for r in rsvps if r["status"] == "sub"]
    outs = [r["name"] for r in rsvps if r["status"] == "out"]

    png = await asyncio.to_thread(render_pitch, session["formation"], taken_img)
    file = discord.File(io.BytesIO(png), filename=f"session{sid}.png")

    status = session["status"]
    color = {"open": 0x2ECC71, "closed": 0x95A5A6, "cancelled": 0xE74C3C}[status]
    title = session["title"]
    if status == "cancelled":
        title = f"❌ CANCELLED — {title}"
    elif status == "closed":
        title = f"🏁 {title}"
    else:
        title = f"⚽ {title}"

    ts = session["start_ts"]
    embed = discord.Embed(title=title, color=color)
    embed.description = (
        f"🗓️ <t:{ts}:F>\n⏳ <t:{ts}:R>\n"
        f"📋 Formation **{session['formation']}** · Host <@{session['creator_id']}>\n"
        f"🔔 Reminder {REMIND_MINUTES} min before: {REMIND_LABELS.get(session['remind_mode'], 'ping in channel')}"
    )
    lineup = []
    for s in slots_for(session["formation"]):
        who = taken.get(s.key)
        lineup.append(f"`{s.label:<3}` {who if who else '—'}")
    half = 6
    embed.add_field(name="Lineup", value="\n".join(lineup[:half]), inline=True)
    embed.add_field(name="​", value="\n".join(lineup[half:]), inline=True)
    embed.add_field(name=f"🪑 Bench / Flex ({len(subs)})", value=", ".join(subs) or "—", inline=False)
    embed.add_field(name=f"🚫 Can't make it ({len(outs)})", value=", ".join(outs) or "—", inline=False)
    embed.set_image(url=f"attachment://{file.filename}")
    embed.set_footer(text=f"Session #{sid} · pick a position below to RSVP")
    return embed, file


async def refresh_message(client: discord.Client, session_id: int, *, interaction: discord.Interaction | None = None):
    session = db.get_session(session_id)
    embed, file = await build_message(session)
    view = SessionView(session_id) if session["status"] == "open" else None
    if interaction is not None:
        await interaction.edit_original_response(embed=embed, attachments=[file], view=view)
        return
    channel = client.get_channel(session["channel_id"]) or await client.fetch_channel(session["channel_id"])
    msg = channel.get_partial_message(session["message_id"])
    await msg.edit(embed=embed, attachments=[file], view=view)


# --------------------------------------------------------------------------
# RSVP UI (persistent: custom_ids carry the session id, so buttons keep
# working after a bot restart)
# --------------------------------------------------------------------------
class PositionSelect(discord.ui.Select):
    def __init__(self, session_id: int):
        session = db.get_session(session_id)
        taken = {r["slot"]: r["name"] for r in db.rsvps(session_id) if r["status"] == "in"}
        options = []
        for s in slots_for(session["formation"]):
            who = taken.get(s.key)
            options.append(
                discord.SelectOption(
                    label=f"{s.label} ({s.key})" if s.key != s.label else s.label,
                    value=s.key,
                    description=f"Taken: {who}"[:100] if who else "Open",
                    emoji="🟡" if who else "🟢",
                )
            )
        super().__init__(
            custom_id=f"pc:{session_id}:pos",
            placeholder="Pick your position…",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.session_id = session_id

    async def callback(self, interaction: discord.Interaction):
        session = db.get_session(self.session_id)
        if not session or session["status"] != "open":
            return await interaction.response.send_message("This session is closed.", ephemeral=True)
        slot = self.values[0]
        holder = db.claim_slot(
            self.session_id, interaction.user.id, interaction.user.display_name, slot,
            avatar_url_for(interaction.user),
        )
        await interaction.response.defer()
        await refresh_message(interaction.client, self.session_id, interaction=interaction)
        if holder:  # refresh also resets the dropdown and updates the "Taken" labels
            await interaction.followup.send(
                f"**{slot}** is already taken by {holder}. Pick another position or join the bench.",
                ephemeral=True,
            )


class SessionView(discord.ui.View):
    def __init__(self, session_id: int):
        super().__init__(timeout=None)
        self.session_id = session_id
        self.add_item(PositionSelect(session_id))
        for label, style, key, emoji in (
            ("Bench / Flex", discord.ButtonStyle.primary, "sub", "🪑"),
            ("Can't make it", discord.ButtonStyle.danger, "out", "🚫"),
            ("Clear my RSVP", discord.ButtonStyle.secondary, "clear", "↩️"),
        ):
            self.add_item(self._button(label, style, key, emoji))

    def _button(self, label, style, key, emoji):
        btn = discord.ui.Button(label=label, style=style, emoji=emoji, custom_id=f"pc:{self.session_id}:{key}")

        async def cb(interaction: discord.Interaction, key=key):
            session = db.get_session(self.session_id)
            if not session or session["status"] != "open":
                return await interaction.response.send_message("This session is closed.", ephemeral=True)
            if key == "clear":
                db.clear_user(self.session_id, interaction.user.id)
            else:
                db.set_status_for_user(self.session_id, interaction.user.id, interaction.user.display_name, key)
            await interaction.response.defer()
            await refresh_message(interaction.client, self.session_id, interaction=interaction)

        btn.callback = cb
        return btn


# --------------------------------------------------------------------------
# Bot + commands
# --------------------------------------------------------------------------
class ProClubsBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # re-register views for sessions that are still open
        for s in db.open_sessions():
            if s["message_id"]:
                self.add_view(SessionView(s["id"]), message_id=s["message_id"])
        if DEV_GUILD_ID:
            # dev mode: commands live in ONE server only, so wipe the global copy
            guild = discord.Object(id=int(DEV_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
        else:
            await self.tree.sync()
        self.housekeeping.start()

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        if not DEV_GUILD_ID and not getattr(self, "_purged", False):
            self._purged = True
            await self._purge_guild_commands()

    async def _purge_guild_commands(self):
        """Remove leftover server-specific commands (from an earlier DEV_GUILD_ID run)
        so they don't show up twice next to the global ones."""
        for g in self.guilds:
            try:
                if await self.tree.fetch_commands(guild=g):
                    self.tree.clear_commands(guild=g)
                    await self.tree.sync(guild=g)
                    log.info("Removed stale server-specific commands from guild %s", g.id)
            except discord.HTTPException:
                log.warning("Could not check commands for guild %s", g.id)

    @tasks.loop(seconds=60)
    async def housekeeping(self):
        now = int(_time.time())
        for s in db.open_sessions():
            try:
                if not s["reminded"] and 0 < s["start_ts"] - now <= REMIND_MINUTES * 60:
                    db.mark_reminded(s["id"])
                    people = [r for r in db.rsvps(s["id"]) if r["status"] in ("in", "sub")]
                    if people and s["remind_mode"] != "none":
                        await self.send_reminders(s, people)
                if now > s["start_ts"] + CLOSE_AFTER_HOURS * 3600:
                    db.set_status(s["id"], "closed")
                    await refresh_message(self, s["id"])
            except (discord.NotFound, discord.Forbidden):
                db.set_status(s["id"], "closed")  # message/channel gone
            except Exception:
                log.exception("housekeeping failed for session %s", s["id"])

    async def send_reminders(self, s, people):
        mode = s["remind_mode"]
        ts = s["start_ts"]
        link = f"https://discord.com/channels/{s['guild_id']}/{s['channel_id']}/{s['message_id']}"
        smap = slot_map(s["formation"])
        failed = []
        if mode in ("dm", "both"):
            for r in people:
                pos = smap[r["slot"]].label if r["status"] == "in" and r["slot"] in smap else "Bench / Flex"
                try:
                    dm = await self.create_dm(discord.Object(id=r["user_id"]))
                    await dm.send(f"⏰ **{s['title']}** kicks off <t:{ts}:R>!\nYour spot: **{pos}**\n{link}")
                except (discord.Forbidden, discord.HTTPException):
                    failed.append(r)  # DMs closed or user unreachable
        # who gets an @ping in the channel: everyone for channel/both, only failed DMs for dm mode
        pinged = people if mode in ("channel", "both") else failed
        if pinged:
            mentions = " ".join(f"<@{r['user_id']}>" for r in pinged)
            note = "" if mode in ("channel", "both") else " (couldn't DM you)"
            channel = self.get_channel(s["channel_id"]) or await self.fetch_channel(s["channel_id"])
            await channel.send(
                f"⏰ **{s['title']}** kicks off <t:{ts}:R>! {mentions}{note}",
                reference=channel.get_partial_message(s["message_id"]),
                allowed_mentions=discord.AllowedMentions(users=True),
            )

    @housekeeping.before_loop
    async def _wait(self):
        await self.wait_until_ready()


bot = ProClubsBot()
session_group = app_commands.Group(name="game", description="Pro Clubs sessions", guild_only=True)


async def tz_autocomplete(interaction: discord.Interaction, current: str):
    cur = current.lower().replace(" ", "_")
    matches = [z for z in ALL_TZ if cur in z.lower()][:25]
    return [app_commands.Choice(name=z, value=z) for z in matches]


async def session_autocomplete(interaction: discord.Interaction, current: str):
    out = []
    for s in db.open_sessions(interaction.guild_id):
        label = f"#{s['id']} {s['title']}"
        if current.lower() in label.lower():
            out.append(app_commands.Choice(name=label[:100], value=s["id"]))
    return out[:25]


@session_group.command(name="create", description="Schedule a Pro Clubs session")
@app_commands.describe(
    formation="Starting formation",
    date="YYYY-MM-DD, DD/MM, today, tomorrow, or a weekday (fri)",
    time="e.g. 20:30, 8pm, 8:30pm",
    title="Optional title (default: Pro Clubs Session)",
    timezone="Override your saved timezone (e.g. Europe/London)",
    reminder="How to remind players before kickoff (default: ping in channel)",
)
@app_commands.choices(
    formation=[app_commands.Choice(name=f, value=f) for f in FORMATIONS],
    reminder=[
        app_commands.Choice(name="Ping players in the channel", value="channel"),
        app_commands.Choice(name="DM each player", value="dm"),
        app_commands.Choice(name="Both channel ping and DM", value="both"),
        app_commands.Choice(name="No reminder", value="none"),
    ],
)
@app_commands.autocomplete(timezone=tz_autocomplete)
async def create(
    interaction: discord.Interaction,
    formation: app_commands.Choice[str],
    date: str,
    time: str,
    title: str = "Pro Clubs Session",
    timezone: Optional[str] = None,
    reminder: Optional[app_commands.Choice[str]] = None,
):
    tz = timezone or db.get_tz(interaction.user.id) or "UTC"
    try:
        ZoneInfo(tz)
        ts = to_timestamp(date, time, tz)
    except Exception as e:
        return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
    if ts < int(_time.time()):
        return await interaction.response.send_message("❌ That time is in the past.", ephemeral=True)

    await interaction.response.defer()
    sid = db.create_session(
        interaction.guild_id, interaction.channel_id, interaction.user.id, title[:100], formation.value, ts,
        reminder.value if reminder else "channel",
    )
    session = db.get_session(sid)
    embed, file = await build_message(session)
    msg = await interaction.followup.send(embed=embed, file=file, view=SessionView(sid), wait=True)
    db.set_message(sid, msg.id)
    if not (timezone or db.get_tz(interaction.user.id)):
        await interaction.followup.send(
            "ℹ️ I used **UTC** because you haven't set a timezone. Run `/timezone` to save yours.",
            ephemeral=True,
        )


def _can_manage(interaction: discord.Interaction, session) -> bool:
    perms = interaction.permissions
    return interaction.user.id == session["creator_id"] or perms.manage_guild


@session_group.command(name="cancel", description="Cancel a session (host or server managers)")
@app_commands.autocomplete(session_id=session_autocomplete)
async def cancel(interaction: discord.Interaction, session_id: int):
    session = db.get_session(session_id)
    if not session or session["guild_id"] != interaction.guild_id:
        return await interaction.response.send_message("Session not found.", ephemeral=True)
    if not _can_manage(interaction, session):
        return await interaction.response.send_message("Only the host can cancel this.", ephemeral=True)
    db.set_status(session_id, "cancelled")
    await interaction.response.defer(ephemeral=True)
    await refresh_message(interaction.client, session_id)
    await interaction.followup.send("Session cancelled.", ephemeral=True)


@session_group.command(name="kick", description="Remove a player from a position (host or managers)")
@app_commands.autocomplete(session_id=session_autocomplete)
async def kick(interaction: discord.Interaction, session_id: int, player: discord.Member):
    session = db.get_session(session_id)
    if not session or session["guild_id"] != interaction.guild_id:
        return await interaction.response.send_message("Session not found.", ephemeral=True)
    if not _can_manage(interaction, session):
        return await interaction.response.send_message("Only the host can do that.", ephemeral=True)
    db.clear_user(session_id, player.id)
    await interaction.response.defer(ephemeral=True)
    await refresh_message(interaction.client, session_id)
    await interaction.followup.send(f"Removed {player.display_name}.", ephemeral=True)


@session_group.command(name="list", description="Upcoming sessions in this server")
async def list_sessions(interaction: discord.Interaction):
    rows = db.open_sessions(interaction.guild_id)
    if not rows:
        return await interaction.response.send_message("No upcoming sessions.", ephemeral=True)
    lines = []
    for s in rows[:15]:
        filled = sum(1 for r in db.rsvps(s["id"]) if r["status"] == "in")
        link = f"https://discord.com/channels/{s['guild_id']}/{s['channel_id']}/{s['message_id']}"
        lines.append(f"**#{s['id']}** [{s['title']}]({link}) · {s['formation']} · <t:{s['start_ts']}:f> · {filled}/11")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="timezone", description="Save your timezone for scheduling")
@app_commands.describe(timezone="e.g. Asia/Kolkata, Europe/London, America/New_York")
@app_commands.autocomplete(timezone=tz_autocomplete)
async def timezone_cmd(interaction: discord.Interaction, timezone: str):
    if timezone not in ALL_TZ:
        return await interaction.response.send_message("Unknown timezone — pick one from the suggestions.", ephemeral=True)
    db.set_tz(interaction.user.id, timezone)
    await interaction.response.send_message(f"Timezone saved: **{timezone}**", ephemeral=True)


bot.tree.add_command(session_group)

if __name__ == "__main__":
    bot.run(TOKEN)
