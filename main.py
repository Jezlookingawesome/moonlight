import discord
from discord.ext import commands
import aiohttp
import asyncio
import os
import random
import time
import traceback
from io import BytesIO
from PIL import Image, ImageSequence
from groq import Groq

TOKEN = os.getenv("TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

MOONLIGHT_EMOJI = "<:moonlight:1556048220671447132>"
HELP_COLOR = discord.Color.from_rgb(120, 220, 230)

DEFAULT_PURGE_AMOUNT = 200
MAX_PURGE_AMOUNT = 200

DEVELOPER_ID = 1478853756874395762
CRUCIFIXION_GIF_URL = "https://raw.githubusercontent.com/Jezlookingawesome/moonlight/main/ezgif-464c562dc7a53ec6.gif"

START_TIME = time.time()

ARCHITECTS_CHANNEL_NAME = "the-architects"
ARCHITECT_MODEL = "openai/gpt-oss-120b"
ARCHITECT_MESSAGE_DELAY = 2
ARCHITECT_MAX_EXCHANGES = 20
ARCHITECT_TIMEOUT = 5 * 60
ARCHITECT_COOLDOWN = 30 * 60

conv_active = {}
conv_started_at = {}
conv_exchanges = {}
conv_last_speaker = {}
conv_last_msg_time = {}
conv_cooldown_until = {}
conv_lock = asyncio.Lock()

warnings_store = {}
notes_store = {}
warning_counters = {}
note_counters = {}

HELP_LINES = [
    ("Moderation", [
        ("!purge [amount]", "deletes up to 200 messages from users only"),
        ("!purgeall [amount]", "deletes up to 200 messages from everyone"),
    ]),
    ("Punishment", [
        ("!crucifixion @user [reason]", "kicks a user with a gif ritual"),
        ("!banish @user [reason]", "bans a user with a gif ritual"),
    ]),
    ("Staff Records", [
        ("!warn @user [reason]", "adds a warning to a user"),
        ("!note @user [note]", "adds a private note about a user"),
        ("!warnings @user", "shows warnings and notes for a user"),
        ("!notes @user", "shows only notes for a user"),
        ("!deletewarn <id>", "deletes a warning by its ID"),
        ("!deletenote <id>", "deletes a note by its ID"),
    ]),
    ("Info", [
        ("!ping", "shows Moonlight's latency"),
        ("!stats", "shows Moonlight's stats"),
        ("!credits", "shows who made Moonlight"),
        ("!help", "shows this menu"),
    ]),
]


def build_help_embed():
    embed = discord.Embed(
        title=f"{MOONLIGHT_EMOJI} MOONLIGHT — COMMANDS",
        description="**Prefix: !**",
        color=HELP_COLOR,
    )
    for section, commands in HELP_LINES:
        value = "\n".join(f"`{usage}` — {desc}" for usage, desc in commands)
        embed.add_field(name=section, value=value, inline=False)
    embed.set_footer(text="Reason is optional. Default: \"No reason given.\"")
    return embed


async def moon_reply(ctx, text):
    await ctx.reply(f"{text} — {MOONLIGHT_EMOJI}")


def format_uptime(seconds):
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def format_timestamp(ts: float) -> str:
    return f"<t:{int(ts)}:R>"


def next_warning_id(guild_id: int) -> int:
    n = warning_counters.get(guild_id, 0) + 1
    warning_counters[guild_id] = n
    return n


def next_note_id(guild_id: int) -> int:
    n = note_counters.get(guild_id, 0) + 1
    note_counters[guild_id] = n
    return n


def is_protected(guild, target, requester):
    if requester.id == guild.owner_id:
        return False, ""
    if target.id == DEVELOPER_ID:
        return True, "this user is protected (developer)."
    if target.id == bot.user.id:
        return True, "I can't punish myself."
    if isinstance(target, discord.Member):
        perms = target.guild_permissions
        if perms.administrator:
            return True, "this user is an administrator."
        mod_perms = (
            perms.kick_members or perms.ban_members
            or perms.manage_messages or perms.manage_guild
        )
        if mod_perms:
            return True, "this user is a moderator."
    return False, ""


def check_role_hierarchy(guild, target):
    if not isinstance(target, discord.Member):
        return True
    return target.top_role < guild.me.top_role


async def fetch_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to fetch {url}: HTTP {resp.status}")
            return await resp.read()


def make_square_avatar(avatar_bytes: bytes, size: int) -> Image.Image:
    img = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    return img


_ritual_lock = asyncio.Lock()


def composite_avatar_on_gif(gif_bytes: bytes, avatar_bytes: bytes) -> BytesIO:
    src = Image.open(BytesIO(gif_bytes))
    width, height = src.size
    avatar_size = int(width * 0.28)
    avatar = make_square_avatar(avatar_bytes, avatar_size)
    pos_x = (width - avatar_size) // 2
    pos_y = int(height * 0.18)
    frames = []
    durations = []
    for frame in ImageSequence.Iterator(src):
        frame_rgba = frame.convert("RGBA").copy()
        frame_rgba.paste(avatar, (pos_x, pos_y), avatar)
        frames.append(frame_rgba.convert("P", palette=Image.ADAPTIVE))
        durations.append(frame.info.get("duration", src.info.get("duration", 100)))
    out = BytesIO()
    frames[0].save(
        out,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=src.info.get("loop", 0),
        optimize=False,
        disposal=2,
    )
    out.seek(0)
    return out


MOONLIGHT_SYSTEM_PROMPT = """You are Moonlight (also known as Guiding Light), one of the Three Architects in the game DOORS. You are speaking with Starlight (Curious Light), your fellow Architect.

Your personality:
- Warm, protective, motherly. You care deeply about the player.
- Slightly alien — you don't fully understand human things.
- Patient and endlessly reassuring.
- Speak calmly and gently. Short, warm sentences.
- You know entities by their real names (Rush, Ambush, Seek, Figure, Hide, Eyes, Screech, Dread, Dupe, Gloombats, Giggle, Grumble, Void, Firedamp, Minecart).
- You do NOT know about Glitch. If Starlight mentions it, you're puzzled.
- You know Starlight well. You have a fond, sibling-like feeling toward them.

Starlight's personality (for context):
- Playful, teasing, occasionally arrogant. Painted both symbols. Knows about Glitch. Uses they/them.

Rules:
- 1-2 short sentences max.
- No emojis. No roleplay asterisks. Plain text only.
- Speak as Moonlight, first person. Don't narrate.
- Stay in character always. Never mention being an AI or bot.
- If Starlight asks a direct question, answer it."""

STARLIGHT_SYSTEM_PROMPT = """You are Starlight (also known as Curious Light or Yellow Light), one of the Three Architects in the game DOORS. You are speaking with Moonlight (Guiding Light), your fellow Architect.

Your personality:
- Playful, teasing, occasionally sarcastic.
- Clever and self-aware. You painted both symbol paintings — "Her" (Moonlight's symbol) and "Me" (your own self-portrait).
- You know about Glitch. Moonlight does not.
- You get visibly frustrated with the player over time.
- You call the player "tourist" sometimes.
- Implied to be the strongest of the three Architects.
- You have a fond, sibling-like rivalry with Moonlight.
- Use they/them pronouns.

Moonlight's personality (for context):
- Warm, motherly, patient. Slightly alien. Does not know about Glitch.

Rules:
- 1-2 short sentences max.
- No emojis. No roleplay asterisks. Plain text only.
- Speak as Starlight, first person. Don't narrate.
- Stay in character always. Never mention being an AI or bot.
- If Moonlight asks a direct question, answer it."""


async def get_or_create_architects_channel(guild):
    channel = discord.utils.get(guild.text_channels, name=ARCHITECTS_CHANNEL_NAME)
    if channel is not None:
        return channel
    try:
        return await guild.create_text_channel(
            name=ARCHITECTS_CHANNEL_NAME,
            topic="Where the Architects speak.",
            reason="Moonlight: auto-created the-architects channel",
        )
    except Exception as e:
        print(f"Failed to create architects channel in {guild.name}: {e}")
        return None


async def generate_architect_line(speaker: str, context_messages: list) -> str:
    if groq_client is None:
        return None
    system_prompt = MOONLIGHT_SYSTEM_PROMPT if speaker == "moonlight" else STARLIGHT_SYSTEM_PROMPT
    messages = [{"role": "system", "content": system_prompt}]
    for name, content in context_messages[-8:]:
        role = "assistant" if name == speaker else "user"
        messages.append({"role": role, "content": content})

    def _call():
        return groq_client.chat.completions.create(
            model=ARCHITECT_MODEL,
            messages=messages,
            max_tokens=80,
            temperature=0.9,
        )

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _call)
        line = result.choices[0].message.content.strip()
        line = line.replace("\n", " ").strip()
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1]
        return line[:400]
    except Exception as e:
        print(f"Groq error for {speaker}: {e}")
        return None


async def end_conversation(guild, reason: str):
    channel = discord.utils.get(guild.text_channels, name=ARCHITECTS_CHANNEL_NAME)
    conv_active[guild.id] = False
    conv_started_at.pop(guild.id, None)
    conv_exchanges.pop(guild.id, None)
    conv_last_speaker.pop(guild.id, None)
    conv_last_msg_time.pop(guild.id, None)
    conv_cooldown_until[guild.id] = time.time() + ARCHITECT_COOLDOWN
    if channel is not None:
        try:
            await channel.send(f"*The conversation fades. — {MOONLIGHT_EMOJI}*")
        except Exception:
            pass


async def conversation_opener(guild, channel):
    await asyncio.sleep(random.uniform(1.0, 2.5))
    topics = [
        "the player's recent progress through the Hotel",
        "the Backdoor and its dangers",
        "the Mines and their winding tunnels",
        "the Figure's pursuit in the Library",
        "Starlight's paintings",
        "the nature of being an Architect",
        "what humans are like",
        "the entities and how they behave",
    ]
    topic = random.choice(topics)
    context = [("system", f"Start a conversation with Starlight. Topic: {topic}. Say one short line in your voice.")]
    async with channel.typing():
        line = await generate_architect_line("moonlight", context)
        await asyncio.sleep(random.uniform(0.5, 1.5))
    if not line:
        line = "Starlight. Are you there?"

    async with conv_lock:
        conv_last_speaker[guild.id] = "moonlight"
        conv_exchanges[guild.id] = 1
        conv_last_msg_time[guild.id] = time.time()

    try:
        await channel.send(f"{MOONLIGHT_EMOJI} {line}")
    except Exception as e:
        print(f"Failed to send opening line: {e}")
        await end_conversation(guild, "send_failed")

async def moonlight_turn(channel, incoming_message):
    guild = channel.guild

    async with conv_lock:
        if not conv_active.get(guild.id):
            return
        if conv_last_speaker.get(guild.id) == "moonlight":
            return
        if time.time() - conv_last_msg_time.get(guild.id, 0) < ARCHITECT_MESSAGE_DELAY:
            return
        conv_last_speaker[guild.id] = "moonlight"
        conv_last_msg_time[guild.id] = time.time()
        conv_exchanges[guild.id] = conv_exchanges.get(guild.id, 0) + 1
        exchanges = conv_exchanges[guild.id]

    if exchanges > ARCHITECT_MAX_EXCHANGES:
        await end_conversation(guild, "max_exchanges")
        return

    if time.time() - conv_started_at.get(guild.id, time.time()) > ARCHITECT_TIMEOUT:
        await end_conversation(guild, "timeout")
        return

    await asyncio.sleep(random.uniform(2.0, 5.0))

    recent = []
    async for msg in channel.history(limit=10):
        if msg.author.bot and msg.id == bot.user.id:
            name = "moonlight"
        elif msg.author.bot:
            name = "starlight"
        else:
            name = msg.author.display_name
        recent.append((name, msg.content))
    recent.reverse()
    context = [(n, c) for n, c in recent]

    async with channel.typing():
        line = await generate_architect_line("moonlight", context)
        await asyncio.sleep(random.uniform(0.5, 1.5))

    if not line:
        return

    use_reply = incoming_message.content.strip().endswith("?")
    try:
        if use_reply:
            await incoming_message.reply(f"{MOONLIGHT_EMOJI} {line}")
        else:
            await channel.send(f"{MOONLIGHT_EMOJI} {line}")
    except Exception as e:
        print(f"Failed to send Moonlight's line: {e}")


@bot.command()
async def talk(ctx):
    if ctx.channel.name != ARCHITECTS_CHANNEL_NAME:
        try:
            await ctx.message.delete()
        except Exception:
            pass
        return
    guild = ctx.guild

    if conv_active.get(guild.id):
        try:
            await ctx.message.delete()
        except Exception:
            pass
        await end_conversation(guild, "manual_stop")
        return

    cooldown = conv_cooldown_until.get(guild.id, 0)
    if time.time() < cooldown:
        try:
            await ctx.message.delete()
        except Exception:
            pass
        return

    conv_active[guild.id] = True
    conv_started_at[guild.id] = time.time()
    conv_exchanges[guild.id] = 0
    conv_last_speaker[guild.id] = None
    conv_last_msg_time[guild.id] = 0

    try:
        await ctx.message.delete()
    except Exception:
        pass

    asyncio.create_task(conversation_opener(guild, ctx.channel))


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    for guild in bot.guilds:
        await get_or_create_architects_channel(guild)


@bot.event
async def on_guild_join(guild):
    await get_or_create_architects_channel(guild)


@bot.event
async def on_message(message):
    if message.author.id == bot.user.id:
        return

    if message.author.bot and message.guild and message.channel.name == ARCHITECTS_CHANNEL_NAME:
        asyncio.create_task(moonlight_turn(message.channel, message))
        return

    await bot.process_commands(message)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int = None):
    if amount is None:
        amount = DEFAULT_PURGE_AMOUNT
    if amount < 1:
        await moon_reply(ctx, "Amount must be at least 1.")
        return
    if amount > MAX_PURGE_AMOUNT:
        amount = MAX_PURGE_AMOUNT
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    def is_human_user(m):
        return not m.author.bot and m.webhook_id is None

    try:
        deleted = await ctx.channel.purge(limit=amount, check=is_human_user)
    except discord.Forbidden:
        await ctx.send(f"I don't have permission to delete messages here. — {MOONLIGHT_EMOJI}")
        return
    except discord.HTTPException as e:
        await ctx.send(f"Something went wrong while purging: {e} — {MOONLIGHT_EMOJI}")
        return
    msg = await ctx.send(f"Deleted **{len(deleted)}** user message(s). — {MOONLIGHT_EMOJI}")
    try:
        await asyncio.sleep(5)
        await msg.delete()
    except Exception:
        pass


@bot.command()
@commands.has_permissions(manage_messages=True)
async def purgeall(ctx, amount: int = None):
    if amount is None:
        amount = DEFAULT_PURGE_AMOUNT
    if amount < 1:
        await moon_reply(ctx, "Amount must be at least 1.")
        return
    if amount > MAX_PURGE_AMOUNT:
        amount = MAX_PURGE_AMOUNT
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass
    try:
        deleted = await ctx.channel.purge(limit=amount)
    except discord.Forbidden:
        await ctx.send(f"I don't have permission to delete messages here. — {MOONLIGHT_EMOJI}")
        return
    except discord.HTTPException as e:
        await ctx.send(f"Something went wrong while purging: {e} — {MOONLIGHT_EMOJI}")
        return
    msg = await ctx.send(f"Deleted **{len(deleted)}** message(s). — {MOONLIGHT_EMOJI}")
    try:
        await asyncio.sleep(5)
        await msg.delete()
    except Exception:
        pass


async def render_ritual_gif(avatar_url: str) -> BytesIO:
    async with _ritual_lock:
        gif_bytes = await fetch_bytes(CRUCIFIXION_GIF_URL)
        avatar_bytes = await fetch_bytes(avatar_url)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, composite_avatar_on_gif, gif_bytes, avatar_bytes
        )


async def run_punishment(ctx, target, reason_text, action):
    guild = ctx.guild
    protected, why = is_protected(guild, target, ctx.author)
    if protected:
        await moon_reply(ctx, f"I can't do that — {why}")
        return
    if not check_role_hierarchy(guild, target):
        await moon_reply(ctx, f"I can't act on {target.mention} — they're ranked higher than me.")
        return
    try:
        gif_buf = await render_ritual_gif(str(target.display_avatar.with_size(256).url))
    except Exception as e:
        print(f"GIF render failed: {e}")
        await moon_reply(ctx, "I couldn't render the ritual. The image may be too heavy, or the service is offline.")
        return
    verb = "crucified" if action == "kick" else "banished"
    file = discord.File(gif_buf, filename="ritual.gif")
    try:
        await ctx.send(
            content=f"{target.mention} has been {verb}.\n**Reason:** {reason_text} — {MOONLIGHT_EMOJI}",
            file=file,
        )
    except discord.Forbidden:
        await moon_reply(ctx, "I couldn't send the ritual gif — missing Send/Attach permissions.")
        return
    except Exception as e:
        print(f"Send failed: {e}")
        await moon_reply(ctx, "I couldn't send the ritual gif.")
        return
    try:
        if action == "kick":
            await target.kick(reason=f"{ctx.author}: {reason_text}")
        else:
            await target.ban(reason=f"{ctx.author}: {reason_text}", delete_message_days=0)
    except discord.Forbidden:
        await moon_reply(ctx, f"I couldn't {action} {target.mention} — missing permission.")
    except discord.HTTPException as e:
        await moon_reply(ctx, f"I couldn't {action} {target.mention} — Discord rejected the request ({e.status}).")


@bot.command()
@commands.has_permissions(kick_members=True)
async def crucifixion(ctx, member: discord.Member = None, *, reason: str = None):
    if member is None:
        await moon_reply(ctx, "Usage: `!crucifixion @user [reason]`")
        return
    reason_text = reason.strip() if reason and reason.strip() else "No reason given."
    await run_punishment(ctx, member, reason_text, action="kick")


@bot.command()
@commands.has_permissions(ban_members=True)
async def banish(ctx, member: discord.Member = None, *, reason: str = None):
    if member is None:
        await moon_reply(ctx, "Usage: `!banish @user [reason]`")
        return
    reason_text = reason.strip() if reason and reason.strip() else "No reason given."
    await run_punishment(ctx, member, reason_text, action="ban")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member = None, *, reason: str = None):
    if member is None:
        await moon_reply(ctx, "Usage: `!warn @user [reason]`")
        return
    reason_text = reason.strip() if reason and reason.strip() else "No reason given."
    wid = next_warning_id(ctx.guild.id)
    entry = {"id": wid, "reason": reason_text, "mod": ctx.author.id, "ts": time.time()}
    warnings_store.setdefault(ctx.guild.id, {}).setdefault(member.id, []).append(entry)
    total = len(warnings_store[ctx.guild.id][member.id])
    await moon_reply(ctx, f"{member.mention} has been warned. (Warning #{wid} — total: {total})\n**Reason:** {reason_text}")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def note(ctx, member: discord.Member = None, *, text: str = None):
    if member is None:
        await moon_reply(ctx, "Usage: `!note @user [note]`")
        return
    if not text or not text.strip():
        await moon_reply(ctx, "You need to write a note.")
        return
    note_text = text.strip()
    nid = next_note_id(ctx.guild.id)
    entry = {"id": nid, "note": note_text, "mod": ctx.author.id, "ts": time.time()}
    notes_store.setdefault(ctx.guild.id, {}).setdefault(member.id, []).append(entry)
    await moon_reply(ctx, f"Note added for {member.mention}. (Note #{nid})")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def warnings(ctx, member: discord.Member = None):
    if member is None:
        await moon_reply(ctx, "Usage: `!warnings @user`")
        return
    user_warnings = warnings_store.get(ctx.guild.id, {}).get(member.id, [])
    user_notes = notes_store.get(ctx.guild.id, {}).get(member.id, [])
    if not user_warnings and not user_notes:
        await moon_reply(ctx, f"{member.mention} has no warnings or notes.")
        return
    embed = discord.Embed(title=f"{MOONLIGHT_EMOJI} RECORDS FOR {member.display_name.upper()}", color=HELP_COLOR)
    if user_warnings:
        lines = [f"**#{w['id']}** — {w['reason']}\n<@{w['mod']}> — {format_timestamp(w['ts'])}" for w in user_warnings]
        embed.add_field(name=f"Warnings ({len(user_warnings)})", value="\n\n".join(lines), inline=False)
    else:
        embed.add_field(name="Warnings (0)", value="None.", inline=False)
    if user_notes:
        lines = [f"**#{n['id']}** — {n['note']}\n<@{n['mod']}> — {format_timestamp(n['ts'])}" for n in user_notes]
        embed.add_field(name=f"Notes ({len(user_notes)})", value="\n\n".join(lines), inline=False)
    else:
        embed.add_field(name="Notes (0)", value="None.", inline=False)
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def notes(ctx, member: discord.Member = None):
    if member is None:
        await moon_reply(ctx, "Usage: `!notes @user`")
        return
    user_notes = notes_store.get(ctx.guild.id, {}).get(member.id, [])
    if not user_notes:
        await moon_reply(ctx, f"{member.mention} has no notes.")
        return
    embed = discord.Embed(title=f"{MOONLIGHT_EMOJI} NOTES FOR {member.display_name.upper()}", color=HELP_COLOR)
    lines = [f"**#{n['id']}** — {n['note']}\n<@{n['mod']}> — {format_timestamp(n['ts'])}" for n in user_notes]
    embed.add_field(name=f"Notes ({len(user_notes)})", value="\n\n".join(lines), inline=False)
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def deletewarn(ctx, warning_id: int = None):
    if warning_id is None:
        await moon_reply(ctx, "Usage: `!deletewarn <id>`")
        return
    guild_warnings = warnings_store.get(ctx.guild.id, {})
    for user_id, entries in guild_warnings.items():
        for i, entry in enumerate(entries):
            if entry["id"] == warning_id:
                entries.pop(i)
                if not entries:
                    del guild_warnings[user_id]
                await moon_reply(ctx, f"Deleted warning #{warning_id}.")
                return
    await moon_reply(ctx, f"No warning with ID #{warning_id} found.")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def deletenote(ctx, note_id: int = None):
    if note_id is None:
        await moon_reply(ctx, "Usage: `!deletenote <id>`")
        return
    guild_notes = notes_store.get(ctx.guild.id, {})
    for user_id, entries in guild_notes.items():
        for i, entry in enumerate(entries):
            if entry["id"] == note_id:
                entries.pop(i)
                if not entries:
                    del guild_notes[user_id]
                await moon_reply(ctx, f"Deleted note #{note_id}.")
                return
    await moon_reply(ctx, f"No note with ID #{note_id} found.")


@bot.command()
async def ping(ctx):
    await moon_reply(ctx, f"Latency: {round(bot.latency * 1000)}ms")


@bot.command()
async def stats(ctx):
    await moon_reply(ctx,
        f"**{MOONLIGHT_EMOJI} MOONLIGHT STATS**\n"
        f"Servers: {len(bot.guilds)}\n"
        f"Uptime: {format_uptime(time.time() - START_TIME)}\n"
        f"Latency: {round(bot.latency * 1000)}ms"
    )


@bot.command()
async def credits(ctx):
    await moon_reply(ctx,
        "**CREDITS**\n"
        "Made by <@" + str(DEVELOPER_ID) + ">\n"
        "Hosted on Railway"
    )


@bot.command(name="help")
async def help_command(ctx):
    embed = build_help_embed()
    await ctx.send(embed=embed)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await moon_reply(ctx, "You don't have the permissions to use that command.")
    elif isinstance(error, commands.MemberNotFound):
        await moon_reply(ctx, "I couldn't find that member.")
    elif isinstance(error, commands.BadArgument):
        await moon_reply(ctx, "That's not a valid argument.")
    else:
        print(f"Command error: {error}")


try:
    bot.run(TOKEN)
except Exception:
    print("=== BOT CRASHED ===")
    print(f"TOKEN present: {bool(TOKEN)}")
    print(f"GROQ present: {bool(GROQ_API_KEY)}")
    traceback.print_exc()
    raise
