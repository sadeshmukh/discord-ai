# TODO: switch to sqlite3 instead of just JSON
import json
from asyncio import to_thread
import logging

"""
{
"token_limit": 1000,
"guilds": {
    "guild_id": {
        "usage": {
            "today": 0,
            "total": 0
        },
        "bypass_limits": False,
        "channel_id": "channel_id";
        "model": "model_name" # default to llama3
        "system": "system_name"
    }
}

"""

class BotDatabase():
    def __init__(self, path):
        self.path = path
        self.data = self.load()

    def load(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        
    def save(self):
        with open(self.path, "w") as f:
            f.write(json.dumps(self.data, indent=2))

    async def get_guild(self, guild_id):
        return self.data.get("guilds", {}).get(str(guild_id), {})
    
    async def set_guild(self, guild_id, data):
        self.data["guilds"] = self.data.get("guilds", {})
        self.data["guilds"][str(guild_id)] = data
        self.save()

    async def set_guild_property(self, guild_id, key, value):
        guild = await self.get_guild(guild_id)
        guild[key] = value
        await self.set_guild(guild_id, guild)
        self.save()
    
    async def append_guild_property(self, guild_id, key, value):
        guild = await self.get_guild(guild_id)
        guild[key] = guild.get(key, [])
        try:
            guild[key].append(value)
        except AttributeError:
            guild[key] = value
        except Exception as e:
            logging.error(e)
            return f"Fatal error: {e}"
        await self.set_guild(guild_id, guild)
        self.save()

    async def remove_item_guild_property(self, guild_id, key, value):
        guild = await self.get_guild(guild_id)
        guild[key] = guild.get(key, [])
        try:
            guild[key].remove(value)
        except AttributeError:
            guild[key] = value
        except Exception as e:
            logging.error(e)
            return f"Fatal error: {e}"
        await self.set_guild(guild_id, guild)
        self.save()
        

    async def get_guild_property(self, guild_id, key, default=None):
        return (await self.get_guild(guild_id)).get(key, default)

    async def get_model_info(self, guild_id) -> str:
        return (await self.get_guild(guild_id)).get("model")
    