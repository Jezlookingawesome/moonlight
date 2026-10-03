import discord
from discord.ext import commands
import os
import traceback

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = False

bot = commands.Bot(command_prefix="!", intents=intents)

MOON_EMOJI = "☾"
HELP_COLOR = discord.Color.from_rgb(180, 200, 255)  # soft moonlight blue

DEFAULT_PURGE_AMOUNT = 200
MAX_PURGE_AMOUNT = 200

HELP_TEXT = (
    f"**{MOON_EMOJI} MOONLIGHT — COMMANDS**\n"
    "**Prefix: !**\n\n"
    "**Moderation**\n"
    "`!purge [amount]` — deletes up to 200 messages **from users only** (bots and webhooks are skipped)\n"
    "`!purgeall [amount]` — deletes up to 200 messages **from everyone** (users, bots, webhooks)\n"
    "\n*Amount is optional. If omitted, it purges as many as possible (up to 200).*"
)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int = None):
    """
    Purge messages sent by USERS only (skips bot messages and webhook messages).
    """
    if amount is None:
        amount = DEFAULT_PURGE_AMOUNT
    if amount < 1:
        await ctx.reply(f"{MOON_EMOJI} Amount must be at least 1.")
        return
    if amount > MAX_PURGE_AMOUNT:
        amount = MAX_PURGE_AMOUNT

    # Delete the command message itself so it doesn't count
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    def is_human_user(m):
        # Keep only messages whose author is a human (not a bot, not a webhook)
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
    # Auto-delete the confirmation after 5 seconds
    try:
        import asyncio
        await asyncio.sleep(5)
        await msg.delete()
    except Exception:
        pass


@bot.command()
@commands.has_permissions(manage_messages=True)
async def purgeall(ctx, amount: int = None):
    """
    Purge ALL messages regardless of author (users, bots, webhooks, etc).
    """
    if amount is None:
        amount = DEFAULT_PURGE_AMOUNT
    if amount < 1:
        await ctx.reply(f"{MOON_EMOJI} Amount must be at least 1.")
        return
    if amount > MAX_PURGE_AMOUNT:
        amount = MAX_PURGE_AMOUNT

    # Delete the command message itself so it doesn't count
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
        import asyncio
        await asyncio.sleep(5)
        await msg.delete()
    except Exception:
        pass


@bot.command(name="help")
async def help_command(ctx):
    await ctx.send(HELP_TEXT)


@bot.event
async def on_command_error(ctx, error):
    """Handle permission errors and bad arguments gracefully."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(f"{MOON_EMOJI} You need **Manage Messages** to use that.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply(f"{MOON_EMOJI} That's not a valid number.")
    else:
        # Print to log for debugging but don't spam the channel
        print(f"Command error: {error}")


try:
    bot.run(TOKEN)
except Exception:
    print("=== BOT CRASHED ===")
    print(f"TOKEN present: {bool(TOKEN)}")
    traceback.print_exc()
    raise
