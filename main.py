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

# --- CONFIGURATION (Hardcoded) ---
# ⚠️ WARNING: Never share this file publicly if it contains these real secrets.
API_ID = 33277483
API_HASH = "65b9f007d9d208b99519c52ce89d3a2a"
BOT_TOKEN = "8502935085:AAFyp69SfDXMEcnLmV55ujan3AdreyEj-MA"
CHANNEL_ID = -1003784917581

# Admin ID for notifications
ADMIN_ID = 8469993808

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
    
    # Iterate through ALL pending requests
    async for request in app.get_chat_join_requests(CHANNEL_ID):
        try:
            await app.approve_chat_join_request(
                chat_id=CHANNEL_ID,
                user_id=request.user.id
            )
            count += 1
            
            # Send a progress update to Admin every 50 users (to avoid spamming you)
            if count % 50 == 0:
                msg = f"✅ Backfill Update: Approved {count} users so far..."
                logger.info(msg)
                try:
                    await app.send_message(ADMIN_ID, msg)
                except:
                    pass
            
            # Tiny sleep to prevent FloodWait errors
            await asyncio.sleep(0.1)

        except FloodWait as e:
            logger.warning(f"⚠️ Rate Limit! Sleeping for {e.value} seconds.")
            await asyncio.sleep(e.value)
            # Retry once after sleeping
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
    try:
        await app.send_message(ADMIN_ID, final_msg)
    except:
        pass

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
        
        logger.info(f"⚡ Approved: {user.first_name}")

        # --- NOTIFY ADMIN ---
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
