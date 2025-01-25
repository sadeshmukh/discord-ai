import datetime
import json
import random
import sys
from dotenv import load_dotenv
load_dotenv()


import logging
import os
import nextcord
from nextcord import Interaction, WebhookMessage, Message
from nextcord.ext import commands, application_checks, tasks
from ai import ChatProvider
from database import BotDatabase

# comma separated list $ADMIN_USERS
ADMIN_USERS = [int(id) for id in os.getenv("ADMIN_USERS", "").split(",")]
# ADMIN_USERS = [892912043240333322, 1270994103584292998]

logging.basicConfig(level=logging.INFO)
if "--debug" in sys.argv:
    logging.getLogger().setLevel(logging.DEBUG)

logging.getLogger("nextcord").setLevel(logging.INFO)
bot_config = json.load(open("botconfig.json"))

database = BotDatabase("data.json")
"""
{
"token_limit": 1000,
"guilds": {
    "guild_id": {
        "bypass_limits": False,
        "channel_id": "channel_id";
        "model": "model_name" # default to llama3
        "system": "system_name"
    }
}

"""

intents = nextcord.Intents.default()
intents.message_content = True
bot = commands.Bot(intents=intents)


# region funny presence stuff
PRESENCES = []
# read from CSV: type, status
with open("presences.csv", "r") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        PRESENCES.append(line.split(","))

async def set_presence(type=nextcord.ActivityType.listening, name="everything you say"):
    await bot.change_presence(activity=nextcord.Activity(type=type, name=name))

async def set_random_presence():
    presence = random.choice(PRESENCES) 
    if presence[0] == "playing":
        await bot.change_presence(activity=nextcord.Game(name=presence[1]))
    elif presence[0] == "listening":
        await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.listening, name=presence[1]))
    elif presence[0] == "watching":
        await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.watching, name=presence[1]))
    else:
        await bot.change_presence(activity=nextcord.Activity(type=nextcord.ActivityType.playing, name=presence[1]))


@tasks.loop(minutes=7)
async def change_presence():
    await set_random_presence()

@change_presence.before_loop
async def before_change_presence():
    await bot.wait_until_ready()
# started at very end
# endregion

chat_provider = ChatProvider("google", "gemini-1.5-flash")
logging.info(f"Using model {chat_provider.model} from {chat_provider.provider}")

TYPING_IN_CHANNELS = []

# captures command errors - not listener errors!
@bot.event
async def on_application_command_error(interaction: nextcord.Interaction, error: Exception):
    logging.error(f"Error during application command execution: {error}")
    if interaction.response.is_done(): # if responded to already, leave it
        return
    if isinstance(error, nextcord.ApplicationCheckFailure):
        await interaction.response.send_message(f"You do not have permissions to use this command.", ephemeral=True)
    else:
        # Handle other unexpected errors
        await interaction.response.send_message("An error occurred during command execution. Please report this to the bot owner.", ephemeral=True)


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")
        
    example_request = await chat_provider.generate_text([{"content": "Hello, world!", "role": "user"}])
    logging.info(example_request)
    # black magic to have it work in all contexts below
    guild = None

    context_types = [0, 1, 2]
    integration_types = [0, 1]

    commands = bot.get_all_application_commands()
    default_payload = [command.get_payload(guild_id=guild) for command in commands if not "hidden" in command.name]

    for item in default_payload:
        item['contexts'] = context_types
        item['integration_types'] = integration_types

    data = await bot.http.bulk_upsert_global_commands(bot.application_id, payload=default_payload)
    # logging.debug(data)

# on guild join, send message in first channel
@bot.event
async def on_guild_join(guild: nextcord.Guild):
    await database.set_guild(guild.id, {"channel_id": None, "model": "gemini-1.5-flash", "system": "google"})
    # get first channel with send permissions
    first_channel = next((channel for channel in guild.text_channels if channel.permissions_for(guild.me).send_messages), None)
    if not first_channel:
        logging.warning(f"Could not find a channel to send welcome message in for {guild.name}")
        return
    await first_channel.send(f"Hello, I am {bot.user.name}. To set me up, use the `/setchannel` command in the channel you want me to respond in.")

@bot.slash_command(description="Welcome to the world of AI!")
async def hello(interaction: Interaction):
    await interaction.response.send_message("Hello, world!")

@bot.slash_command(description="About the bot")
async def about(interaction: Interaction, nodiscord: bool = False):
    await interaction.response.send_message(f"I am {bot.user.mention}, created by @quiteinteresting. To start, run /help to see available commands." + (" Join our Discord server for support and updates: https://discord.gg/3BMdFbEYDW" if not nodiscord else ""))

@bot.slash_command("admin")
async def admin(interaction: Interaction):
    pass

# region Admin

@application_checks.is_owner()
@admin.subcommand()
async def shutdown(interaction: Interaction):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    await interaction.response.send_message("Shutting down...", ephemeral=True)
    await bot.close()

@admin.subcommand()
async def restart(interaction: Interaction):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    await set_presence(type=nextcord.ActivityType.watching, name="myself restart")
    await interaction.response.send_message("Restarting...", ephemeral=True)
    os.execl(sys.executable, sys.executable, *sys.argv)

@admin.subcommand()
async def bypass(interaction: Interaction):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    current_bypass = await database.get_guild_property(interaction.guild.id, "bypass_limits")
    if current_bypass:
        await database.set_guild_property(interaction.guild.id, "bypass_limits", False)
        await interaction.response.send_message("Limits are no longer bypassed.", ephemeral=True)
        return
    await database.set_guild_property(interaction.guild.id, "bypass_limits", True)
    await interaction.response.send_message("Limits are now bypassed.")

@application_checks.is_owner()
@admin.subcommand("usage")
async def check_usage(interaction: Interaction, guild_id: str | None = None):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    if not guild_id:
        # check global usage
        global_daily_usage = sum([guild["usage"]["today"] for guild in database.data.get("guilds", {}).values()])
        global_total_usage = sum([guild["usage"]["total"] for guild in database.data.get("guilds", {}).values()])
        await interaction.response.send_message(f"Global daily usage: {global_daily_usage} | Global total usage: {global_total_usage}", ephemeral=True)
        return
    guild_id = int(guild_id)
    usage = await database.get_guild_property(guild_id, "usage")
    await interaction.response.send_message(f"Today's usage: {usage['today']} | Total usage: {usage['total']}", ephemeral=True)

@admin.subcommand("activetyping")
async def currently_typing(interaction: Interaction):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    await interaction.response.send_message(f"Currently typing in channels: {TYPING_IN_CHANNELS}", ephemeral=True)

@admin.subcommand("delm")
async def delete_message(interaction: Interaction, message_id: str):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    message_id = int(message_id)
    message = await interaction.channel.fetch_message(message_id)
    await message.delete()
    await interaction.response.send_message(f"Deleted message {message_id}", ephemeral=True)

@admin.subcommand("setlimit")
async def set_limit(interaction: Interaction, limit: int):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    await database.set_guild_property(interaction.guild.id, "token_limit", limit)
    await interaction.response.send_message(f"Set token limit to {limit}")

@application_checks.is_owner()
@admin.subcommand("setmodel")
async def set_model(interaction: Interaction, model: str):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    if not model in (MODELS := chat_provider.available_models()): # model is PROVIDER|MODEL
        await interaction.response.send_message(f"Model {model} not available.")
        return
    # provider = next(key for key, value in MODELS.items() if model in value)
    # await database.set_guild_property(interaction.guild.id, "provider", provider)
    await database.set_guild_property(interaction.guild.id, "model", model)
    await interaction.response.send_message(f"Set model to {model}")

@application_checks.is_owner()
@admin.subcommand("listmodels")
async def list_models(interaction: Interaction):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    models = chat_provider.available_models()
    await interaction.response.send_message(f"Available models: {', '.join(models)}")


@application_checks.is_owner()
@admin.subcommand("echo")
async def echo(interaction: Interaction, message: str, ephemeral: bool = True):
    if not (interaction.user.id in ADMIN_USERS):
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    try:
        await interaction.channel.send(message.replace("nnn", "\n"))
        await interaction.response.send_message("Sent message.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(message.replace("nnn", "\n"), ephemeral=ephemeral)

# endregion

# region Hidden

HIDDEN_GUILDS = [int(guild) for guild in os.getenv("HIDDEN_GUILDS", "").split(",")] + [1]

@application_checks.is_owner()
@bot.slash_command("hidden", guild_ids=HIDDEN_GUILDS)
async def hidden(interaction: Interaction):
    pass

@application_checks.is_owner()
@hidden.subcommand("activeguilds")
async def active_guilds(interaction: Interaction):
    # do not retrieve database guilds - retrieve from bot.guilds
    guilds = bot.guilds
    text = "\n".join(f"{guild.name} ({guild.id})" for guild in guilds)
    await interaction.response.send_message(text)

@application_checks.is_owner()
@hidden.subcommand("guildinfo")
async def guild_info(interaction: Interaction, guild_id: str):
    guild_id = int(guild_id)
    guild = await database.get_guild(guild_id)
    await interaction.response.send_message(f"Guild info: {guild}")

# retrieve guild channel list
@application_checks.is_owner()
@hidden.subcommand("guildchannels")
async def guild_channels(interaction: Interaction, guild_id: str):
    guild_id = int(guild_id)
    guild = bot.get_guild(guild_id)
    channels = [channel.name for channel in guild.text_channels]
    await interaction.response.send_message(f"Channels in guild: {channels}")

# retrieve guild member list
@application_checks.is_owner()
@hidden.subcommand("guildmembers")
async def guild_members(interaction: Interaction, guild_id: str):
    guild_id = int(guild_id)
    guild = bot.get_guild(guild_id)
    members = [member.name for member in guild.members]
    await interaction.response.send_message(f"Members in guild: {members}")

@application_checks.is_owner()
@hidden.subcommand("guildleave")
async def guild_leave(interaction: Interaction, guild_id: str):
    guild_id = int(guild_id)
    guild = bot.get_guild(guild_id)
    await guild.leave()
    await interaction.response.send_message(f"Left guild {guild.name} ({guild_id})")

@application_checks.is_owner()
@hidden.subcommand("setguildproperty")
async def set_guild_property(interaction: Interaction, guild_id: str, key: str, value: str, value_type: str = "str"):
    guild_id = int(guild_id)
    if value_type == "int":
        value = int(value)
    await database.set_guild_property(guild_id, key, value)
    await interaction.response.send_message(f"Set guild property {key} to {value}")

@application_checks.is_owner()
@hidden.subcommand("resetallusage")
async def reset_all_usage(interaction: Interaction):
    await _reset_usage()
    await interaction.response.send_message("Reset all daily usage.")

@application_checks.is_owner()
@hidden.subcommand("sendall")
async def send_all(interaction: Interaction, message: str):
    message = message.replace("nnn", "\n")
    await interaction.response.defer()
    for guild in bot.guilds:
        # look for AI channel
        channel_id = await database.get_guild_property(guild.id, "channel_id")
        if not channel_id:
            continue
        channel = bot.get_channel(channel_id)
        await channel.send(message)
    await interaction.followup.send("Sent message to all guilds' ai channels.")

@application_checks.is_owner()
@hidden.subcommand("sendguild")
async def send_guild(interaction: Interaction, guild_id: str, message: str):
    guild_id = int(guild_id)
    message = message.replace("nnn", "\n")
    channel_id = await database.get_guild_property(guild_id, "channel_id")
    if not channel_id:
        await interaction.response.send_message("Channel not set.")
        return
    channel = bot.get_channel(channel_id)
    await channel.send(message)
    await interaction.response.send_message("Sent message.")


# endregion

@application_checks.has_guild_permissions(manage_guild=True)
@bot.slash_command("setchannel", description="Set the channel for the bot to respond in")
async def set_channel(interaction: Interaction):
    await interaction.response.defer()
    setting_message: WebhookMessage = await interaction.followup.send("Setting channel...")
    # check if guild channel is not already set
    if not await database.get_guild(interaction.guild.id):
        # also set model to DEFAULT_MODEL
        await database.set_guild(interaction.guild.id, {"channel_id": interaction.channel.id, "model": "google|gemini-1.5-flash", "system": "You're a helpful assistant."})
        await setting_message.edit("Channel set! Defaulting to Gemini. To edit the system message, use `/system set [message]`.")
        return
    
    await database.set_guild_property(interaction.guild.id, "channel_id", interaction.channel.id)
    await setting_message.edit("Channel set!")

@application_checks.has_guild_permissions(manage_guild=True)
@bot.slash_command("disable", description="Disable the bot in this server")
async def disable(interaction: Interaction):
    # just set channel to None
    await database.set_guild_property(interaction.guild.id, "channel_id", None)
    await interaction.response.send_message("Disabled bot in this server. Use `/setchannel` to re-enable.")

@bot.slash_command("discord", description="Invite to the Discord")
async def discord(interaction: Interaction):
    if not os.getenv("DISCORD_INVITE"):
        await interaction.response.send_message("No Discord invite set.")
        return
    await interaction.response.send_message(os.getenv("DISCORD_INVITE"))

@bot.slash_command("system", description="Modify the system message")
async def system(interaction: Interaction):
    pass

@system.subcommand("set", description="Set the system message")
async def set_system(interaction: Interaction, system: str):
    if not interaction.user.guild_permissions.manage_guild and not interaction.user.id in ADMIN_USERS:
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    if len(system) > 100:
        await interaction.response.send_message("System message too long.", ephemeral=True)
        return
    await interaction.response.defer()
    await database.set_guild_property(interaction.guild.id, "system", system)
    await interaction.followup.send(f"System set: `{system}`")


@application_checks.has_guild_permissions(manage_guild=True)
@system.subcommand("get", description="Get the system message")
async def get_system(interaction: Interaction):
    system = await database.get_guild_property(interaction.guild.id, "system")
    await interaction.response.send_message(f"System: `{system}`")


@bot.slash_command("help", description="Commands list and token reset time")
async def help(interaction: Interaction):
    # DM user with list of commands
    await interaction.response.defer(ephemeral=True)
    # <t:1725580800:t> is a timestamp for 9/5/24 12 AM utc
    # calculate next reset time (day + 1 at 12 AM)
    epoch = datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc)
    now = datetime.datetime.now()
    next_reset = datetime.datetime(now.year, now.month, now.day) + datetime.timedelta(days=1)
    next_reset = next_reset.replace(tzinfo=datetime.timezone.utc)
    next_reset = int((next_reset - epoch).total_seconds())
    HELP_MESSAGE = f"""
    **[Moderator Only] Commands:**
    `/setchannel` - Set the channel for the bot to respond in
    `/disable` - Disable the bot in this server
    `/system set [system]` - Set the system message
    `/system get` - Get the system message
    `/contextlength set [length]` - Set the context length
    `/contextlength get` - Get the context length
    `/break` - Send a breakpoint message in the channel
    `/toggletts` - Toggle TTS
    `/seebots` - Allow/disallow bots to be responded to
    **[User] Commands:**
    `/ignoreme` - The bot will not respond to you or see your messages
    `/peace` - The bot will not ping you
    `/unignoreme` - Unignore you
    `/unpeace` - Unpeace you
    **Other Commands:**
    `/about` - About the bot
    `/hello` - Test command
    `/discord` - Invite to the Discord
    `/help` - This message

    The bot will next reset tokens at <t:{next_reset}:t>.
    """
    await interaction.user.send(HELP_MESSAGE)
    await interaction.followup.send("Help message sent.", ephemeral=True)

# breakpoint: sends message BREAK which stops the history
@bot.slash_command("break", description="Send a breakpoint message in the channel")
async def break_history(interaction: Interaction):
    if not interaction.guild or not interaction.guild.id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild and not interaction.user.id in ADMIN_USERS:
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    channelid = await database.get_guild_property(interaction.guild.id, "channel_id")
    if not channelid:
        await interaction.followup.send("Channel not set.", ephemeral=True)
        return
    channel = bot.get_channel(channelid)
    if not channel:
        await interaction.followup.send("Channel not found.", ephemeral=True)
        return
    await channel.send("-- BREAK --")
    await interaction.followup.send("Created BREAKPOINT.", ephemeral=True)

@bot.slash_command("toggletts", description="Toggle TTS")
async def toggle_tts(interaction: Interaction):
    if not interaction.guild or not interaction.guild.id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild and not interaction.user.id in ADMIN_USERS:
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    tts = await database.get_guild_property(interaction.guild.id, "tts")
    tts = not tts
    await database.set_guild_property(interaction.guild.id, "tts", tts)
    await interaction.followup.send(f"TTS is now {'enabled' if tts else 'disabled'}", ephemeral=True)

@bot.slash_command("seebots", description="Allow/disallow bots to be responded to")
async def see_bots(interaction: Interaction):
    if not interaction.guild or not interaction.guild.id:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_guild and not interaction.user.id in ADMIN_USERS:
        await interaction.response.send_message("You do not have permissions to use this command.", ephemeral=True)
        return
    # toggle see_bots in guild
    see_bots = await database.get_guild_property(interaction.guild.id, "see_bots")
    see_bots = not see_bots
    await database.set_guild_property(interaction.guild.id, "see_bots", see_bots)
    await interaction.response.send_message(f"See bots is now {'enabled' if see_bots else 'disabled'}", ephemeral=True)

@application_checks.has_guild_permissions(manage_guild=True)
@bot.slash_command("contextlength")
async def context_length(interaction: Interaction):
    pass

@application_checks.has_guild_permissions(manage_guild=True)
@context_length.subcommand("set", description="Set the context length")
async def set_context_length(interaction: Interaction, length: int):
    if not 1 <= length <= 12:
        await interaction.response.send_message("Context length must be between 1 and 12.", ephemeral=True)
        return
    await database.set_guild_property(interaction.guild.id, "context_length", length)
    await interaction.response.send_message(f"Set context length to {length}", ephemeral=True)

@application_checks.has_guild_permissions(manage_guild=True)
@context_length.subcommand("get", description="Get the context length")
async def get_context_length(interaction: Interaction):
    length = await database.get_guild_property(interaction.guild.id, "context_length")
    await interaction.response.send_message(f"Context length: {length}", ephemeral=True)

# on deletion
@bot.event
async def on_message_delete(message: nextcord.Message):
    if message.author == bot.user:
        return
    gchannel = await database.get_guild_property(message.guild.id, "channel_id")
    if not gchannel:
        return
    if not message.channel.id == gchannel:
        return
    # check if it is in last 5 messages
    history = await message.channel.history(limit=5).flatten()
    if not message in history:
        return
    # send DELETED <@id>: message
    await message.channel.send(f"DELETED <@{message.author.id}>: {message.content}")

# region Ignore/Peace - set by user within guild

@bot.slash_command("ignoreme", description="Ignore yourself in this channel")
async def ignore_me(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    await database.append_guild_property(interaction.guild.id, "ignored_users", interaction.user.id)
    await interaction.followup.send("Ignoring you in this channel.", ephemeral=True)


@bot.slash_command("peace", description="Disallow pings from the bot for yourself")
async def peace_me(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    await database.append_guild_property(interaction.guild.id, "no_ping_users", {"id": interaction.user.id, "name": interaction.user.name})
    await interaction.followup.send("You are now free from pings (from the bot).", ephemeral=True)


@bot.slash_command("unignoreme", description="Unignore yourself in this channel")
async def unignore_me(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    await database.remove_item_guild_property(interaction.guild.id, "ignored_users", interaction.user.id)
    await interaction.followup.send("Unignoring you in this channel.", ephemeral=True)


@bot.slash_command("unpeace", description="Allow pings from the bot for yourself")
async def unpeace_me(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    no_ping_users = await database.get_guild_property(interaction.guild.id, "no_ping_users", [])
    no_ping_users = [user for user in no_ping_users if user["id"] != interaction.user.id]
    await database.set_guild_property(interaction.guild.id, "no_ping_users", no_ping_users)
    await interaction.followup.send("You are no longer free from pings (from the bot).", ephemeral=True)


# endregion

# on edit of most recent message, delete and send new message
@bot.event
async def on_message_edit(before: nextcord.Message, after: nextcord.Message):
    if before.author == bot.user:
        return
    gchannel = await database.get_guild_property(before.guild.id, "channel_id")
    if not gchannel:
        return
    if not before.channel.id == gchannel:
        return
    # check if it is in last message
    history = await before.channel.history(limit=1).flatten()
    if not before in history:
        return
    # send DELETED <@id>: message
    await before.channel.send(f"EDITED <@{before.author.id}>: {before.content}")

@bot.event
async def on_message(message: nextcord.Message):
    see_bots = await database.get_guild_property(message.guild.id, "see_bots", False)
    if message.author == bot.user or (message.author.bot and not see_bots):
        return
    if not message.guild:
        return
    
    if message.channel.id in TYPING_IN_CHANNELS:
        return
    
    if (not (await database.get_guild_property(message.guild.id, "channel_id")) == message.channel.id ) and not bot.user.mentioned_in(message):
        return

    # check if guild is bypassing limits
    TYPING_IN_CHANNELS.append(message.channel.id)
    try:
      await message.channel.trigger_typing()
    except Exception as e:
      logging.error(f"Error typing: {e}")
      TYPING_IN_CHANNELS.remove(message.channel.id)
      return

    if not await database.get_guild_property(message.guild.id, "usage"):
        await database.set_guild_property(message.guild.id, "usage", {"today": 0, "total": 0})

    if not await database.get_guild_property(message.guild.id, "bypass_limits"):
        await database.set_guild_property(message.guild.id, "bypass_limits", False)
    
    guild_token_limit = int((await database.get_guild_property(message.guild.id, "token_limit")) or bot_config.get("tokenLimit", 1000))

    if not await database.get_guild_property(message.guild.id, "bypass_limits") and (await database.get_guild_property(message.guild.id, "usage"))["today"] >= guild_token_limit:
        
        # check if already sent message
        if (h := await message.channel.history(limit=1).flatten()):
            if h[0].author == bot.user and h[0].content == "You have reached the token limit for today.":
                return
        logging.info(f"Token limit reached for guild {message.guild.id} ({message.guild.name})")
        await message.channel.send("You have reached the token limit for today.")
        return
    # now look through channel history - if empty, stop
    context_limit = (await database.get_guild_property(message.guild.id, "context_length")) or bot_config.get("contextLimit", 5)
    history = await message.channel.history(limit=context_limit).flatten()
    # if breakpoint, stop
    if not history or not len(history) > 1:
        return
    temp_user_names = {}
    temp_user_names[message.author.name] = message.author.id
    temp_display_names = {}
    temp_display_names[message.author.name] = message.author.display_name
    # dict: user_name -> user_id
    # convert above to loop
    ignored_users = await database.get_guild_property(message.guild.id, "ignored_users", [])
    formatted_history = []
    for fmessage in history:
        if fmessage.author.id in ignored_users:
            continue
        if fmessage.content == "-- BREAK --":
            break
        for mention in fmessage.mentions:
            temp_user_names[mention.name] = mention.id
            temp_display_names[mention.name] = mention.display_name
        # replace <@id> with <@name>
        # if message is prefixed with DELETED <@id>: ...content..., treat it as a message from that user and remove the prefix
        if fmessage.content.startswith("DELETED <@"):
            fmessage.content = fmessage.content.split(": ", 1)[1]
            formatted_history.append({"content": f"<@{fmessage.author.name}>: {fmessage.content} <END>", "role": "user" if not fmessage.author.bot else "assistant"})
        else:
          temp_content = f"<@{fmessage.author.name}>: {fmessage.content} <END>"
          for name, id in temp_user_names.items():
              temp_content = temp_content.replace(f"<@{id}>", f"<@{name}>")
          is_user = not fmessage.author.bot if not see_bots else fmessage.author.id != bot.user.id
          formatted_history.append({"content": temp_content, "role": "user" if is_user else "assistant"})
                
    temp = []
    # go through and join consecutive messages from the same role
    for fmessage in formatted_history:
        if not temp:
            temp.append(fmessage)
            continue
        if temp[-1]["role"] == fmessage["role"]:
            temp[-1]["content"] += " " + fmessage["content"]
        else:
            temp.append(fmessage)
    formatted_history = temp

    
    # server_model, server_provider = await database.get_model_info(message.guild.id)
    server_model_info = await database.get_model_info(message.guild.id)
    if "|" in server_model_info:
        server_provider, server_model = server_model_info.split("|")
    else:
        server_model = server_model_info
        server_provider = "google"
    server_system = await database.get_guild_property(message.guild.id, "system")
    if not server_system:
        server_system = bot_config.get("defaultSystem", "You are an assistant.")
    server_system += "\n\nYour name is " + bot.user.name + ". Refer to users by their Display Name, not their mention username."
    for name, display_name in temp_display_names.items():
        server_system += f"\n{name} is displayed as {display_name}"


    # example message to show example formatting
    formatted_history.append({"content": f"<@{bot.user.name}>: Example response! <END>", "role": "assistant"})
    formatted_history.append({"content": f"<@sample.username123>: Example query <END>", "role": "user"})


    formatted_history.append({"content": "SYSTEM: " + server_system + " <END>", "role": "system"})

    formatted_history.reverse()
    usage, response = await chat_provider.generate_text(formatted_history, override_model=server_model, override_provider=server_provider, usage=True)

    total_usage = sum(usage.values())
    current_guild_usage = await database.get_guild_property(message.guild.id, "usage")
    current_guild_usage["today"] += total_usage
    current_guild_usage["total"] += total_usage

    botusername = bot.user.name
    ulen = len(botusername)

    if response[:ulen+1] == f"{botusername}:":
        response = response[ulen+1:]
    if response[:ulen+4] == f"<@{botusername}>:":
        response = response[ulen+4:]

    response = response.replace(f"<@{botusername}>", bot.user.mention)

    # match <@name> -> <@id>
    for name, id in temp_user_names.items():
        response = response.replace(f"<@{name}>", f"<@{id}>")

    response = response.replace("@everyone", "@ everyone")
    response = response.replace("@here", "@ here")
    no_ping_users = await database.get_guild_property(message.guild.id, "no_ping_users", [])
    for user in no_ping_users:
        response = response.replace(f"<@{user['id']}>", user['name'])

    await database.set_guild_property(message.guild.id, "usage", current_guild_usage)
    if not response:
        logging.warning("No response from AI - check stop sequences")
        response = "..."
    use_tts = await database.get_guild_property(message.guild.id, "tts", False)
    if not use_tts:
        use_tts = False
    if len(response) > 2000:
        # split on newlines - ADD THE NEWLINE BACK
        response = response.split("\n")
        temp = []
        current = ""
        for r in response:
            if len(current + r) < 1500:
                temp.append(current)
                current = ""
            else:
                # do the same thing as above, but with " " instead of "\n"
                for r_split in r.split(" "):
                    if len(current + r_split) < 1500:
                        current += r_split + " "
                    else:
                        temp.append(current)
                        current = r_split + " "
                temp.append(current)
                current = ""
            current += r + "\n"
        temp.append(current)
        for t in temp:
            if not t.strip():
                continue
            if len(t) >= 1500:
                logging.warning("Message too long to send")
                logging.debug(t)
                for i in range(0, len(t), 1500):
                    if not t[i:i+1500]:
                        continue
                    await message.channel.send(t[i:i+1500], tts=use_tts)
            await message.channel.send(t, tts=use_tts)

    else:
      try: 
            if message.author.id in ignored_users:
                await message.reply(response, tts=use_tts, mention_author=False)
            else:
                await message.reply(response, tts=use_tts)
      except Exception as e:
            logging.error(f"Error sending message: {e}")
            try:
                await message.channel.send(response)
            except Exception as e:
                logging.error(f"Error sending message: {e}")

          
    TYPING_IN_CHANNELS.remove(message.channel.id)

async def _reset_usage():
    for guild in list(database.data.get("guilds", {}).keys()):
        current_guild_usage = await database.get_guild_property(guild, "usage", {"today": 0, "total": 0})
        current_guild_usage["today"] = 0
        await database.set_guild_property(guild, "usage", current_guild_usage)
    database.save()

# reset daily usage at midnight
@tasks.loop(time=datetime.time(hour=0, minute=0))
async def reset_usage():
    await _reset_usage()

@reset_usage.before_loop
async def before_reset_usage():
    await bot.wait_until_ready()

reset_usage.start()
change_presence.start()
bot.run(os.getenv("TOKEN"))