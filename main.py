import discord
from discord.ext import commands
import aiohttp
import asyncio
import os
import time
import traceback
from io import BytesIO
from PIL import Image, ImageSequence

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

MOONLIGHT_EMOJI = "<:moonlight:1556048220671447132>"
HELP_COLOR = discord.Color.from_rgb(120, 220, 230)  # warm cyan

DEFAULT_PURGE_AMOUNT = 200
MAX_PURGE_AMOUNT = 200

DEVELOPER_ID = 1478853756874395762
CRUCIFIXION_GIF_URL = "https://raw.githubusercontent.com/Jezlookingawesome/moonlight/main/ezgif-464c562dc7a53ec6.gif"

START_TIME = time.time()

HELP_LINES = [
    ("Moderation", [
        ("!purge [amount]", "deletes up to 200 messages from users only"),
        ("!purgeall [amount]", "deletes up to 200 messages from everyone"),
    ]),
    ("Punishment", [
        ("!crucifixion @user [reason]", "kicks a user with a gif ritual"),
        ("!banish @user [reason]", "bans a user with a gif ritual"),
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
    """Reply with the Moonlight emoji appended via em dash."""
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

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


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
    traceback.print_exc()
    raise
