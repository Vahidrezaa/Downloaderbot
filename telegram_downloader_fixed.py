import os
import re
import logging
import requests
import yt_dlp
import spotipy
import instaloader
import asyncio
import tempfile
from contextlib import contextmanager
from urllib.parse import urlparse
from spotipy.oauth2 import SpotifyClientCredentials
from telegram import (
    Update,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaAudio
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# تنظیمات پایه با بررسی وجود
def get_required_env(key, default=None):
    """دریافت متغیر محیطی با بررسی وجود"""
    value = os.environ.get(key, default)
    if value is None:
        raise ValueError(f"متغیر محیطی {key} تنظیم نشده است!")
    return value

# بررسی و دریافت تنظیمات
try:
    TOKEN = get_required_env('TOKEN')
    SPOTIFY_CLIENT_ID = get_required_env('SPOTIFY_CLIENT_ID')
    SPOTIFY_CLIENT_SECRET = get_required_env('SPOTIFY_CLIENT_SECRET')
    WEBHOOK_URL = get_required_env('WEBHOOK_URL')
except ValueError as e:
    logging.error(f"خطای تنظیمات: {e}")
    exit(1)

MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', '50'))  # کاهش حجم پیش‌فرض
MAX_SPOTIFY_TRACKS = int(os.environ.get('MAX_SPOTIFY_TRACKS', '5'))  # کاهش تعداد
PORT = int(os.environ.get('PORT', '8443'))

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Spotify Auth با بررسی خطا
try:
    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    ))
except Exception as e:
    logger.error(f"خطای اتصال به Spotify: {e}")
    sp = None

# لیست پلتفرم‌های پشتیبانی شده
SUPPORTED_PLATFORMS = [
    r'(https?://)?(www\.)?instagram\.com/',
    r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/',
    r'(https?://)?(www\.)?tiktok\.com/',
    r'(https?://)?(www\.)?facebook\.com/',
    r'(https?://)?(www\.)?(twitter\.com|x\.com)/',
    r'(https?://)?(www\.)?spotify\.com/',
    r'(https?://)?(www\.)?radiojavan\.com/',
    r'(https?://)?(www\.)?pinterest\.com/',
    r'(https?://)?(www\.)?soundcloud\.com/'
]

@contextmanager
def safe_file_handler(filepath):
    """مدیریت ایمن فایل‌ها"""
    file_obj = None
    try:
        file_obj = open(filepath, 'rb')
        yield file_obj
    finally:
        if file_obj:
            file_obj.close()
        # پاک کردن فایل موقت
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass

def is_platform_supported(url):
    """بررسی پشتیبانی از پلتفرم"""
    for pattern in SUPPORTED_PLATFORMS:
        if re.match(pattern, url):
            return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start"""
    await update.message.reply_text(
        '🤖 ربات فعال شد!\n'
        'لینک پست از پلتفرم‌های زیر را ارسال کنید:\n'
        '• Instagram • YouTube • TikTok • Facebook\n'
        '• Twitter/X • Spotify • RadioJavan • Pinterest • SoundCloud\n\n'
        f'حداکثر حجم فایل: {MAX_FILE_SIZE} مگابایت'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های کاربر"""
    message = update.message
    text = message.text.strip()
    
    if not text.startswith(('http://', 'https://')):
        await message.reply_text('⚠️ لطفاً لینک معتبر ارسال کنید!')
        return
    
    if not is_platform_supported(text):
        await message.reply_text('⚠️ پلتفرم مورد نظر پشتیبانی نمی‌شود!')
        return
    
    # نمایش پیام در حال پردازش
    processing_msg = await message.reply_text('⏳ در حال پردازش...')
    
    try:
        if 'instagram.com' in text:
            await handle_instagram(text, message, processing_msg)
        elif 'spotify.com' in text:
            await handle_spotify(text, message, processing_msg)
        else:
            await handle_general(text, message, processing_msg)
    except Exception as e:
        logger.error(f"Error processing {text}: {str(e)}")
        await processing_msg.edit_text(f'❌ خطا در پردازش: {str(e)}')

async def handle_instagram(url: str, message, processing_msg):
    """پردازش لینک اینستاگرام"""
    try:
        loader = instaloader.Instaloader(
            download_pictures=True,
            download_videos=True,
            download_video_thumbnails=False,
            compress_json=False,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        # استخراج shortcode
        shortcode_match = re.search(r'/p/([^/]+)', url) or re.search(r'/reel/([^/]+)', url)
        if not shortcode_match:
            raise ValueError("لینک اینستاگرام معتبر نیست")
        
        shortcode = shortcode_match.group(1)
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
        
        media_urls = []
        
        if post.mediacount > 1:
            for node in post.get_sidecar_nodes():
                if node.is_video:
                    media_urls.append(('video', node.video_url))
                else:
                    media_urls.append(('photo', node.display_url))
        else:
            if post.is_video:
                media_urls.append(('video', post.video_url))
            else:
                media_urls.append(('photo', post.url))
        
        await processing_msg.edit_text(f'📥 دانلود {len(media_urls)} فایل...')
        
        caption = f"📸 Instagram\n{post.caption[:500] if post.caption else 'بدون توضیح'}"
        await send_media_group(media_urls, message, caption)
        await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"Instagram Error: {e}")
        await processing_msg.edit_text(f'❌ خطای اینستاگرام: {str(e)}')

async def handle_spotify(url: str, message, processing_msg):
    """پردازش لینک اسپاتیفای"""
    if not sp:
        await processing_msg.edit_text('❌ سرویس اسپاتیفای در دسترس نیست!')
        return
    
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        
        if 'track' in path_parts:
            track_id = path_parts[-1].split('?')[0]
            track = sp.track(track_id)
            query = f"{track['name']} {track['artists'][0]['name']}"
            
            await processing_msg.edit_text('🎵 دانلود آهنگ...')
            await download_and_send_audio(query, message, track['name'], track['artists'][0]['name'])
            await processing_msg.delete()
            
        elif 'playlist' in path_parts:
            playlist_id = path_parts[-1].split('?')[0]
            results = sp.playlist_tracks(playlist_id, limit=MAX_SPOTIFY_TRACKS)
            tracks = results['items']
            
            await processing_msg.edit_text(f"🔊 دانلود {len(tracks)} آهنگ از پلی‌لیست...")
            
            for i, item in enumerate(tracks):
                if not item['track']:
                    continue
                    
                track = item['track']
                query = f"{track['name']} {track['artists'][0]['name']}"
                
                await processing_msg.edit_text(f"🎵 دانلود آهنگ {i+1}/{len(tracks)}: {track['name']}")
                await download_and_send_audio(query, message, track['name'], track['artists'][0]['name'])
                
                # تاخیر برای جلوگیری از اسپم
                await asyncio.sleep(1)
                
            await processing_msg.delete()
                
        else:
            await processing_msg.edit_text("⚠️ فقط لینک‌های ترک و پلی‌لیست پشتیبانی می‌شود")
            
    except Exception as e:
        logger.error(f"Spotify Error: {e}")
        await processing_msg.edit_text(f'❌ خطای اسپاتیفای: {str(e)}')

async def download_and_send_audio(query: str, message, title=None, artist=None):
    """دانلود و ارسال آهنگ از یوتیوب"""
    try:
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'default_search': f"ytsearch1:{query}",
            'max_filesize': MAX_FILE_SIZE * 1024 * 1024,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'outtmpl': '%(title)s.%(ext)s'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            
            if not info or 'entries' not in info or not info['entries']:
                raise Exception("آهنگ پیدا نشد")
            
            entry = info['entries'][0]
            
            # دانلود در پوشه موقت
            with tempfile.NamedTemporaryFile(delete=False, suffix='.m4a') as temp_file:
                temp_path = temp_file.name
            
            ydl_opts['outtmpl'] = temp_path
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([entry['webpage_url']])
            
            # ارسال با مدیریت ایمن فایل
            with safe_file_handler(temp_path) as audio_file:
                await message.reply_audio(
                    audio=audio_file,
                    title=(title or entry.get('title', 'Unknown'))[:64],
                    performer=(artist or entry.get('uploader', 'Unknown'))[:64],
                    duration=entry.get('duration')
                )
            
    except Exception as e:
        logger.error(f"Audio Download Error: {e}")
        raise Exception(f"خطا در دانلود آهنگ: {str(e)}")

async def handle_general(url: str, message, processing_msg):
    """پردازش سایر پلتفرم‌ها"""
    try:
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'max_filesize': MAX_FILE_SIZE * 1024 * 1024,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise Exception("اطلاعات ویدیو دریافت نشد")
            
            # دانلود فایل
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
                temp_path = temp_file.name
            
            ydl_opts['outtmpl'] = temp_path
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            await processing_msg.edit_text('📤 ارسال فایل...')
            
            # ارسال فایل با مدیریت ایمن
            with safe_file_handler(temp_path) as video_file:
                file_size = os.path.getsize(temp_path)
                title = info.get('title', 'Downloaded Video')[:100]
                
                if file_size > 50 * 1024 * 1024:  # 50MB
                    await message.reply_document(
                        document=video_file,
                        caption=title
                    )
                else:
                    await message.reply_video(
                        video=video_file,
                        caption=title,
                        supports_streaming=True
                    )
            
            await processing_msg.delete()
            
    except Exception as e:
        logger.error(f"General Platform Error: {e}")
        await processing_msg.edit_text(f'❌ خطا در پردازش: {str(e)}')

async def send_media_group(media_list, message, caption=None):
    """ارسال گروهی مدیاها"""
    if not media_list:
        return
    
    MAX_MEDIA_PER_GROUP = 10
    temp_files = []
    
    try:
        for idx, (media_type, url) in enumerate(media_list[:MAX_MEDIA_PER_GROUP]):
            # دانلود فایل
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{media_type}')
            temp_files.append(temp_file.name)
            
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            with open(temp_file.name, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # بررسی حجم
            file_size = os.path.getsize(temp_file.name) / (1024 * 1024)
            if file_size > MAX_FILE_SIZE:
                continue
        
        # تشکیل گروه مدیا
        media_group = []
        for idx, temp_file in enumerate(temp_files):
            if not os.path.exists(temp_file):
                continue
                
            with open(temp_file, 'rb') as f:
                if media_list[idx][0] == 'photo':
                    media = InputMediaPhoto(media=f.read())
                else:
                    media = InputMediaVideo(media=f.read())
                    
                if idx == 0 and caption:
                    media.caption = caption[:1024]
                    
                media_group.append(media)
        
        # ارسال گروهی
        if media_group:
            await message.reply_media_group(media=media_group)
    
    except Exception as e:
        logger.error(f"Media Group Error: {e}")
        raise
    
    finally:
        # پاکسازی فایل‌های موقت
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

def main():
    """تابع اصلی"""
    try:
        # ساخت اپلیکیشن
        application = Application.builder().token(TOKEN).build()

        # ثبت هندلرها
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("🤖 ربات آماده است...")
        
        # اجرای webhook یا polling
        if WEBHOOK_URL:
            logger.info("🌐 راه‌اندازی Webhook...")
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                webhook_url=f"{WEBHOOK_URL}/{TOKEN}",
                url_path=TOKEN
            )
        else:
            logger.info("🔄 راه‌اندازی Polling...")
            application.run_polling(drop_pending_updates=True)
            
    except Exception as e:
        logger.error(f"خطای اجرای ربات: {e}")
        exit(1)

if __name__ == '__main__':
    main()