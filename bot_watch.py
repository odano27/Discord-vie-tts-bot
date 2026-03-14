import discord
from discord.ext import commands
import asyncio
import os
from keep_alive import keep_alive # <-- Added this

MAIN_BOT_ID = 1481616849958473798  # PUT YOUR MAIN BOT ID HERE

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

    if message.content.strip().lower() == "!dô":
        await asyncio.sleep(2.0)
        
        recent_messages = [msg async for msg in message.channel.history(limit=5)]
        
        main_bot_responded = False
        for msg in recent_messages:
            if msg.author.id == MAIN_BOT_ID and msg.created_at >= message.created_at:
                main_bot_responded = True
                await message.channel.send("おめでとう\nmời sủa")
                break
                
        if not main_bot_responded:
            await message.channel.send("botdam đang chết hoặc đánh vần ngu\nmuốn xài thì học chính tả hoặc kêu bot dâm gọi botdam dậy")

# Start the web server
keep_alive() # <-- Added this

# Start the bot
bot.run(os.environ["DISCORD_TOKEN"])
