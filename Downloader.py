import os
import re
import logging
import requests
import yt_dlp
import spotipy
import instaloader
import asyncio
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

# تنظیمات پایه
TOKEN = os.environ.get('TOKEN')
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET')
MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 400))  # مگابایت
MAX_SPOTIFY_TRACKS = int(os.environ.get('MAX_SPOTIFY_TRACKS', 10))

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Spotify Auth
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

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
        '• Twitter/X • Spotify • RadioJavan • Pinterest • SoundCloud'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های کاربر"""
    message = update.message
    text = message.text.strip()
    
    if not is_platform_supported(text):
        await message.reply_text('⚠️ پلتفرم مورد نظر پشتیبانی نمی‌شود!')
        return
    
    try:
        if 'instagram.com' in text:
            await handle_instagram(text, message)
        elif 'spotify.com' in text:
            await handle_spotify(text, message)
        else:
            await handle_general(text, message)
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await message.reply_text(f'❌ خطا در پردازش: {str(e)}')

async def handle_instagram(url: str, message):
    """پردازش لینک اینستاگرام"""
    try:
        loader = instaloader.Instaloader(
            download_pictures=True,
            download_videos=True,
            download_video_thumbnails=False,
            compress_json=False
        )
        
        shortcode = url.split('/')[-2]
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
        
        media_list = []
        
        if post.mediacount > 1:
            for idx, node in enumerate(post.get_sidecar_nodes()):
                if node.is_video:
                    media_type = 'video'
                    media_url = node.video_url
                else:
                    media_type = 'photo'
                    media_url = node.display_url
                    
                media_list.append((media_type, media_url))
        else:
            if post.is_video:
                media_list.append(('video', post.video_url))
            else:
                media_list.append(('photo', post.url))
        
        await send_media_group(media_list, message, f"📸 Instagram\n{post.caption[:1000] if post.caption else ''}")
    except Exception as e:
        logger.error(f"Instagram Error: {e}")
        await message.reply_text(f'❌ خطای اینستاگرام: {str(e)}')

async def handle_spotify(url: str, message):
    """پردازش لینک اسپاتیفای"""
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.split('/')
        
        if 'track' in path_parts:
            track_id = path_parts[-1]
            track = sp.track(track_id)
            query = f"{track['name']} {track['artists'][0]['name']}"
            await download_and_send_audio(query, message, track['name'], track['artists'][0]['name'])
            
        elif 'playlist' in path_parts:
            playlist_id = path_parts[-1]
            results = sp.playlist_tracks(playlist_id)
            tracks = results['items']
            
            await message.reply_text(f"🔊 در حال دریافت {min(len(tracks), MAX_SPOTIFY_TRACKS)} آهنگ از پلی‌لیست...")
            
            for i, item in enumerate(tracks[:MAX_SPOTIFY_TRACKS]):
                track = item['track']
                query = f"{track['name']} {track['artists'][0]['name']}"
                await download_and_send_audio(query, message, track['name'], track['artists'][0]['name'])
                
        elif 'album' in path_parts:
            album_id = path_parts[-1]
            album = sp.album(album_id)
            tracks = album['tracks']['items']
            
            await message.reply_text(f"🎵 در حال دریافت {min(len(tracks), MAX_SPOTIFY_TRACKS)} آهنگ از آلبوم {album['name']}...")
            
            for i, track in enumerate(tracks[:MAX_SPOTIFY_TRACKS]):
                query = f"{track['name']} {album['artists'][0]['name']}"
                await download_and_send_audio(query, message, track['name'], album['artists'][0]['name'])
                
        else:
            await message.reply_text("⚠️ نوع لینک اسپاتیفای پشتیبانی نمی‌شود (فقط ترک، آلبوم، پلی‌لیست)")
            
    except Exception as e:
        logger.error(f"Spotify Error: {e}")
        await message.reply_text(f'❌ خطای اسپاتیفای: {str(e)}')

async def download_and_send_audio(query: str, message, title=None, artist=None):
    """دانلود و ارسال آهنگ از یوتیوب"""
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'default_search': f"ytsearch:{query}",
            'max_filesize': MAX_FILE_SIZE * 10**6,
            'noplaylist': True,
            'quiet': True,
            'outtmpl': 'spotify_audio.%(ext)s'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)
            
            if not info or 'entries' not in info or not info['entries']:
                raise Exception("هیچ نتیجه‌ای یافت نشد")
            
            entry = info['entries'][0]
            filename = ydl.prepare_filename(entry)
            ydl.process_info(entry)
            
            title = title or entry.get('title', 'Spotify Track')[:64]
            artist = artist or entry.get('uploader', 'Unknown Artist')[:64]
            
            await message.reply_audio(
                audio=open(filename, 'rb'),
                title=title,
                performer=artist,
                duration=entry.get('duration')
            )
            os.remove(filename)
            
    except Exception as e:
        logger.error(f"Spotify Download Error: {e}")
        await message.reply_text(f'❌ خطا در دانلود آهنگ: {str(e)}')

async def handle_general(url: str, message):
    """پردازش سایر پلتفرم‌ها"""
    try:
        platform_settings = {
            'youtube': {'format': 'bestvideo[height=360]+bestaudio/best[height=360]'},
            'tiktok': {'format': 'best'},
            'default': {'format': 'best'}
        }
        
        ydl_opts = {
            'max_filesize': MAX_FILE_SIZE * 10**6,
            'noplaylist': True,
            'quiet': True
        }
        
        if 'youtube.com' in url or 'youtu.be' in url:
            ydl_opts.update(platform_settings['youtube'])
        elif 'tiktok.com' in url:
            ydl_opts.update(platform_settings['tiktok'])
        else:
            ydl_opts.update(platform_settings['default'])
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if 'entries' in info:
                media_list = []
                for entry in info['entries']:
                    if 'url' in entry:
                        media_list.append(('video', entry['url']))
                    elif 'thumbnail' in entry:
                        media_list.append(('photo', entry['thumbnail']))
                
                if media_list:
                    await send_media_group(media_list, message, info.get('title', ''))
                    return
            
            filename = ydl.prepare_filename(info)
            ydl.process_info(info)
            
            if info.get('ext') == 'mp4':
                await message.reply_video(
                    video=open(filename, 'rb'),
                    caption=info.get('title', ''),
                    supports_streaming=True
                )
            elif info.get('ext') in ['mp3', 'm4a']:
                await message.reply_audio(
                    audio=open(filename, 'rb'),
                    title=info.get('title', ''),
                    performer=info.get('uploader', 'Unknown Artist')
                )
            else:
                await message.reply_document(
                    document=open(filename, 'rb'),
                    caption=info.get('title', '')
                )
            
            os.remove(filename)
            
    except Exception as e:
        logger.error(f"General Platform Error: {e}")
        await message.reply_text(f'❌ خطا در پردازش لینک: {str(e)}')

async def send_media_group(media_list, message, caption=None):
    """ارسال گروهی مدیاها"""
    MAX_MEDIA_PER_GROUP = 10
    media_groups = []
    current_group = []
    
    for idx, (media_type, url) in enumerate(media_list):
        try:
            temp_file = f"temp_{message.message_id}_{idx}.{media_type}"
            
            # دانلود محتوا
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            
            # بررسی حجم فایل
            file_size = os.path.getsize(temp_file) / (1024*1024)
            if file_size > MAX_FILE_SIZE:
                os.remove(temp_file)
                continue
            
            # ایجاد مدیا
            if media_type == 'photo':
                media = InputMediaPhoto(media=open(temp_file, 'rb'))
            elif media_type == 'video':
                media = InputMediaVideo(media=open(temp_file, 'rb'))
            else:
                media = InputMediaAudio(media=open(temp_file, 'rb'))
            
            # افزودن کپشن به اولین مدیا
            if idx == 0 and caption:
                media.caption = caption[:1024]
            
            current_group.append(media)
            
            # ارسال گروهی در صورت پر شدن گروه یا رسیدن به آخر
            if len(current_group) >= MAX_MEDIA_PER_GROUP or idx == len(media_list)-1:
                await message.reply_media_group(media=current_group)
                media_groups.append(current_group)
                current_group = []
        
        except Exception as e:
            logger.error(f"Media Processing Error: {str(e)}")
            continue
    
    # پاکسازی فایل‌های موقت
    for idx in range(len(media_list)):
        for ext in ['photo', 'video', 'audio']:
            temp_file = f"temp_{message.message_id}_{idx}.{ext}"
            if os.path.exists(temp_file):
                os.remove(temp_file)

def main():
    """تابع اصلی اجرای ربات"""
    if not TOKEN:
        logger.error("❌ توکن ربات تنظیم نشده است!")
        return
    
    # ساخت اپلیکیشن تلگرام
    application = Application.builder().token(TOKEN).build()
    
    # ثبت هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_message
    ))
    
    # شروع ربات
    logger.info("🤖 در حال راه‌اندازی ربات...")
    application.run_polling()

if __name__ == '__main__':
    main()