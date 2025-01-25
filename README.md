# Discord AI
I originally wrote this bot with absolutely no intention of writing more than maybe 100 lines of code. As it grew, I moved it here, rewrote it from scratch, and it's became (again) a little bit of a mess. However, it works, dare I say, pretty well for what it is - and that's the greatest part of it! If you have any questions, you can contact me through email at hello@sahil.ink.

You can add the bot to test it [here](https://discord.com/oauth2/authorize?client_id=1100966976366579713).

## Configuration
You must include the TOKEN environment variable (this is your discord bot token).
You must include at least one of the following env variables in your .env file:
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
You may include the following in your .env file (you should probably at your user ID as an ADMIN user).
ADMIN_USERS=
DISCORD_INVITE=
HIDDEN_GUILDS=

Additionally, you should edit your models.json file to reflect which models your bot supports.

To set custom presence messages, you can create a presences.csv. Each line should be have a first item "listening", "watching", or "playing".

In your botconfig.json, the parameters are specified. This is the default initialization on any server.

## Running
You can create a Discord bot through the Discord Developer Dashboard. Make sure to enable the Read Messages intent, and also the following permissions: Read Message History, Send Messages, Send Messages in Threads, View Channels. Make sure to allow it to use Application Commands (also called Slash Commands).

Once your TOKEN is set, you can run the bot with [poetry](https://python-poetry.org/). Run `poetry install` (one-time), then `poetry run python bot.py`.

For a description of commands, use /help once starting. For commands not listed (such as those under admin or hidden), the names should describe their purpose.