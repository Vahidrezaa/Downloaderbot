import os
import re
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
import yt_dlp

# Patterns
INSTAGRAM_REEL_REGEX = r'(https?://www\.instagram\.com/reel/[^\s]+)'
YOUTUBE_SHORTS_REGEX = r'(https?://(www\.)?youtube\.com/shorts/[^\s]+)'

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    insta_match = re.search(INSTAGRAM_REEL_REGEX, text)
    yt_match = re.search(YOUTUBE_SHORTS_REGEX, text)

    if insta_match:
        await download_instagram_reel(insta_match.group(1), chat_id, context)

    elif yt_match:
        await download_youtube_shorts(yt_match.group(1), chat_id, context)
import re
import yt_dlp
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# لینک‌های هدف: Reels (Instagram) یا Shorts (YouTube)
INSTAGRAM_REELS_PATTERN = r'(https?://www\.instagram\.com/reel/[^\s]+)'
YOUTUBE_SHORTS_PATTERN = r'(https?://(www\.)?youtube\.com/shorts/[^\s]+)'

async def handle_video_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    # بررسی وجود لینک Reels یا Shorts
    match = re.search(INSTAGRAM_REELS_PATTERN, text) or re.search(YOUTUBE_SHORTS_PATTERN, text)
    if not match:
        return

    url = match.group(0)

    # دانلود و ارسال ویدیو
    try:
        ydl_opts = {
            'outtmpl': 'downloaded_video.%(ext)s',
            'format': 'mp4',
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_path = ydl.prepare_filename(info)

        await context.bot.send_video(chat_id=chat_id, video=open(video_path, 'rb'), caption="Here's your video 📥")
    except Exception as e:
        await update.message.reply_text(f"❌ Error downloading video: {e}")

if __name__ == '__main__':
    app = ApplicationBuilder().token("YOUR_BOT_TOKEN").build()

    video_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_video_links)
    app.add_handler(video_handler)

    app.run_polling()
async def download_instagram_reel(url, chat_id, context):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.post('https://snapsave.app/action.php', data={'url': url}, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        video_tag = soup.find('a', {'class': 'abutton'})
        video_url = video_tag['href'] if video_tag else None

        if not video_url:
            await context.bot.send_message(chat_id, "⚠️ Couldn't get the Instagram Reel.")
            return

        video_data = requests.get(video_url, headers=headers)
        with open("reel.mp4", "wb") as f:
            f.write(video_data.content)

        await context.bot.send_video(chat_id=chat_id, video=open("reel.mp4", "rb"), caption="📥 Instagram Reel")
        os.remove("reel.mp4")
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Error downloading reel: {e}")

async def download_youtube_shorts(url, chat_id, context):
    try:
        ydl_opts = {
            'format': 'mp4',
            'outtmpl': 'shorts.%(ext)s',
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        await context.bot.send_video(chat_id=chat_id, video=open(file_path, 'rb'), caption="📥 YouTube Shorts")
        os.remove(file_path)
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Error downloading shorts: {e}")

if __name__ == '__main__':
    TOKEN = os.getenv("TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()
