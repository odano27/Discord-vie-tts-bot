import discord
from discord.ext import commands
import asyncio
import os

MAIN_BOT_ID = 1481616849958473798

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Watcher Bot logged in as {bot.user}')

@bot.listen('on_message')
async def watch_for_do(message):
    if message.author == bot.user:
        return

    if message.content.strip().lower() == "!dô" or "!status":
        await asyncio.sleep(2.0)
        
        recent_messages = [msg async for msg in message.channel.history(limit=5)]
        
        main_bot_responded = False
        for msg in recent_messages:
            if msg.author.id == MAIN_BOT_ID and msg.created_at >= message.created_at and ("Botdam" in msg.content or "sống" in msg.content):
                main_bot_responded = True
                await message.channel.send("おめでとう\nmời sủa")
                break
        if not main_bot_responded:
            await message.channel.send("botdam đang chết hoặc chưa load xong")

# Start the bot
bot.run(os.environ["DISCORD_TOKEN"])
