import asyncio
import re
import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import yt_dlp
import instaloader
from pathlib import Path
import tempfile
import shutil

# تنظیمات لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# توکن بات از متغیر محیطی
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8000))

class MediaBot:
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
        
    async def download_instagram_reel(self, url: str) -> str:
        """دانلود ریلز اینستاگرام"""
        try:
            # استفاده از yt-dlp برای اینستاگرام
            ydl_opts = {
                'format': 'best',
                'outtmpl': os.path.join(self.temp_dir, 'instagram_%(id)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'instagram': {
                        'comment_count': 0,
                        'like_count': 0,
                    }
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=True)
                    video_id = info['id']
                    ext = info.get('ext', 'mp4')
                    video_path = os.path.join(self.temp_dir, f"instagram_{video_id}.{ext}")
                    
                    if os.path.exists(video_path):
                        return video_path
                except Exception as e:
                    logger.error(f"خطا در دانلود با yt-dlp: {e}")
                    # اگر yt-dlp کار نکرد، از instaloader استفاده کن
                    return await self.download_instagram_fallback(url)
            
            return None
            
        except Exception as e:
            logger.error(f"خطا در دانلود ریلز اینستاگرام: {e}")
            return None
    
    async def download_instagram_fallback(self, url: str) -> str:
        """روش جایگزین برای دانلود اینستاگرام"""
        try:
            L = instaloader.Instaloader(
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            # استخراج shortcode از URL
            shortcode = url.split('/')[-2] if url.endswith('/') else url.split('/')[-1]
            if '?' in shortcode:
                shortcode = shortcode.split('?')[0]
            
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            
            # دانلود ویدیو
            video_path = os.path.join(self.temp_dir, f"{shortcode}.mp4")
            L.download_post(post, target=self.temp_dir)
            
            # یافتن فایل دانلود شده
            for file in os.listdir(self.temp_dir):
                if file.endswith('.mp4') and shortcode in file:
                    old_path = os.path.join(self.temp_dir, file)
                    shutil.move(old_path, video_path)
                    return video_path
            
            return None
            
        except Exception as e:
            logger.error(f"خطا در fallback method: {e}")
            return None
    
    async def download_youtube_short(self, url: str) -> str:
        """دانلود شورت یوتوب"""
        try:
            ydl_opts = {
                'format': 'best[height<=720]/best',
                'outtmpl': os.path.join(self.temp_dir, 'youtube_%(id)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_id = info['id']
                ext = info.get('ext', 'mp4')
                video_path = os.path.join(self.temp_dir, f"youtube_{video_id}.{ext}")
                
                if os.path.exists(video_path):
                    return video_path
                    
                # اگر فایل با نام دیگری ذخیره شده باشد
                for file in os.listdir(self.temp_dir):
                    if video_id in file and file.startswith('youtube_'):
                        return os.path.join(self.temp_dir, file)
                
            return None
            
        except Exception as e:
            logger.error(f"خطا در دانلود شورت یوتوب: {e}")
            return None
    
    def detect_url_type(self, text: str) -> tuple:
        """تشخیص نوع URL"""
        instagram_patterns = [
            r'https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?',
            r'https?://(?:www\.)?instagram\.com/p/[A-Za-z0-9_-]+/?'
        ]
        
        youtube_patterns = [
            r'https?://(?:www\.)?youtube\.com/shorts/[A-Za-z0-9_-]+',
            r'https?://youtu\.be/[A-Za-z0-9_-]+',
            r'https?://(?:www\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]+'
        ]
        
        for pattern in instagram_patterns:
            match = re.search(pattern, text)
            if match:
                return 'instagram', match.group()
        
        for pattern in youtube_patterns:
            match = re.search(pattern, text)
            if match:
                return 'youtube', match.group()
        
        return None, None
    
    def cleanup_temp_files(self):
        """پاکسازی فایل‌های موقت"""
        try:
            for file in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        except Exception as e:
            logger.error(f"خطا در پاکسازی فایل‌های موقت: {e}")

# ایجاد نمونه از بات
media_bot = MediaBot()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های دریافتی"""
    message = update.message
    
    if not message or not message.text:
        return
    
    # تشخیص نوع URL
    url_type, url = media_bot.detect_url_type(message.text)
    
    if not url_type:
        return  # اگر لینک مناسب نیست، کاری انجام نمی‌دهد
    
    # ارسال پیام در حال پردازش
    processing_msg = await message.reply_text("🔄 در حال دانلود و پردازش...")
    
    try:
        video_path = None
        
        if url_type == 'instagram':
            logger.info(f"دانلود ریلز اینستاگرام: {url}")
            video_path = await media_bot.download_instagram_reel(url)
        elif url_type == 'youtube':
            logger.info(f"دانلود شورت یوتوب: {url}")
            video_path = await media_bot.download_youtube_short(url)
        
        if video_path and os.path.exists(video_path):
            # بررسی سایز فایل (حداکثر 50MB برای تلگرام)
            file_size = os.path.getsize(video_path)
            logger.info(f"حجم فایل: {file_size / (1024*1024):.2f} MB")
            
            if file_size > 50 * 1024 * 1024:  # 50MB
                await processing_msg.edit_text("❌ حجم فایل بیش از حد مجاز است (حداکثر 50MB)")
                return
            
            # ارسال ویدیو
            with open(video_path, 'rb') as video_file:
                await message.reply_video(
                    video=video_file,
                    caption=f"📹 دانلود شده از: {url_type.title()}\n🔗 لینک اصلی: {url}",
                    supports_streaming=True
                )
            
            # حذف پیام پردازش
            await processing_msg.delete()
            
            # پاکسازی فایل دانلود شده
            os.remove(video_path)
            logger.info("فایل با موفقیت ارسال و پاک شد")
            
        else:
            error_msg = f"❌ خطا در دانلود ویدیو از {url_type}.\n"
            error_msg += "احتمالاً ویدیو private است یا لینک اشتباه است."
            await processing_msg.edit_text(error_msg)
            logger.error(f"دانلود ناموفق: {url}")
    
    except Exception as e:
        logger.error(f"خطا در پردازش پیام: {e}")
        await processing_msg.edit_text(f"❌ خطا در پردازش درخواست: {str(e)}")
    
    finally:
        # پاکسازی فایل‌های موقت
        media_bot.cleanup_temp_files()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت خطاها"""
    logger.error(f"خطا: {context.error}")

def main():
    """اجرای اصلی بات"""
    if not BOT_TOKEN:
        print("❌ لطفاً توکن بات را در متغیر محیطی BOT_TOKEN قرار دهید")
        return
    
    # ایجاد application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # اضافه کردن handler برای پیام‌های متنی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # اضافه کردن error handler
    application.add_error_handler(error_handler)
    
    print("🤖 بات شروع به کار کرد...")
    print("📱 بات را به گروه اضافه کنید و لینک ریلز یا شورت ارسال کنید")
    
    # اجرای بات
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
