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
API_ID = 33277483
API_HASH = "65b9f007d9d208b99519c52ce89d3a2a"
BOT_TOKEN = "8502935085:AAFyp69SfDXMEcnLmV55ujan3AdreyEj-MA"
CHANNEL_ID = -1003784917581

# Admin ID for notifications
ADMIN_ID = 8469993808

# Initialize the Client with in-memory storage to avoid database locks
app = Client(
    "approver_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

# ---------------------------------------------------------
# FUNCTION: Process Old "Backlog" Requests
# ---------------------------------------------------------
async def process_backlog():
    logger.info("⏳ Starting Backfill: Fetching existing pending requests...")
    
    # --- THE FIX: PRE-FETCH CHANNEL ---
    # We must fetch the chat details first so Pyrogram caches the Access Hash.
    # Without this, it crashes with "ID not found".
    try:
        logger.info(f"🔍 Verifying channel access for ID: {CHANNEL_ID}...")
        chat_info = await app.get_chat(CHANNEL_ID)
        logger.info(f"✅ Access Verified: Connected to '{chat_info.title}'")
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR: Could not access channel {CHANNEL_ID}.")
        logger.error(f"Make sure the Bot is an ADMIN in the channel!")
        logger.error(f"Error details: {e}")
        return # Stop backfill if we can't access the channel

    # Notify Admin
    try:
        await app.send_message(ADMIN_ID, "🔄 Bot Restarted: Processing backlog...")
    except:
        pass

    count = 0
    
    # Iterate through ALL pending requests
    # We use a try/except loop to ensure one bad request doesn't crash the whole bot
    try:
        async for request in app.get_chat_join_requests(CHANNEL_ID):
            try:
                await app.approve_chat_join_request(
                    chat_id=CHANNEL_ID,
                    user_id=request.user.id
                )
                count += 1
                
                # Update Admin every 50 users
                if count % 50 == 0:
                    msg = f"✅ Backfill Update: Approved {count} users so far..."
                    logger.info(msg)
                    try:
                        await app.send_message(ADMIN_ID, msg)
                    except:
                        pass
                
                # Tiny sleep to be polite
                await asyncio.sleep(0.1)

            except FloodWait as e:
                logger.warning(f"⚠️ Rate Limit! Sleeping for {e.value} seconds.")
                await asyncio.sleep(e.value)
                try:
                    await app.approve_chat_join_request(chat_id=CHANNEL_ID, user_id=request.user.id)
                except:
                    pass
            except UserAlreadyParticipant:
                pass 
            except Exception as inner_e:
                logger.error(f"❌ Error approving user {request.user.id}: {inner_e}")
                
    except Exception as outer_e:
        logger.error(f"⚠️ Error during backfill loop (Bot will continue listening for new users): {outer_e}")

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
        try:
            await client.send_message(ADMIN_ID, admin_text)
        except:
            pass

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
