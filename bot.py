import discord
from discord.ext import commands
from gtts import gTTS
import asyncio
import os
import json
import typing
import threading
import re

from vieneu import Vieneu

vieneu_tts = Vieneu()
print("VieNeu Tải Xong!")

MOD_ROLE_ID = 1315683389449310349

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

tts_channels = {}
last_speakers = {}
tts_queues = {}
BOT_DATA = {}
current_playing = {}
cancelled_msgs = set()

infer_lock = threading.Lock()
DATA_FILE = "data.json"

LANGUAGES_VI = {
    "af": "Tiếng Afrikaans", "ar": "Tiếng Ả Rập", "bg": "Tiếng Bulgaria", "ca": "Tiếng Catalan",
    "zh": "Tiếng Trung (Quan Thoại)", "cs": "Tiếng Séc", "da": "Tiếng Đan Mạch", "nl": "Tiếng Hà Lan",
    "en": "Tiếng Anh", "fi": "Tiếng Phần Lan", "fr": "Tiếng Pháp", "de": "Tiếng Đức",
    "el": "Tiếng Hy Lạp", "gu": "Tiếng Gujarati", "hi": "Tiếng Hindi", "hu": "Tiếng Hungary",
    "id": "Tiếng Indonesia", "it": "Tiếng Ý", "ja": "Tiếng Nhật", "ko": "Tiếng Hàn",
    "no": "Tiếng Na Uy", "pl": "Tiếng Ba Lan", "pt": "Tiếng Bồ Đào Nha", "ru": "Tiếng Nga",
    "es": "Tiếng Tây Ban Nha", "sv": "Tiếng Thụy Điển", "th": "Tiếng Thái", "tr": "Tiếng Thổ Nhĩ Kỳ",
    "vi": "Tiếng Việt", "vn": "Tiếng Việt",
    "en-AU": "Tiếng Anh (Úc)", "en-CA": "Tiếng Anh (Canada)", "en-GB": "Tiếng Anh (Anh)",
    "en-IN": "Tiếng Anh (Ấn Độ)", "en-IE": "Tiếng Anh (Ireland)", "en-NG": "Tiếng Anh (Nigeria)",
    "en-ZA": "Tiếng Anh (Nam Phi)", "en-US": "Tiếng Anh (Mỹ)",
    "fr-CA": "Tiếng Pháp (Canada)", "fr-FR": "Tiếng Pháp (Pháp)",
    "zh-CN": "Tiếng Trung (Đại lục)", "zh-TW": "Tiếng Trung (Đài Loan)",
    "pt-BR": "Tiếng Bồ Đào Nha (Brazil)", "pt-PT": "Tiếng Bồ Đào Nha (Bồ Đào Nha)",
    "es-MX": "Tiếng Tây Ban Nha (Mexico)", "es-ES": "Tiếng Tây Ban Nha (Tây Ban Nha)", "es-US": "Tiếng Tây Ban Nha (Mỹ)"
}

class KeepAliveSilence(discord.AudioSource):
    def __init__(self):
        self.frames = 5
    def read(self):
        if self.frames > 0:
            self.frames -= 1
            return b'\x00' * 3840
        return b''

def split_text_for_tts(text, max_words=15):
    tokens = re.split(r'([.,?!;:\n]+)', text)
    clauses = []
    current_clause = ""
    for token in tokens:
        if re.match(r'^[.,?!;:\n]+$', token):
            current_clause += token
            clauses.append(current_clause.strip())
            current_clause = ""
        else:
            current_clause += token
    if current_clause.strip():
        clauses.append(current_clause.strip())
    chunks = []
    for clause in clauses:
        if not clause: continue
        words = clause.split()
        for i in range(0, len(words), max_words):
            chunks.append(" ".join(words[i:i+max_words]))
    return chunks

def load_data():
    global BOT_DATA
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            BOT_DATA = json.load(f)
    else:
        BOT_DATA = {}

async def save_data_async():
    def _save():
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(BOT_DATA, f, indent=4, ensure_ascii=False)
    await asyncio.to_thread(_save)

def get_guild_data(guild_id):
    gid = str(guild_id)
    if gid not in BOT_DATA:
        BOT_DATA[gid] = {
            "prefix": "sủa",
            "announce": True,
            "nicknames": {},
            "muted":[],
            "languages": {},
            "vieneu_voices": {}
        }
    if "languages" not in BOT_DATA[gid]: BOT_DATA[gid]["languages"] = {}
    if "vieneu_voices" not in BOT_DATA[gid]: BOT_DATA[gid]["vieneu_voices"] = {}
    return BOT_DATA, gid

def tao_file_am_thanh(text, lang, filename, voice_id=None):
    if lang in ['vn']:
        with infer_lock:
            if voice_id:
                try:
                    voice_data = vieneu_tts.get_preset_voice(voice_id)
                    audio_data = vieneu_tts.infer(text=text, voice=voice_data)
                except Exception as e:
                    print(f"Lỗi giọng {voice_id}: {e}")
                    audio_data = vieneu_tts.infer(text=text)
            else:
                audio_data = vieneu_tts.infer(text=text)
            vieneu_tts.save(audio_data, filename)
    else:
        tts = gTTS(text=text, lang=lang)
        tts.save(filename)

async def tts_worker(guild_id):
    while True:
        try:
            queue_item = await asyncio.wait_for(tts_queues[guild_id].get(), timeout=50.0)
        except asyncio.TimeoutError:
            guild = bot.get_guild(guild_id)
            if not guild or not guild.voice_client or not guild.voice_client.is_connected():
                if guild_id in tts_queues:
                    del tts_queues[guild_id]
                break
            if not guild.voice_client.is_playing():
                try:
                    guild.voice_client.play(KeepAliveSilence())
                except discord.ClientException:
                    pass
            continue

        base_msg_id = queue_item["base_msg_id"]
        filename = queue_item["filename"]

        if base_msg_id in cancelled_msgs:
            try: await queue_item["task"]
            except: pass
            if os.path.exists(filename):
                try: os.remove(filename)
                except: pass
            tts_queues[guild_id].task_done()
            continue

        current_playing[guild_id] = base_msg_id

        try:
            await queue_item["task"]
        except Exception as e:
            print(f"Lỗi tạo audio: {e}")
            tts_queues[guild_id].task_done()
            continue

        if base_msg_id in cancelled_msgs:
            if os.path.exists(filename):
                try: os.remove(filename)
                except: pass
            tts_queues[guild_id].task_done()
            continue

        guild = bot.get_guild(guild_id)
        if not guild or not guild.voice_client:
            tts_queues[guild_id].task_done()
            continue

        voice_client = guild.voice_client

        try:
            audio_source = discord.FFmpegPCMAudio(filename, options='-vn -sn')
            if voice_client.is_connected():
                if voice_client.is_playing():
                    voice_client.stop()
                play_finished = asyncio.Event()
                def after_play(error):
                    bot.loop.call_soon_threadsafe(play_finished.set)
                voice_client.play(audio_source, after=after_play)
                await play_finished.wait()
        except Exception as e:
            print(f"Lỗi trong quá trình phát: {e}")
        finally:
            if os.path.exists(filename):
                try: os.remove(filename)
                except: pass
            tts_queues[guild_id].task_done()

def push_to_queue(guild_id, payload):
    if guild_id not in tts_queues:
        tts_queues[guild_id] = asyncio.Queue()
        bot.loop.create_task(tts_worker(guild_id))
    
    file_ext = "wav" if payload["lang"] in ['vn'] else "mp3"
    filename = f"audio_{payload['msg_id']}.{file_ext}"

    gen_task = bot.loop.create_task(
        asyncio.to_thread(tao_file_am_thanh, payload["text"], payload["lang"], filename, payload["voice_id"])
    )
    
    tts_queues[guild_id].put_nowait({
        "task": gen_task,
        "filename": filename,
        "base_msg_id": payload["base_msg_id"]
    })

def clear_queue(guild_id):
    if guild_id in tts_queues:
        while not tts_queues[guild_id].empty():
            try:
                item = tts_queues[guild_id].get_nowait()
                item["task"].cancel()
                def cleanup(f, fname=item["filename"]):
                    try:
                        if os.path.exists(fname): os.remove(fname)
                    except: pass
                item["task"].add_done_callback(cleanup)
            except: break

async def show_muted(ctx, data, gid):
    muted = data[gid]["muted"]
    if not muted:
        await ctx.send("Không có ai đang bị bịt mỏ.")
    else:
        mentions = ", ".join([f"<@{m}>" for m in muted])
        await ctx.send(f"Các con dợ {mentions} đang bị bịt mỏ")

@bot.event
async def on_ready():
    load_data()
    print(f'Bot đã sẵn sàng! Đăng nhập dưới tên {bot.user.name}')

@bot.command()
async def dô(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        tts_channels[ctx.guild.id] = ctx.channel.id
        last_speakers[ctx.guild.id] = None
        
        clear_queue(ctx.guild.id)

        data, gid = get_guild_data(ctx.guild.id)
        current_prefix = data[gid]["prefix"]
        instructions = f"Botdam đã xuất hiện\n`{current_prefix} [gì đó]` để đọc\n`!cú` nếu bị ngu"

        if not ctx.guild.voice_client:
            await channel.connect()
            await ctx.send(instructions)
            await ctx.send("https://tenor.com/view/peepo-arrive-pepe-gif-18118119")
            if ctx.guild.id not in tts_queues:
                tts_queues[ctx.guild.id] = asyncio.Queue()
                bot.loop.create_task(tts_worker(ctx.guild.id))
        else:
            await ctx.send(f"Đã đổi channel\n{instructions}")
    else:
        await ctx.send("Dô đây tao mới dô")

@bot.command()
async def cú(ctx):
    data, gid = get_guild_data(ctx.guild.id)
    current_prefix = data[gid]["prefix"]
    instructions = (
        f"{ctx.author.mention} bị ngu\n`{current_prefix} [gì đó]` để đọc\n"
        "`!cút` để đá đít\n"
        "`!tiếng [code]` đổi ngôn ngữ\n"
        "`!dsgiọng` xem các giọng VN hiện có\n"
        "`!giọng [số]` đổi giọng cá nhân\n"
        "`!prefix [txt]` để sửa prefix\n"
        "`!announce true/false` để sủa tên\n"
        "`!tên [tên]` để đổi tên\n"
        "`!nín @condợ` để bịt mỏ con dợ\n"
        "`!mồm @condợ` để mở miệng con dợ\n"
        "`!im` để bịt mỏ tao"
    )
    await ctx.send(instructions)

@bot.command()
async def cút(ctx):
    if ctx.guild.voice_client:
        await ctx.guild.voice_client.disconnect()
        last_speakers[ctx.guild.id] = None
        clear_queue(ctx.guild.id)
        cancelled_msgs.clear()
        await ctx.send("Botdam đã chết")
    else:
        await ctx.send("có ở trong đây đéo đâu mà cút")

@bot.command()
async def im(ctx):
    gid = ctx.guild.id
    if gid in current_playing:
        cancelled_msgs.add(current_playing[gid])
    if ctx.guild.voice_client and ctx.guild.voice_client.is_playing():
        ctx.guild.voice_client.stop()
    await ctx.message.add_reaction("🛑")

@bot.command()
async def channel(ctx):
    tts_channels[ctx.guild.id] = ctx.channel.id
    last_speakers[ctx.guild.id] = None
    await ctx.send(f"Sủa vào channel {ctx.channel.mention}")

@bot.command()
async def tiếng(ctx, lang_code: typing.Optional[str] = None):
    data, gid = get_guild_data(ctx.guild.id)
    
    if lang_code is None:
        current_lang = data[gid]["languages"].get(str(ctx.author.id), 'vi')
        lang_name = LANGUAGES_VI.get(current_lang, current_lang)
        msg = f"{ctx.author.mention} đang sủa {lang_name}"
        
        if current_lang == 'vn':
            current_voice = data[gid]["vieneu_voices"].get(str(ctx.author.id))
            if current_voice:
                voices = vieneu_tts.list_preset_voices()
                for i, (desc, voice_id) in enumerate(voices):
                    if voice_id == current_voice:
                        msg += f" bằng giọng {i}"
                        break
        return await ctx.send(msg)
        
    data[gid]["languages"][str(ctx.author.id)] = lang_code
    await save_data_async()
    lang_name = LANGUAGES_VI.get(lang_code, lang_code)
    await ctx.send(f"{ctx.author.mention} từ giờ sẽ sủa {lang_name}")
    

@bot.command()
async def dsgiọng(ctx):
    voices = vieneu_tts.list_preset_voices()
    if not voices:
        return await ctx.send("Không tìm thấy giọng mẫu nào!")
    
    msg = "**🎤 Danh sách giọng Tiếng Việt (VieNeu):**\n"
    for i, (desc, voice_id) in enumerate(voices):
        msg += f"`{i}` - {desc}\n"
    msg += "\n👉 Gõ lệnh `!giọng [số]` để chọn (Ví dụ: `!giọng 1`)"
    await ctx.send(msg)

@bot.command()
async def giọng(ctx, index: str):
    if not index.isdigit():
        return await ctx.send("Đụ má nhập SỐ thôi! Ví dụ: `!giọng 1` (Gõ `!dsgiọng` để xem).")
    
    index = int(index)
    voices = vieneu_tts.list_preset_voices()
    if index < 0 or index >= len(voices):
        return await ctx.send("Số đéo hợp lệ đụ má! Gõ `!dsgiọng` để xem danh sách.")
    
    desc, voice_id = voices[index]
    data, gid = get_guild_data(ctx.guild.id)
    data[gid]["vieneu_voices"][str(ctx.author.id)] = voice_id
    await save_data_async()
    await ctx.send(f"{ctx.author.mention} đã đổi sang giọng: **{desc}**")

@bot.command()
async def prefix(ctx, new_prefix: str):
    data, gid = get_guild_data(ctx.guild.id)
    data[gid]["prefix"] = new_prefix
    await save_data_async()
    await ctx.send(f"Trước khi sủa hãy: `{new_prefix}`")

@bot.command()
async def announce(ctx, toggle: typing.Optional[str] = None):
    data, gid = get_guild_data(ctx.guild.id)
    
    if toggle is None:
        trang_thai = "có" if data[gid]["announce"] else "không"
        return await ctx.send(f"Đang {trang_thai} sủa tên.")
        
    toggle = toggle.lower()
    if toggle not in ["true", "false"]:
        return await ctx.send("`true` hay `false` đụ ngựa")
        
    is_true = (toggle == "true")
    data[gid]["announce"] = is_true
    await save_data_async()
    trang_thai_moi = "bật" if is_true else "tắt"
    await ctx.send(f"Đã {trang_thai_moi} sủa tên.")

@bot.command()
async def tên(ctx, *, args: typing.Optional[str] = None):
    data, gid = get_guild_data(ctx.guild.id)
    
    if not args:
        current_name = data[gid]["nicknames"].get(str(ctx.author.id), ctx.author.display_name)
        return await ctx.send(f"{ctx.author.mention} là: **{current_name}**")
        
    target = ctx.author
    nickname = args
    
    try:
        parts = args.split(maxsplit=1)
        parsed_member = await commands.MemberConverter().convert(ctx, parts[0])
        if len(parts) > 1:
            target = parsed_member
            nickname = parts[1]
        else:
            current_name = data[gid]["nicknames"].get(str(parsed_member.id), parsed_member.display_name)
            return await ctx.send(f"{parsed_member.mention} là: **{current_name}**")
    except commands.BadArgument:
        pass
        
    data[gid]["nicknames"][str(target.id)] = nickname
    await save_data_async()
    await ctx.send(f"{target.mention} biến thành **{nickname}**.")
    return await ctx.send("https://tenor.com/view/vine-morph-vinesauce-vinny-vinesauce-duck-transformation-gif-25311790")

@bot.command()
async def nín(ctx, target: typing.Optional[typing.Union[discord.Member, str]] = None):
    data, gid = get_guild_data(ctx.guild.id)
    if target is None:
        return await show_muted(ctx, data, gid)
        
    mod_role = discord.utils.get(ctx.guild.roles, id=MOD_ROLE_ID)
    if mod_role not in ctx.author.roles and not ctx.author.guild_permissions.administrator:
        await ctx.send("cha mày")
        return await ctx.send("https://tenor.com/view/nuh-uh-gif-17210163150458403844")
        
    if isinstance(target, discord.Member):
        target_id = str(target.id)
        if target_id not in data[gid]["muted"]:
            data[gid]["muted"].append(target_id)
            await save_data_async()
        await ctx.send(f"Đã khóa mồm {target.mention}!")
        return await ctx.send("https://tenor.com/view/shut-up-shut-up-be-quiet-funny-gif-2290609444616872411")

@bot.command()
async def mồm(ctx, target: typing.Optional[typing.Union[discord.Member, str]] = None):
    data, gid = get_guild_data(ctx.guild.id)
    if target is None:
        return await show_muted(ctx, data, gid)
        
    mod_role = discord.utils.get(ctx.guild.roles, id=MOD_ROLE_ID)
    if mod_role not in ctx.author.roles and not ctx.author.guild_permissions.administrator:
        await ctx.send("cha mày")
        return await ctx.send("https://tenor.com/view/nuh-uh-gif-17210163150458403844")
        
    if isinstance(target, str) and target.lower() == "all":
        data[gid]["muted"] = []
        await save_data_async()
        await ctx.send("Đã mở mồm cho tất cả!")
        return await ctx.send("https://tenor.com/view/furina-genshin-genshin-impact-cool-burst-gif-11321952489220096466")
        
    if isinstance(target, discord.Member):
        target_id = str(target.id)
        if target_id in data[gid]["muted"]:
            data[gid]["muted"].remove(target_id)
            await save_data_async()
        await ctx.send(f"Đã mở mồm cho {target.mention}!")
        await ctx.send("https://tenor.com/view/furina-genshin-genshin-impact-cool-burst-gif-11321952489220096466")

@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author.bot or message.content.startswith("!"):
        return

    voice_client = message.guild.voice_client
    if not voice_client:
        return

    chosen_channel_id = tts_channels.get(message.guild.id)
    if message.channel.id != chosen_channel_id:
        return

    data, gid = get_guild_data(message.guild.id)

    if str(message.author.id) in data[gid]["muted"]:
        return

    msg_content = message.content
    req_prefix = data[gid]["prefix"].lower()
    
    if msg_content.lower().startswith(req_prefix):
        msg_content = msg_content[len(req_prefix):].strip()
    else:
        return

    if not msg_content:
        return

    display_name = data[gid]["nicknames"].get(str(message.author.id), message.author.display_name)
    if data[gid]["announce"]:
        if last_speakers.get(message.guild.id) != message.author.id:
            text_to_read = f"{display_name}, {msg_content}"
        else:
            text_to_read = msg_content
    else:
        text_to_read = msg_content

    last_speakers[message.guild.id] = message.author.id

    lang_code = data[gid]["languages"].get(str(message.author.id), 'vi')
    gtts_lang = lang_code.split("-")[0]
    voice_id = data[gid]["vieneu_voices"].get(str(message.author.id), None)

    chunks = split_text_for_tts(text_to_read, max_words=15)
    
    for i, chunk in enumerate(chunks):
        payload = {
            "text": chunk,
            "lang": gtts_lang,
            "voice_id": voice_id,
            "msg_id": f"{message.id}_{i}",
            "base_msg_id": str(message.id)
        }
        push_to_queue(message.guild.id, payload)

# bot.run("YOUR_TOKEN_HERE")
bot.run("DISCORD_TOKEN")
