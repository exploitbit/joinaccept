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

# --- CONFIGURATION ---
# We use .get() to avoid crashing immediately if variables are missing
# But we check them right after.
ENV_API_ID = os.environ.get("API_ID")
ENV_API_HASH = os.environ.get("API_HASH")
ENV_BOT_TOKEN = os.environ.get("BOT_TOKEN")
ENV_CHANNEL_ID = os.environ.get("CHANNEL_ID")

# The Admin ID to receive notifications
ADMIN_ID = 8469993808

# Check if variables exist before starting
if not ENV_API_ID or not ENV_API_HASH or not ENV_BOT_TOKEN or not ENV_CHANNEL_ID:
    logger.error("❌ CRITICAL ERROR: Missing Environment Variables!")
    logger.error("Please go to Railway -> Variables and add: API_ID, API_HASH, BOT_TOKEN, CHANNEL_ID")
    exit(1)

API_ID = int(ENV_API_ID)
API_HASH = ENV_API_HASH
BOT_TOKEN = ENV_BOT_TOKEN
CHANNEL_ID = int(ENV_CHANNEL_ID)

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
    
    # Notify Admin that work has started
    try:
        await app.send_message(ADMIN_ID, "🔄 Bot Restarted: Processing backlog of old requests...")
    except Exception as e:
        logger.error(f"Could not message admin: {e}")

    count = 0
    
    async for request in app.get_chat_join_requests(CHANNEL_ID):
        try:
            await app.approve_chat_join_request(
                chat_id=CHANNEL_ID,
                user_id=request.user.id
            )
            count += 1
            
            # NOTIFICATION LOGIC FOR BACKLOG:
            # We send a summary every 50 users to avoid spamming the admin 10,000 times.
            if count % 50 == 0:
                msg = f"✅ Backfill Update: Approved {count} users so far..."
                logger.info(msg)
                try:
                    await app.send_message(ADMIN_ID, msg)
                except:
                    pass
            
            await asyncio.sleep(0.1)

        except FloodWait as e:
            logger.warning(f"⚠️ Rate Limit! Sleeping for {e.value} seconds.")
            await asyncio.sleep(e.value)
            # Retry once
            try:
                await app.approve_chat_join_request(chat_id=CHANNEL_ID, user_id=request.user.id)
            except:
                pass
        except UserAlreadyParticipant:
            pass 
        except Exception as e:
            logger.error(f"❌ Error approving {request.user.id}: {e}")

    final_msg = f"🎉 Backfill Complete! Total old requests approved: {count}"
    logger.info(final_msg)
    await app.send_message(ADMIN_ID, final_msg)

# ---------------------------------------------------------
# HANDLER: Accept New Incoming Requests (Real-time)
# ---------------------------------------------------------
@app.on_chat_join_request(filters.chat(CHANNEL_ID))
async def approve_new_request(client, message: ChatJoinRequest):
    try:
        user = message.from_user
        await client.approve_chat_join_request(
            chat_id=message.chat.id,
            user_id=user.id
        )
        
        # Log to console
        logger.info(f"⚡ Approved: {user.first_name}")

        # --- NOTIFY ADMIN ---
        # Sends a message for every NEW user
        admin_text = (
            f"✅ **New Request Approved**\n"
            f"👤 Name: {user.first_name}\n"
            f"🆔 ID: `{user.id}`"
        )
        await client.send_message(ADMIN_ID, admin_text)

    except Exception as e:
        logger.error(f"Error on new request: {e}")

# ---------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------
async def main():
    await app.start()
    
    # 1. Clear old requests
    await process_backlog()
    
    # 2. Listen for new ones
    logger.info("🤖 Bot is now Idle and listening for NEW requests...")
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
