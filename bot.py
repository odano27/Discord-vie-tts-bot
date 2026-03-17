import discord
from discord.ext import commands
from gtts import gTTS
import asyncio
import os
import json
import typing
import re
import wave
import time
import subprocess

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
tts_semaphore = None

DATA_FILE = "data.json"

LANGUAGES_VI = {
    "af": "Tiếng Afrikaans", "ar": "Tiếng Ả Rập", "bg": "Tiếng Bulgaria", "ca": "Tiếng Catalan",
    "zh": "Tiếng Trung (Quan Thoại)", "cs": "Tiếng Séc", "da": "Tiếng Đan Mạch", "nl": "Tiếng Hà Lan",
    "en": "Tiếng Anh", "fi": "Tiếng Phần Lan", "fr": "Tiếng Pháp", "de": "Tiếng Đức",
    "el": "Tiếng Hy Lạp", "gu": "Tiếng Gujarati", "hi": "Tiếng Hindi", "hu": "Tiếng Hungary",
    "id": "Tiếng Indonesia", "it": "Tiếng Ý", "ja": "Tiếng Nhật", "ko": "Tiếng Hàn",
    "no": "Tiếng Na Uy", "pl": "Tiếng Ba Lan", "pt": "Tiếng Bồ Đào Nha", "ru": "Tiếng Nga",
    "es": "Tiếng Tây Ban Nha", "sv": "Tiếng Thụy Điển", "th": "Tiếng Thái", "tr": "Tiếng Thổ Nhĩ Kỳ",
    "vi": "Tiếng Việt", "vn": "Tiếng Việt", "vi-vn": "Tiếng Việt (Piper)",
    "en-au": "Tiếng Anh (Úc)", "en-ca": "Tiếng Anh (Canada)", "en-gb": "Tiếng Anh (Anh Piper)",
    "en-in": "Tiếng Anh (Ấn Độ)", "en-ie": "Tiếng Anh (Ireland)", "en-ng": "Tiếng Anh (Nigeria)",
    "en-za": "Tiếng Anh (Nam Phi)", "en-us": "Tiếng Anh (Mỹ Piper)",
    "fr-ca": "Tiếng Pháp (Canada)", "fr-fr": "Tiếng Pháp (Pháp)",
    "zh-cn": "Tiếng Trung (Đại lục)", "zh-tw": "Tiếng Trung (Đài Loan)",
    "pt-br": "Tiếng Bồ Đào Nha (Brazil)", "pt-pt": "Tiếng Bồ Đào Nha (Bồ Đào Nha)",
    "es-mx": "Tiếng Tây Ban Nha (Mexico)", "es-es": "Tiếng Tây Ban Nha (Tây Ban Nha)", "es-us": "Tiếng Tây Ban Nha (Mỹ)"
}

class KeepAliveSilence(discord.AudioSource):
    def __init__(self):
        self.frames = 5
    def read(self):
        if self.frames > 0:
            self.frames -= 1
            return b'\x00' * 3840
        return b''

def split_text_for_tts(text, max_words=25):
    tokens = re.split(r'([.,?!;:\n]+)', text)
    clauses =[]
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
    chunks =[]
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

def tao_file_am_thanh(text, lang, filename, voice_id=None, metrics=None):
    if metrics is None: metrics = {}

    lang_lower = lang.lower().split('-')[0]
    if lang_lower == 'vn':
        lang_lower = 'vi'

    tts = gTTS(text=text, lang=lang_lower)
    tts.save(filename)
    
    metrics['gtts_done'] = time.time()

def xoa_file(fname):
    try:
        if os.path.exists(fname):
            os.remove(fname)
    except:
        pass
    
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
        volume = queue_item.get("volume", 1.0)
        speed = queue_item.get("speed", 1.0)
        metrics = queue_item.get("metrics", {})

        if base_msg_id in cancelled_msgs:
            try: await queue_item["task"]
            except: pass
            await asyncio.to_thread(xoa_file, filename)
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
            await asyncio.to_thread(xoa_file, filename)
            tts_queues[guild_id].task_done()
            continue

        guild = bot.get_guild(guild_id)
        if not guild or not guild.voice_client:
            tts_queues[guild_id].task_done()
            continue

        voice_client = guild.voice_client

        try:
            ffmpeg_options = '-vn -sn'
            ffmpeg_before_options = '-analyzeduration 0 -loglevel error'
            
            audio_filters =[]
            if volume != 1.0:
                audio_filters.append(f"volume={volume}")
            if speed != 1.0:
                speed_clamped = max(0.5, min(speed, 100.0))
                audio_filters.append(f"atempo={speed_clamped}")
                
            if audio_filters:
                ffmpeg_options += f' -filter:a "{",".join(audio_filters)}"'

            t_ffmpeg_start = time.time()
            
            audio_source = await asyncio.to_thread(
                discord.FFmpegPCMAudio, 
                filename, 
                options=ffmpeg_options,
                before_options=ffmpeg_before_options
            )
            
            metrics['ffmpeg_done'] = time.time()
            
            if voice_client.is_connected():
                if voice_client.is_playing():
                    voice_client.stop()
                
                play_finished = asyncio.Event()
                def after_play(error):
                    bot.loop.call_soon_threadsafe(play_finished.set)
                
                voice_client.play(audio_source, after=after_play)
                metrics['discord_play'] = time.time()
                
                try:
                    t0 = metrics['t0_received']
                    t1 = metrics['t1_processed']
                    t2 = metrics['gtts_done']
                    t3_start = t_ffmpeg_start
                    t3_done = metrics['ffmpeg_done']
                    t4 = metrics['discord_play']
                    #print(f"1. Python processing: {(t1 - t0)*1000:7.2f} ms")
                    print(f"2. gTTS API:          {(t2 - t1)*1000:7.2f} ms")
                    #print(f"3. Queue:             {(t3_start - t2)*1000:7.2f} ms")
                    print(f"4. FFmpeg:            {(t3_done - t3_start)*1000:7.2f} ms")
                    #print(f"5. Discord Play:      {(t4 - t3_done)*1000:7.2f} ms")
                    #print(f"--------------------------------------------")
                    print(f"Processing delay:     {(t4 - t0 - t3_start + t2)*1000:7.2f} ms")
                    #print(f"============================================\n")
                except KeyError:
                    pass

                await play_finished.wait()
        except Exception as e:
            print(f"Lỗi trong quá trình phát: {e}")
        finally:
            await asyncio.to_thread(xoa_file, filename)
            tts_queues[guild_id].task_done()

def clear_queue(guild_id):
    if guild_id in tts_queues:
        while not tts_queues[guild_id].empty():
            try:
                item = tts_queues[guild_id].get_nowait()
                item["task"].cancel()
                def cleanup(f, fname=item["filename"]):
                    bot.loop.create_task(asyncio.to_thread(xoa_file, fname))
                item["task"].add_done_callback(cleanup)
            except: break

async def safe_generate_tts(text, lang, filename, voice_id, metrics):
    global tts_semaphore
    if tts_semaphore is None:
        tts_semaphore = asyncio.Semaphore(2) 
        
    async with tts_semaphore:
        await asyncio.to_thread(tao_file_am_thanh, text, lang, filename, voice_id, metrics)

def push_to_queue(guild_id, payload):
    if guild_id not in tts_queues:
        tts_queues[guild_id] = asyncio.Queue()
        bot.loop.create_task(tts_worker(guild_id))
    
    file_ext = "mp3"
    filename = f"audio_{payload['msg_id']}.{file_ext}"

    gen_task = bot.loop.create_task(
        safe_generate_tts(payload["text"], payload["lang"], filename, payload["voice_id"], payload["metrics"])
    )
    
    tts_queues[guild_id].put_nowait({
        "task": gen_task,
        "filename": filename,
        "base_msg_id": payload["base_msg_id"],
        "volume": payload.get("volume", 1.0),
        "speed": payload.get("speed", 1.0),
        "metrics": payload.get("metrics", {})
    })

async def show_muted(ctx, data, gid):
    muted = data[gid]["muted"]
    if not muted:
        await ctx.send("Không có ai đang bị bịt mỏ.")
    else:
        mentions = ", ".join([f"<@{m}>" for m in muted])
        await ctx.send(f"Các con dợ {mentions} đang bị bịt mỏ")

async def keep_ffmpeg_warm():
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            await proc.wait()
        except Exception:
            pass
        await asyncio.sleep(3600)

@bot.event
async def on_ready():
    load_data()
    print(f'Bot đã sẵn sàng! Đăng nhập dưới tên {bot.user.name}')
    #bot.loop.create_task(keep_ffmpeg_warm())

def warmup_gtts():
    try:
        tts = gTTS(text="ハローエブリニャン", lang="ja")
        dummy_file = "warmup_dummy.mp3"
        tts.save(dummy_file)
        if os.path.exists(dummy_file):
            os.remove(dummy_file)
    except Exception:
        pass

@bot.command()
async def dô(ctx):
    if not ctx.author.voice:
        if not ctx.guild.voice_client:
            await ctx.send("Dô đây rồi tao dô")
        return

    channel = ctx.author.voice.channel
    tts_channels[ctx.guild.id] = ctx.channel.id
    last_speakers[ctx.guild.id] = None
    
    clear_queue(ctx.guild.id)

    data, gid = get_guild_data(ctx.guild.id)
    current_prefix = data[gid]["prefix"]
    instructions = f"Botdam đã xuất hiện\n`{current_prefix} [gì đó]` để đọc\n`!cú` nếu bị ngu"

    voice_client = ctx.guild.voice_client

    if not voice_client:
        await ctx.send(instructions)
        await ctx.send("https://tenor.com/view/peepo-arrive-pepe-gif-18118119")
        try:
            await channel.connect(timeout=20.0)
        except asyncio.TimeoutError:
            return await ctx.send("Đụ má Discord lag quá đéo connect được, gõ lại lệnh đi!")
        except Exception as e:
            return await ctx.send(f"Lỗi đéo dô được: {e}")

        if ctx.guild.id not in tts_queues:
            tts_queues[ctx.guild.id] = asyncio.Queue()
            bot.loop.create_task(tts_worker(ctx.guild.id))
    else:
        if voice_client.channel != channel:
            await voice_client.move_to(channel)
        await ctx.send(f"Đã đổi channel\n{instructions}")

    warmup_payload = {
        "text": "ハローエブリニャン",
        "lang": "ja",
        "voice_id": None,
        "msg_id": "warmup_gtts",
        "base_msg_id": "warmup_msg",
        "volume": 0.5,
        "metrics": {"t0_received": time.time(), "t1_processed": time.time()}
    }
    push_to_queue(ctx.guild.id, warmup_payload)
    
@bot.command()
async def cú(ctx):
    data, gid = get_guild_data(ctx.guild.id)
    current_prefix = data[gid]["prefix"]
    instructions = (
        f"{ctx.author.mention} bị ngu\n`{current_prefix} [gì đó]` để đọc\n"
        "`!cút` để đá đít\n"
        "`!tiếng [code]` đổi ngôn ngữ\n"
        "`!prefix[txt]` để sửa prefix\n"
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
    base_msg_id = current_playing.get(gid)
    if base_msg_id:
        cancelled_msgs.add(base_msg_id)
    if ctx.guild.voice_client and ctx.guild.voice_client.is_playing():
        ctx.guild.voice_client.stop()
        
    reacted = False
    if base_msg_id:
        try:
            target_channel_id = tts_channels.get(gid, ctx.channel.id)
            target_channel = bot.get_channel(target_channel_id) or ctx.channel
            original_message = await target_channel.fetch_message(int(base_msg_id))
            
            await original_message.add_reaction("<:suyt:1388876103703203972>")
            await original_message.add_reaction("ℹ️")
            await original_message.add_reaction("Ⓜ️")
            reacted = True
        except Exception:
            pass

    if not reacted:
        try:
            await ctx.message.add_reaction("<:suyt:1388876103703203972>")
            await ctx.message.add_reaction("ℹ️")
            await ctx.message.add_reaction("Ⓜ️")
        except Exception:
            pass
            
    await ctx.send("nói nhiều quá coi chừng bị bịt miệng")

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
        lang_name = LANGUAGES_VI.get(current_lang.lower(), current_lang)
        msg = f"{ctx.author.mention} đang sủa {lang_name}"
        return await ctx.send(msg)
        
    lang_code = lang_code.lower()
    if lang_code not in LANGUAGES_VI:
        return await ctx.send("sai code rồi mẹ mày")
        
    data[gid]["languages"][str(ctx.author.id)] = lang_code
    await save_data_async()
    lang_name = LANGUAGES_VI.get(lang_code, lang_code)
    await ctx.send(f"{ctx.author.mention} từ giờ sẽ sủa {lang_name}")

@bot.command()
async def dsgiọng(ctx):
    await ctx.send("chậm quá vứt rồi")

@bot.command()
async def giọng(ctx, index: str):
    await ctx.send("chậm quá vứt rồi")

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
        data[gid]["muted"] =[]
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
        t0_received = time.time()
        msg_content = msg_content[len(req_prefix):].strip()
    else:
        return

    if not msg_content:
        return

    volume = 1.0
    vol_match = re.search(r'-v\s+([0-9]*\.?[0-9]+)', msg_content)
    if vol_match:
        try: volume = float(vol_match.group(1))
        except ValueError: pass
        msg_content = re.sub(r'-v\s+[0-9]*\.?[0-9]+', '', msg_content)

    speed = 1.0
    spd_match = re.search(r'-s\s+([0-9]*\.?[0-9]+)', msg_content)
    if spd_match:
        try: speed = float(spd_match.group(1))
        except ValueError: pass
        msg_content = re.sub(r'-s\s+[0-9]*\.?[0-9]+', '', msg_content)

    msg_content = msg_content.strip()
    if not msg_content:
        return

    display_name = data[gid]["nicknames"].get(str(message.author.id), message.author.display_name)
    if data[gid]["announce"]:
        if last_speakers.get(message.guild.id) != message.author.id:
            text_to_read = f"{display_name} {msg_content}"
        else:
            text_to_read = msg_content
    else:
        text_to_read = msg_content

    last_speakers[message.guild.id] = message.author.id

    lang_code = data[gid]["languages"].get(str(message.author.id), 'vi')
    voice_id = data[gid]["vieneu_voices"].get(str(message.author.id), None)

    chunks = split_text_for_tts(text_to_read, max_words=25)
    
    for i, chunk in enumerate(chunks):
        t1_processed = time.time()
        
        payload = {
            "text": chunk,
            "lang": lang_code,
            "voice_id": voice_id,
            "msg_id": f"{message.id}_{i}",
            "base_msg_id": str(message.id),
            "volume": volume,
            "speed": speed,
            "metrics": {
                "t0_received": t0_received,
                "t1_processed": t1_processed
            }
        }
        push_to_queue(message.guild.id, payload)

bot.run(os.environ["DISCORD_TOKEN_1"])
