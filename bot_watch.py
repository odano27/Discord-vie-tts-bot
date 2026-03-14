import discord
from discord.ext import commands
import asyncio
import os

# Put your MAIN TTS Bot's User ID here (so the watcher knows who to look for)
MAIN_BOT_ID = 1481616849958473798  

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Watcher Bot logged in as {bot.user}')

@bot.listen('on_message')
async def watch_for_do(message):
    # Ignore the watcher bot's own messages
    if message.author == bot.user:
        return

    # If someone types the join command
    if message.content.strip().lower() == "!dô":
        # Wait 2 seconds to give your local TTS bot time to respond
        await asyncio.sleep(2.0)
        
        # Check the last 5 messages in the channel
        recent_messages = [msg async for msg in message.channel.history(limit=5)]
        
        # Look to see if the main bot replied recently
        main_bot_responded = False
        for msg in recent_messages:
            if msg.author.id == MAIN_BOT_ID and msg.created_at >= message.created_at:
                main_bot_responded = True
                break
                
        # If the main bot didn't reply, send the offline message
        if not main_bot_responded:
            await message.channel.send("botdam đang chết muốn xài thì kêu bot dâm gọi botdam dậy")

# The token will be read from the environment variable we set up on the host
bot.run(os.environ["MTQ4MjE2ODc0Njg0Mjc4Mzc0NA.Ggposw.jwjqgFLu1OjfrGQhlsd16nCfOHd8BSL-RnBCf4"])