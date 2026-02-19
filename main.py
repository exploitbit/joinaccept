import os
import asyncio
import logging
from pyrogram import Client, idle, filters
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import FloodWait, UserAlreadyParticipant

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load variables from Railway Environment
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))

app = Client(
    "approver_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ---------------------------------------------------------
# FUNCTION: Process Old "Backlog" Requests
# ---------------------------------------------------------
async def process_backlog():
    logger.info("⏳ Starting Backfill: Fetching existing pending requests...")
    count = 0
    
    # We iterate over ALL requests. 
    # This might take a while for 10k users due to Rate Limits.
    async for request in app.get_chat_join_requests(CHANNEL_ID):
        try:
            await app.approve_chat_join_request(
                chat_id=CHANNEL_ID,
                user_id=request.user.id
            )
            count += 1
            if count % 20 == 0:
                logger.info(f"✅ Backfill Progress: Approved {count} users...")
            
            # Tiny sleep to be polite to the server
            await asyncio.sleep(0.1)

        except FloodWait as e:
            logger.warning(f"⚠️ Rate Limit! Sleeping for {e.value} seconds.")
            await asyncio.sleep(e.value)
            # Retry the same user after sleep
            try:
                await app.approve_chat_join_request(chat_id=CHANNEL_ID, user_id=request.user.id)
            except:
                pass
        except UserAlreadyParticipant:
            pass # User is already in, ignore
        except Exception as e:
            logger.error(f"❌ Error approving {request.user.id}: {e}")

    logger.info(f"🎉 Backfill Complete! Total old requests approved: {count}")

# ---------------------------------------------------------
# HANDLER: Accept New Incoming Requests (Real-time)
# ---------------------------------------------------------
@app.on_chat_join_request(filters.chat(CHANNEL_ID))
async def approve_new_request(client, message: ChatJoinRequest):
    try:
        await client.approve_chat_join_request(
            chat_id=message.chat.id,
            user_id=message.from_user.id
        )
        logger.info(f"⚡ Instantly approved new user: {message.from_user.first_name}")
    except Exception as e:
        logger.error(f"Error on new request: {e}")

# ---------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------
async def main():
    await app.start()
    
    # 1. First, clear the 10k pending requests
    # Note: If this takes too long, Railway might restart. 
    # But because we loop, it will pick up where it left off next time.
    await process_backlog()
    
    # 2. Then, stay online forever to handle new ones
    logger.info("🤖 Bot is now Idle and listening for NEW requests...")
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
