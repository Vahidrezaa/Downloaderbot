import os
import re
import logging
import requests
import yt_dlp
import spotipy
import instaloader
import asyncio
import tempfile
import json
from contextlib import contextmanager
from urllib.parse import urlparse, unquote
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

# تنظیمات پایه
def get_required_env(key, default=None):
    value = os.environ.get(key, default)
    if value is None:
        raise ValueError(f"متغیر محیطی {key} تنظیم نشده است!")
    return value

# بررسی تنظیمات
try:
    TOKEN = get_required_env('TOKEN')
    SPOTIFY_CLIENT_ID = get_required_env('SPOTIFY_CLIENT_ID')
    SPOTIFY_CLIENT_SECRET = get_required_env('SPOTIFY_CLIENT_SECRET')
    WEBHOOK_URL = get_required_env('WEBHOOK_URL')
except ValueError as e:
    logging.error(f"خطای تنظیمات: {e}")
    exit(1)

MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', '45'))
MAX_SPOTIFY_TRACKS = int(os.environ.get('MAX_SPOTIFY_TRACKS', '3'))
PORT = int(os.environ.get('PORT', '8443'))

# لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Spotify Auth
try:
    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    ))
except Exception as e:
    logger.error(f"خطای اتصال به Spotify: {e}")
    sp = None

# پترن‌های URL بهبود یافته
URL_PATTERNS = {
    'instagram': [
        r'https?://(?:www\.)?instagram\.com/(?:p|reel)/([^/?]+)',
        r'https?://(?:www\.)?instagram\.com/stories/[^/]+/(\d+)',
    ],
    'youtube': [
        r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([^&\n?#]+)',
        r'https?://(?:www\.)?youtube\.com/shorts/([^&\n?#]+)',
    ],
    'spotify': [
        r'https?://open\.spotify\.com/(track|playlist|album)/([^?]+)',
    ],
    'twitter': [
        r'https?://(?:www\.)?(?:twitter\.com|x\.com)/\w+/status/(\d+)',
    ],
    'tiktok': [
        r'https?://(?:www\.)?tiktok\.com/@[^/]+/video/(\d+)',
        r'https?://(?:vm|vt)\.tiktok\.com/([^/]+)',
    ],
    'pinterest': [
        r'https?://(?:www\.)?pinterest\.com/pin/(\d+)',
        r'https?://pin\.it/([^/]+)',
    ],
    'soundcloud': [
        r'https?://soundcloud\.com/[^/]+/[^/]+',
        r'https?://on\.soundcloud\.com/([^/]+)',
    ],
    'facebook': [
        r'https?://(?:www\.)?facebook\.com/[^/]+/(?:posts|videos)/(\d+)',
    ]
}

@contextmanager
def safe_file_handler(filepath):
    """مدیریت ایمن فایل‌ها"""
    file_obj = None
    try:
        if os.path.exists(filepath):
            file_obj = open(filepath, 'rb')
            yield file_obj
        else:
            yield None
    finally:
        if file_obj:
            file_obj.close()
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass

def detect_platform(url):
    """شناسایی پلتفرم با regex بهبود یافته"""
    for platform, patterns in URL_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return platform
    return None

def extract_url_from_text(text):
    """استخراج URL از متن"""
    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, text)
    return urls[0] if urls else None

def is_group_chat(update: Update) -> bool:
    """بررسی اینکه پیام در گروه است یا نه"""
    return update.message.chat.type in ['group', 'supergroup']

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start"""
    await update.message.reply_text(
        '🤖 ربات دانلود رسانه فعال شد!\n\n'
        '🔗 پلتفرم‌های پشتیبانی شده:\n'
        '• Instagram (پست‌ها و ریل‌ها)\n'
        '• YouTube (ویدیوها و شورت‌ها)\n'
        '• Spotify (آهنگ‌ها و پلی‌لیست‌ها)\n'
        '• Twitter/X (تصاویر و ویدیوها)\n'
        '• TikTok • Pinterest • SoundCloud • Facebook\n\n'
        f'📊 حداکثر حجم: {MAX_FILE_SIZE} مگابایت\n'
        '💡 کافیست لینک را ارسال کنید!'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌ها"""
    message = update.message
    text = message.text.strip()
    
    # در گروه فقط لینک‌ها را پردازش کن
    if is_group_chat(update):
        url = extract_url_from_text(text)
        if not url:
            return  # هیچ واکنشی نده
    else:
        # در چت خصوصی
        if not text.startswith(('http://', 'https://')):
            await message.reply_text('⚠️ لطفاً لینک معتبر ارسال کنید!')
            return
        url = text
    
    platform = detect_platform(url)
    if not platform:
        await message.reply_text('⚠️ پلتفرم مورد نظر پشتیبانی نمی‌شود!')
        return
    
    # نمایش پیام پردازش
    processing_msg = await message.reply_text(f'⏳ در حال پردازش {platform}...')
    
    try:
        if platform == 'instagram':
            await handle_instagram(url, message, processing_msg)
        elif platform == 'spotify':
            await handle_spotify(url, message, processing_msg)
        elif platform == 'pinterest':
            await handle_pinterest(url, message, processing_msg)
        elif platform == 'soundcloud':
            await handle_soundcloud(url, message, processing_msg)
        elif platform == 'twitter':
            await handle_twitter(url, message, processing_msg)
        else:
            await handle_general(url, message, processing_msg, platform)
    except Exception as e:
        logger.error(f"Error processing {url}: {str(e)}")
        await processing_msg.edit_text(f'❌ خطا در پردازش: {str(e)}')

async def handle_instagram(url: str, message, processing_msg):
    """پردازش اینستاگرام با روش بهبود یافته"""
    try:
        # استفاده از yt-dlp برای اینستاگرام
        ydl_opts = {
            'format': 'best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'max_filesize': MAX_FILE_SIZE * 1024 * 1024,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise Exception("اطلاعات پست دریافت نشد")
            
            await processing_msg.edit_text('📥 دانلود از اینستاگرام...')
            
            # دانلود فایل
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
                temp_path = temp_file.name
            
            ydl_opts['outtmpl'] = temp_path
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # تشخیص نوع فایل و ارسال
            if os.path.exists(temp_path):
                file_size = os.path.getsize(temp_path)
                caption = f"📸 Instagram\n{info.get('description', '')[:300]}"
                
                with safe_file_handler(temp_path) as media_file:
                    if media_file:
                        if file_size > 50 * 1024 * 1024:
                            await message.reply_document(
                                document=media_file,
                                caption=caption
                            )
                        else:
                            # تشخیص نوع بر اساس محتوا
                            if 'video' in info.get('format', '').lower():
                                await message.reply_video(
                                    video=media_file,
                                    caption=caption
                                )
                            else:
                                await message.reply_photo(
                                    photo=media_file,
                                    caption=caption
                                )
            
            await processing_msg.delete()
            
    except Exception as e:
        logger.error(f"Instagram Error: {e}")
        await processing_msg.edit_text(f'❌ خطای اینستاگرام: {str(e)}')

async def handle_spotify(url: str, message, processing_msg):
    """پردازش اسپاتیفای"""
    if not sp:
        await processing_msg.edit_text('❌ سرویس اسپاتیفای در دسترس نیست!')
        return
    
    try:
        # استخراج ID از URL
        match = re.search(r'https?://open\.spotify\.com/(track|playlist|album)/([^?]+)', url)
        if not match:
            await processing_msg.edit_text('❌ لینک اسپاتیفای معتبر نیست!')
            return
        
        content_type, content_id = match.groups()
        
        if content_type == 'track':
            track = sp.track(content_id)
            query = f"{track['name']} {track['artists'][0]['name']}"
            
            await processing_msg.edit_text('🎵 جستجو و دانلود آهنگ...')
            await download_and_send_audio(query, message, track['name'], track['artists'][0]['name'])
            await processing_msg.delete()
            
        elif content_type == 'playlist':
            playlist = sp.playlist(content_id)
            tracks = sp.playlist_tracks(content_id, limit=MAX_SPOTIFY_TRACKS)['items']
            
            await processing_msg.edit_text(f"🎵 دانلود {len(tracks)} آهنگ از پلی‌لیست...")
            
            for i, item in enumerate(tracks):
                if not item['track']:
                    continue
                    
                track = item['track']
                query = f"{track['name']} {track['artists'][0]['name']}"
                
                await processing_msg.edit_text(f"🎵 آهنگ {i+1}/{len(tracks)}: {track['name'][:30]}...")
                await download_and_send_audio(query, message, track['name'], track['artists'][0]['name'])
                await asyncio.sleep(2)  # کمی تاخیر
                
            await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"Spotify Error: {e}")
        await processing_msg.edit_text(f'❌ خطای اسپاتیفای: {str(e)}')

async def handle_pinterest(url: str, message, processing_msg):
    """پردازش پینترست"""
    try:
        # رفع مشکل لینک‌های کوتاه
        if 'pin.it' in url:
            # دنبال کردن redirect
            response = requests.head(url, allow_redirects=True, timeout=10)
            url = response.url
        
        await processing_msg.edit_text('📌 دانلود از پینترست...')
        
        # استفاده از requests برای دانلود مستقیم تصاویر
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # استخراج ID پین
        pin_match = re.search(r'/pin/(\d+)', url)
        if not pin_match:
            raise Exception("لینک پینترست معتبر نیست")
        
        pin_id = pin_match.group(1)
        
        # API غیررسمی پینترست
        api_url = f"https://www.pinterest.com/resource/PinResource/get/?source_url=%2Fpin%2F{pin_id}%2F&data=%7B%22options%22%3A%7B%22field_set_key%22%3A%22detailed%22%2C%22id%22%3A%22{pin_id}%22%7D%2C%22context%22%3A%7B%7D%7D"
        
        response = requests.get(api_url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            pin_data = data.get('resource_response', {}).get('data', {})
            
            if pin_data:
                image_url = pin_data.get('images', {}).get('orig', {}).get('url')
                description = pin_data.get('description', 'Pinterest Image')
                
                if image_url:
                    # دانلود تصویر
                    img_response = requests.get(image_url, headers=headers, timeout=30)
                    img_response.raise_for_status()
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
                        temp_file.write(img_response.content)
                        temp_path = temp_file.name
                    
                    with safe_file_handler(temp_path) as photo_file:
                        if photo_file:
                            await message.reply_photo(
                                photo=photo_file,
                                caption=f"📌 Pinterest\n{description[:300]}"
                            )
                    
                    await processing_msg.delete()
                    return
        
        raise Exception("تصویر پینترست یافت نشد")
        
    except Exception as e:
        logger.error(f"Pinterest Error: {e}")
        await processing_msg.edit_text(f'❌ خطای پینترست: {str(e)}')

async def handle_soundcloud(url: str, message, processing_msg):
    """پردازش ساوندکلاود"""
    try:
        # رفع مشکل لینک‌های کوتاه
        if 'on.soundcloud.com' in url:
            response = requests.head(url, allow_redirects=True, timeout=10)
            url = response.url
        
        await processing_msg.edit_text('🎵 دانلود از ساوندکلاود...')
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'max_filesize': MAX_FILE_SIZE * 1024 * 1024,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise Exception("اطلاعات آهنگ دریافت نشد")
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
                temp_path = temp_file.name
            
            ydl_opts['outtmpl'] = temp_path
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            with safe_file_handler(temp_path) as audio_file:
                if audio_file:
                    await message.reply_audio(
                        audio=audio_file,
                        title=info.get('title', 'SoundCloud Track')[:64],
                        performer=info.get('uploader', 'Unknown')[:64],
                        duration=info.get('duration')
                    )
            
            await processing_msg.delete()
            
    except Exception as e:
        logger.error(f"SoundCloud Error: {e}")
        await processing_msg.edit_text(f'❌ خطای ساوندکلاود: {str(e)}')

async def handle_twitter(url: str, message, processing_msg):
    """پردازش توییتر/X"""
    try:
        await processing_msg.edit_text('🐦 دانلود از Twitter/X...')
        
        ydl_opts = {
            'format': 'best',
            'max_filesize': MAX_FILE_SIZE * 1024 * 1024,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise Exception("محتوای توییت دریافت نشد")
            
            # بررسی وجود رسانه
            if 'entries' in info:
                entries = info['entries']
                if not entries:
                    raise Exception("هیچ رسانه‌ای در توییت یافت نشد")
                
                for entry in entries:
                    await download_twitter_media(entry, message)
            else:
                await download_twitter_media(info, message)
            
            await processing_msg.delete()
            
    except Exception as e:
        logger.error(f"Twitter Error: {e}")
        await processing_msg.edit_text(f'❌ خطای Twitter: {str(e)}')

async def download_twitter_media(info, message):
    """دانلود رسانه از توییتر"""
    try:
        url = info.get('url')
        if not url:
            return
        
        # دانلود فایل
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = temp_file.name
        
        ydl_opts = {
            'outtmpl': temp_path,
            'format': 'best',
            'quiet': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            caption = f"🐦 Twitter\n{info.get('title', '')[:300]}"
            
            with safe_file_handler(temp_path) as media_file:
                if media_file:
                    if 'video' in info.get('format', '').lower():
                        await message.reply_video(
                            video=media_file,
                            caption=caption
                        )
                    else:
                        await message.reply_photo(
                            photo=media_file,
                            caption=caption
                        )
        
    except Exception as e:
        logger.error(f"Twitter Media Download Error: {e}")

async def download_and_send_audio(query: str, message, title=None, artist=None):
    """دانلود و ارسال آهنگ"""
    try:
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best',
            'default_search': f"ytsearch1:{query}",
            'max_filesize': MAX_FILE_SIZE * 1024 * 1024,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            
            if not info or 'entries' not in info or not info['entries']:
                raise Exception("آهنگ پیدا نشد")
            
            entry = info['entries'][0]
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.m4a') as temp_file:
                temp_path = temp_file.name
            
            ydl_opts['outtmpl'] = temp_path
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([entry['webpage_url']])
            
            with safe_file_handler(temp_path) as audio_file:
                if audio_file:
                    await message.reply_audio(
                        audio=audio_file,
                        title=(title or entry.get('title', 'Unknown'))[:64],
                        performer=(artist or entry.get('uploader', 'Unknown'))[:64],
                        duration=entry.get('duration')
                    )
            
    except Exception as e:
        logger.error(f"Audio Download Error: {e}")
        raise Exception(f"خطا در دانلود آهنگ: {str(e)}")

async def handle_general(url: str, message, processing_msg, platform):
    """پردازش سایر پلتفرم‌ها"""
    try:
        await processing_msg.edit_text(f'📥 دانلود از {platform}...')
        
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'max_filesize': MAX_FILE_SIZE * 1024 * 1024,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise Exception("اطلاعات محتوا دریافت نشد")
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
                temp_path = temp_file.name
            
            ydl_opts['outtmpl'] = temp_path
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            await processing_msg.edit_text('📤 ارسال فایل...')
            
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                file_size = os.path.getsize(temp_path)
                caption = f"📱 {platform.title()}\n{info.get('title', 'Downloaded Media')[:300]}"
                
                with safe_file_handler(temp_path) as media_file:
                    if media_file:
                        if file_size > 50 * 1024 * 1024:
                            await message.reply_document(
                                document=media_file,
                                caption=caption
                            )
                        else:
                            await message.reply_video(
                                video=media_file,
                                caption=caption,
                                supports_streaming=True
                            )
            
            await processing_msg.delete()
            
    except Exception as e:
        logger.error(f"General Platform Error: {e}")
        await processing_msg.edit_text(f'❌ خطا در پردازش: {str(e)}')

def main():
    """تابع اصلی"""
    try:
        application = Application.builder().token(TOKEN).build()

        # ثبت هندلرها
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("🤖 ربات آماده است...")
        
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
