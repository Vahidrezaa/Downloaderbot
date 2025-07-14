import os
import re
import logging
import requests
import yt_dlp
import spotipy
import instaloader
from spotipy.oauth2 import SpotifyClientCredentials
from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaAudio
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from threading import Thread
from urllib.parse import urlparse

# تنظیمات پایه
TOKEN = "TOKEN_BOT"
MAX_FILE_SIZE = 400  # مگابایت
MAX_SPOTIFY_TRACKS = 10  # حداکثر تعداد آهنگ برای پلی‌لیست/آلبوم
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

# Spotify API
SPOTIFY_CLIENT_ID = 'YOUR_SPOTIFY_CLIENT_ID'
SPOTIFY_CLIENT_SECRET = 'YOUR_SPOTIFY_CLIENT_SECRET'

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

def is_platform_supported(url):
    for pattern in SUPPORTED_PLATFORMS:
        if re.match(pattern, url):
            return True
    return False

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        '🤖 ربات فعال شد!\n'
        'لینک پست از پلتفرم‌های زیر را ارسال کنید:\n'
        '• Instagram • YouTube • TikTok • Facebook\n'
        '• Twitter/X • Spotify • RadioJavan • Pinterest • SoundCloud'
    )

def handle_message(update: Update, context: CallbackContext):
    message = update.message
    text = message.text.strip()
    
    if not is_platform_supported(text):
        message.reply_text('⚠️ پلتفرم مورد نظر پشتیبانی نمی‌شود!')
        return
    
    try:
        if 'instagram.com' in text:
            Thread(target=handle_instagram, args=(text, message)).start()
        elif 'spotify.com' in text:
            Thread(target=handle_spotify, args=(text, message)).start()
        else:
            Thread(target=handle_general, args=(text, message)).start()
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        message.reply_text(f'❌ خطا در پردازش: {str(e)}')

def handle_instagram(url: str, message):
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
                    url = node.video_url
                else:
                    media_type = 'photo'
                    url = node.display_url
                    
                media_list.append((media_type, url))
        else:
            if post.is_video:
                media_list.append(('video', post.video_url))
            else:
                media_list.append(('photo', post.url))
        
        send_media_group(media_list, message, f"📸 Instagram\n{post.caption[:1000] if post.caption else ''}")
    except Exception as e:
        logger.error(f"Instagram Error: {e}")
        message.reply_text(f'❌ خطای اینستاگرام: {str(e)}')

def handle_spotify(url: str, message):
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.split('/')
        
        if 'track' in path_parts:
            # پردازش تک آهنگ
            track_id = path_parts[-1]
            track = sp.track(track_id)
            query = f"{track['name']} {track['artists'][0]['name']}"
            download_and_send_audio(query, message)
            
        elif 'playlist' in path_parts:
            # پردازش پلی‌لیست
            playlist_id = path_parts[-1]
            results = sp.playlist_tracks(playlist_id)
            tracks = results['items']
            
            message.reply_text(f"🔊 در حال دریافت {min(len(tracks), MAX_SPOTIFY_TRACKS)} آهنگ از پلی‌لیست...")
            
            for i, item in enumerate(tracks[:MAX_SPOTIFY_TRACKS]):
                track = item['track']
                query = f"{track['name']} {track['artists'][0]['name']}"
                download_and_send_audio(query, message, track['name'], track['artists'][0]['name'])
                
        elif 'album' in path_parts:
            # پردازش آلبوم
            album_id = path_parts[-1]
            album = sp.album(album_id)
            tracks = album['tracks']['items']
            
            message.reply_text(f"🎵 در حال دریافت {min(len(tracks), MAX_SPOTIFY_TRACKS)} آهنگ از آلبوم {album['name']}...")
            
            for i, track in enumerate(tracks[:MAX_SPOTIFY_TRACKS]):
                query = f"{track['name']} {album['artists'][0]['name']}"
                download_and_send_audio(query, message, track['name'], album['artists'][0]['name'])
                
        else:
            message.reply_text("⚠️ نوع لینک اسپاتیفای پشتیبانی نمی‌شود (فقط ترک، آلبوم، پلی‌لیست)")
            
    except Exception as e:
        logger.error(f"Spotify Error: {e}")
        message.reply_text(f'❌ خطای اسپاتیفای: {str(e)}')

def download_and_send_audio(query: str, message, title=None, artist=None):
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
            
            # تنظیم عنوان و هنرمند در صورت عدم وجود
            title = title or entry.get('title', 'Spotify Track')
            artist = artist or entry.get('uploader', 'Unknown Artist')
            
            message.reply_audio(
                audio=open(filename, 'rb'),
                title=title[:64],
                performer=artist[:64],
                duration=entry.get('duration')
            )
            os.remove(filename)
            
    except Exception as e:
        logger.error(f"Spotify Download Error: {e}")
        message.reply_text(f'❌ خطا در دانلود آهنگ: {str(e)}')

def handle_general(url: str, message):
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
            
            # برای محتوای چندرسانه‌ای
            if 'entries' in info:
                media_list = []
                for entry in info['entries']:
                    if 'url' in entry:
                        media_list.append(('video', entry['url']))
                    elif 'thumbnail' in entry:
                        media_list.append(('photo', entry['thumbnail']))
                
                if media_list:
                    send_media_group(media_list, message, info.get('title', ''))
                    return
            
            # برای محتوای تک‌رسانه‌ای
            filename = ydl.prepare_filename(info)
            ydl.process_info(info)
            
            if info.get('ext') == 'mp4':
                message.reply_video(
                    video=open(filename, 'rb'),
                    caption=info.get('title', ''),
                    supports_streaming=True
                )
            elif info.get('ext') in ['mp3', 'm4a']:
                message.reply_audio(
                    audio=open(filename, 'rb'),
                    title=info.get('title', ''),
                    performer=info.get('uploader', 'Unknown Artist')
                )
            else:
                message.reply_document(
                    document=open(filename, 'rb'),
                    caption=info.get('title', '')
                )
            
            os.remove(filename)
            
    except Exception as e:
        logger.error(f"General Platform Error: {e}")
        message.reply_text(f'❌ خطا در پردازش لینک: {str(e)}')

def send_media_group(media_list, message, caption=None):
    MAX_MEDIA_PER_GROUP = 10
    media_groups = []
    current_group = []
    
    for idx, (media_type, url) in enumerate(media_list):
        try:
            # دانلود موقت
            temp_file = f"temp_{message.message_id}_{idx}.{media_type}"
            with requests.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(temp_file, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
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
            
            # اضافه کردن کپشن فقط برای اولین مدیا
            if idx == 0 and caption:
                media.caption = caption[:1024]
            
            current_group.append(media)
            
            # اگر گروه پر شد یا آخرین مدیا است
            if len(current_group) >= MAX_MEDIA_PER_GROUP or idx == len(media_list)-1:
                media_groups.append(current_group)
                current_group = []
        
        except Exception as e:
            logger.error(f"Media Processing Error: {str(e)}")
            continue
    
    # ارسال گروه‌ها
    for group in media_groups:
        message.reply_media_group(media=group)
    
    # پاکسازی فایل‌های موقت
    for idx in range(len(media_list)):
        for ext in ['photo', 'video', 'audio']:
            temp_file = f"temp_{message.message_id}_{idx}.{ext}"
            if os.path.exists(temp_file):
                os.remove(temp_file)

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    logger.info("✅ Bot started and polling...")
    updater.idle()

if __name__ == '__main__':
    main()