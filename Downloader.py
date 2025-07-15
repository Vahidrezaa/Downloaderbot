import re
import os
import yt_dlp as youtube_dl
from pytube import YouTube
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# تنظیمات اصلی
TOKEN = os.getenv("TELEGRAM_TOKEN")
INSTAGRAM_REGEX = r"(https?:\/\/(?:www\.)?instagram\.com\/(?:reel|reels|p)\/[^\/\?\s]+)"
YOUTUBE_REGEX = r"(https?:\/\/(?:www\.)?youtube\.com\/shorts\/[^\/\?\s]+)|(https?:\/\/youtu\.be\/[^\/\?\s]+)"

async def download_instagram_reel(url: str) -> str:
    """دانلود ریلز اینستاگرام با yt-dlp بدون نیاز به لاگین"""
    ydl_opts = {
        'format': 'best[ext=mp4]',
        'outtmpl': 'reel_%(id)s.%(ext)s',
        'quiet': True,
    }
    
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    
    return filename

async def download_youtube_short(url: str) -> str:
    """دانلود یوتیوب شورتس با pytube"""
    yt = YouTube(url)
    stream = yt.streams.filter(
        progressive=True,
        file_extension='mp4',
        resolution="720p"
    ).first() or yt.streams.get_highest_resolution()
    
    filename = f"short_{yt.video_id}.mp4"
    stream.download(filename=filename)
    return filename

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    text = message.text or (message.caption if message.caption else "")
    
    if not text:
        return
    
    # چک کردن لینک اینستاگرام
    insta_match = re.search(INSTAGRAM_REGEX, text)
    if insta_match:
        url = insta_match.group(0)
        await process_media(url, message, context, "Instagram Reels")
        return
    
    # چک کردن لینک یوتیوب
    yt_match = re.search(YOUTUBE_REGEX, text)
    if yt_match:
        url = yt_match.group(0)
        await process_media(url, message, context, "YouTube Shorts")
        return

async def process_media(url: str, message, context, media_type: str):
    """پردازش و ارسال مدیا"""
    try:
        status_msg = await message.reply_text(f"⏳ در حال دریافت {media_type}...")
        
        if "instagram" in url:
            filename = await download_instagram_reel(url)
        else:
            filename = await download_youtube_short(url)
        
        # ارسال ویدیو
        with open(filename, 'rb') as video_file:
            await context.bot.send_video(
                chat_id=message.chat_id,
                video=video_file,
                supports_streaming=True,
                reply_to_message_id=message.message_id
            )
        
        await status_msg.delete()
        
    except Exception as e:
        error_msg = f"❌ خطا: {str(e)}"
        await message.reply_text(error_msg)
    finally:
        if 'filename' in locals() and os.path.exists(filename):
            os.remove(filename)

def main():
    # ساخت و اجرای ربات
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 ربات فعال! در حال گوش دادن به پیام‌ها...")
    app.run_polling()

if __name__ == "__main__":
    main()
