import discord
from discord.ext import commands
import aiohttp
import asyncio
import os
import traceback
from io import BytesIO
from PIL import Image, ImageSequence

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

MOON_EMOJI = "☾"
HELP_COLOR = discord.Color.from_rgb(180, 200, 255)

DEFAULT_PURGE_AMOUNT = 200
MAX_PURGE_AMOUNT = 200

DEVELOPER_ID = 1478853756874395762
CRUCIFIXION_GIF_URL = "https://raw.githubusercontent.com/Jezlookingawesome/moonlight/main/ezgif-464c562dc7a53ec6.gif"

HELP_TEXT = (
    f"**{MOON_EMOJI} MOONLIGHT — COMMANDS**\n"
    "**Prefix: !**\n\n"
    "**Moderation**\n"
    "`!purge [amount]` — deletes up to 200 messages **from users only**\n"
    "`!purgeall [amount]` — deletes up to 200 messages **from everyone**\n"
    "\n**Punishment**\n"
    "`!crucifixion @user [reason]` — kicks a user with a gif ritual\n"
    "`!banish @user [reason]` — bans a user with a gif ritual\n"
    "\n*Reason is optional. Default: \"No reason given.\"*"
)


def is_protected(guild, target, requester):
    """
    Returns True if the target is protected from punishment.
    The server owner bypasses all protections.
    Protected: developer, administrators, moderators, Moonlight herself.
    """
    # Owner bypasses everything
    if requester.id == guild.owner_id:
        return False, ""

    # Developer
    if target.id == DEVELOPER_ID:
        return True, "this user is protected (developer)."

    # Moonlight herself
    if target.id == bot.user.id:
        return True, "I can't punish myself."

    # Administrators (guild permission)
    if isinstance(target, discord.Member):
        perms = target.guild_permissions
        if perms.administrator:
            return True, "this user is an administrator."

        # Moderators = anyone with kick/ban/manage_messages/Manage Guild perms
        mod_perms = (
            perms.kick_members or perms.ban_members
            or perms.manage_messages or perms.manage_guild
        )
        if mod_perms:
            return True, "this user is a moderator."

    return False, ""


def check_role_hierarchy(guild, target):
    """
    Returns True if Moonlight can act on the target (target's top role < bot's top role).
    """
    if not isinstance(target, discord.Member):
        return True
    bot_top = guild.me.top_role
    target_top = target.top_role
    return target_top < bot_top


async def fetch_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to fetch {url}: HTTP {resp.status}")
            return await resp.read()


def make_circular_avatar(avatar_bytes: bytes, size: int) -> Image.Image:
    """Download avatar → crop to square → return square Image (no circle mask this time)."""
    img = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    return img


def composite_avatar_on_gif(gif_bytes: bytes, avatar_bytes: bytes) -> BytesIO:
    """
    Overlays the avatar (square) onto every frame of the GIF.
    Position: centered horizontally, in the upper-middle area of the frame.
    Size: 28% of the GIF width.
    Returns a BytesIO with the new GIF.
    """
    src = Image.open(BytesIO(gif_bytes))
    width, height = src.size

    avatar_size = int(width * 0.28)
    avatar = make_circular_avatar(avatar_bytes, avatar_size)

    # Position: horizontal center, vertical ~18% from top (floats above the sigil)
    pos_x = (width - avatar_size) // 2
    pos_y = int(height * 0.18)

    frames = []
    durations = []

    for frame in ImageSequence.Iterator(src):
        frame = frame.convert("RGBA").copy()
        frame.paste(avatar, (pos_x, pos_y), avatar)
        frames.append(frame.convert("P", palette=Image.ADAPTIVE))
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
        await ctx.reply(f"{MOON_EMOJI} Amount must be at least 1.")
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
        await ctx.send(f"{MOON_EMOJI} I don't have permission to delete messages here.")
        return
    except discord.HTTPException as e:
        await ctx.send(f"{MOON_EMOJI} Something went wrong while purging: {e}")
        return

    msg = await ctx.send(f"{MOON_EMOJI} Deleted **{len(deleted)}** user message(s).")
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
        await ctx.reply(f"{MOON_EMOJI} Amount must be at least 1.")
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
        await ctx.send(f"{MOON_EMOJI} I don't have permission to delete messages here.")
        return
    except discord.HTTPException as e:
        await ctx.send(f"{MOON_EMOJI} Something went wrong while purging: {e}")
        return

    msg = await ctx.send(f"{MOON_EMOJI} Deleted **{len(deleted)}** message(s).")
    try:
        await asyncio.sleep(5)
        await msg.delete()
    except Exception:
        pass


async def render_ritual_gif(avatar_url: str) -> BytesIO:
    """Fetch the GIF and the avatar, composite them, return the result."""
    gif_bytes = await fetch_bytes(CRUCIFIXION_GIF_URL)
    avatar_bytes = await fetch_bytes(avatar_url)
    # Composite in a thread so we don't block the event loop on the heavy work
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, composite_avatar_on_gif, gif_bytes, avatar_bytes
    )


async def run_punishment(ctx, target, reason_text, action):
    """
    action = "kick" or "ban"
    Handles protection checks, GIF compositing, sending, and the actual action.
    """
    guild = ctx.guild

    # --- protection check ---
    protected, why = is_protected(guild, target, ctx.author)
    if protected:
        await ctx.reply(f"{MOON_EMOJI} I can't do that — {why}")
        return

    # --- hierarchy check ---
    if not check_role_hierarchy(guild, target):
        await ctx.reply(f"{MOON_EMOJI} I can't act on {target.mention} — they're ranked higher than me.")
        return

    # --- build the GIF ---
    try:
        gif_buf = await render_ritual_gif(str(target.display_avatar.with_size(256).url))
    except Exception as e:
        print(f"GIF render failed: {e}")
        await ctx.reply(f"{MOON_EMOJI} I couldn't render the ritual. The image may be too heavy, or the service is offline.")
        return

    # --- send the GIF ---
    verb = "crucified" if action == "kick" else "banished"
    file = discord.File(gif_buf, filename="ritual.gif")
    try:
        await ctx.send(
            content=f"{MOON_EMOJI} {target.mention} has been {verb}.\n**Reason:** {reason_text}",
            file=file,
        )
    except discord.Forbidden:
        await ctx.reply(f"{MOON_EMOJI} I couldn't send the ritual gif — missing Send/Attach permissions.")
        return
    except Exception as e:
        print(f"Send failed: {e}")
        await ctx.reply(f"{MOON_EMOJI} I couldn't send the ritual gif.")
        return

    # --- execute the punishment ---
    try:
        if action == "kick":
            await target.kick(reason=f"{ctx.author}: {reason_text}")
        else:
            await target.ban(reason=f"{ctx.author}: {reason_text}", delete_message_days=0)
    except discord.Forbidden:
        await ctx.reply(f"{MOON_EMOJI} I couldn't {action} {target.mention} — missing permission.")
    except discord.HTTPException as e:
        await ctx.reply(f"{MOON_EMOJI} I couldn't {action} {target.mention} — Discord rejected the request ({e.status}).")


@bot.command()
@commands.has_permissions(kick_members=True)
async def crucifixion(ctx, member: discord.Member = None, *, reason: str = None):
    if member is None:
        await ctx.reply(f"{MOON_EMOJI} Usage: `!crucifixion @user [reason]`")
        return
    reason_text = reason.strip() if reason and reason.strip() else "No reason given."
    await run_punishment(ctx, member, reason_text, action="kick")


@bot.command()
@commands.has_permissions(ban_members=True)
async def banish(ctx, member: discord.Member = None, *, reason: str = None):
    if member is None:
        await ctx.reply(f"{MOON_EMOJI} Usage: `!banish @user [reason]`")
        return
    reason_text = reason.strip() if reason and reason.strip() else "No reason given."
    await run_punishment(ctx, member, reason_text, action="ban")


@bot.command(name="help")
async def help_command(ctx):
    await ctx.send(HELP_TEXT)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(f"{MOON_EMOJI} You don't have the permissions to use that command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply(f"{MOON_EMOJI} I couldn't find that member.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply(f"{MOON_EMOJI} That's not a valid argument.")
    else:
        print(f"Command error: {error}")


try:
    bot.run(TOKEN)
except Exception:
    print("=== BOT CRASHED ===")
    print(f"TOKEN present: {bool(TOKEN)}")
    traceback.print_exc()
    raise
