import asyncio
import logging
import sys
from pyrogram import Client, idle, filters
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import FloodWait, UserAlreadyParticipant, PeerIdInvalid, ChatAdminRequired, ChannelInvalid, InviteHashExpired

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION (Hardcoded) ---
# ⚠️ WARNING: Never share this file publicly if it contains these real secrets.
API_ID = 33277483  # This is fine as integer
API_HASH = "65b9f007d9d208b99519c52ce89d3a2a"  # Must be in quotes!
BOT_TOKEN = "8502935085:AAFyp69SfDXMEcnLmV55ujan3AdreyEj-MA"
CHANNEL_ID = -1003784917581  # Negative value for channel

# Admin ID for notifications
ADMIN_ID = 8469993808

app = Client(
    "approver_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    sleep_threshold=60  # Add threshold for flood wait handling
)

# ---------------------------------------------------------
# FUNCTION: Verify Bot is Admin in Channel
# ---------------------------------------------------------
async def verify_bot_admin():
    """Check if bot is admin in the channel"""
    try:
        # Try to get chat info to verify access
        chat = await app.get_chat(CHANNEL_ID)
        logger.info(f"✅ Connected to chat: {chat.title} (ID: {chat.id})")
        
        # Verify bot is admin (try to get its privileges)
        bot_member = await app.get_chat_member(CHANNEL_ID, "me")
        if not bot_member.privileges or not bot_member.privileges.can_invite_users:
            logger.error("❌ Bot is not an admin or doesn't have 'can_invite_users' permission!")
            logger.error("   Please add the bot as an admin with 'Add members' permission.")
            return False
        
        logger.info("✅ Bot has proper admin privileges")
        return True
    except ChatAdminRequired:
        logger.error("❌ Bot is not an admin in the channel!")
        logger.error("   Please add the bot as an admin with 'Add members' permission.")
        return False
    except ChannelInvalid:
        logger.error(f"❌ Channel ID {CHANNEL_ID} is invalid!")
        logger.error("   Make sure the channel exists and the bot is added to it.")
        return False
    except PeerIdInvalid:
        logger.error(f"❌ Peer ID {CHANNEL_ID} is invalid!")
        logger.error("   For channels, make sure to use the correct negative ID.")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to verify bot admin status: {e}")
        return False

# ---------------------------------------------------------
# FUNCTION: Process Old "Backlog" Requests
# ---------------------------------------------------------
async def process_backlog():
    logger.info("⏳ Starting Backfill: Fetching existing pending requests...")
    
    # Notify Admin that work has started
    try:
        await app.send_message(ADMIN_ID, "🔄 Bot Restarted: Processing backlog of old requests...")
    except Exception as e:
        logger.warning(f"Could not message admin: {e}")

    count = 0
    errors = 0
    
    try:
        # First verify we can access the channel
        try:
            chat = await app.get_chat(CHANNEL_ID)
            logger.info(f"📢 Processing requests for: {chat.title}")
        except Exception as e:
            logger.error(f"❌ Cannot access channel: {e}")
            return
        
        # Iterate through ALL pending requests
        async for request in app.get_chat_join_requests(CHANNEL_ID):
            try:
                await app.approve_chat_join_request(
                    chat_id=CHANNEL_ID,
                    user_id=request.user.id
                )
                count += 1
                
                # Log every 10 users for progress
                if count % 10 == 0:
                    logger.info(f"✅ Backfill progress: {count} users approved so far...")
                
                # Send a progress update to Admin every 50 users
                if count % 50 == 0:
                    msg = f"✅ Backfill Update: Approved {count} users so far..."
                    logger.info(msg)
                    try:
                        await app.send_message(ADMIN_ID, msg)
                    except Exception as e:
                        logger.warning(f"Failed to send progress update: {e}")
                
                # Small sleep to prevent FloodWait errors
                await asyncio.sleep(0.5)

            except FloodWait as e:
                logger.warning(f"⚠️ Rate Limit! Sleeping for {e.value} seconds.")
                await asyncio.sleep(e.value)
                # Retry once after sleeping
                try:
                    await app.approve_chat_join_request(chat_id=CHANNEL_ID, user_id=request.user.id)
                    count += 1
                except Exception as retry_error:
                    logger.error(f"❌ Retry failed: {retry_error}")
                    errors += 1
                    
            except UserAlreadyParticipant:
                # User already in channel, skip
                logger.debug(f"User {request.user.id} already in channel")
                pass
                
            except Exception as e:
                logger.error(f"❌ Error approving {request.user.id} ({request.user.first_name}): {e}")
                errors += 1

        final_msg = f"🎉 Backfill Complete! Total old requests approved: {count} | Errors: {errors}"
        logger.info(final_msg)
        try:
            await app.send_message(ADMIN_ID, final_msg)
        except Exception as e:
            logger.warning(f"Could not send final message to admin: {e}")
            
    except Exception as e:
        logger.error(f"❌ Fatal error in backfill process: {e}")
        try:
            await app.send_message(ADMIN_ID, f"❌ Backfill failed: {e}")
        except:
            pass

# ---------------------------------------------------------
# HANDLER: Accept New Incoming Requests (Real-time)
# ---------------------------------------------------------
@app.on_chat_join_request()
async def approve_new_request(client, message: ChatJoinRequest):
    # Check if this is for our channel
    if message.chat.id != CHANNEL_ID:
        return
        
    try:
        user = message.from_user
        await client.approve_chat_join_request(
            chat_id=message.chat.id,
            user_id=user.id
        )
        
        logger.info(f"⚡ Approved: {user.first_name} (ID: {user.id})")

        # --- NOTIFY ADMIN ---
        admin_text = (
            f"✅ **New Request Approved**\n"
            f"👤 Name: {user.first_name}\n"
            f"🆔 ID: `{user.id}`\n"
            f"📊 Username: @{user.username if user.username else 'None'}"
        )
        await client.send_message(ADMIN_ID, admin_text)

    except FloodWait as e:
        logger.warning(f"⚠️ Rate limit hit for new request: Sleeping {e.value}s")
        await asyncio.sleep(e.value)
        # Retry
        try:
            await client.approve_chat_join_request(
                chat_id=message.chat.id,
                user_id=message.from_user.id
            )
        except Exception as retry_error:
            logger.error(f"❌ Retry failed: {retry_error}")
    except UserAlreadyParticipant:
        logger.info(f"User {message.from_user.id} already in channel")
    except Exception as e:
        logger.error(f"❌ Error approving new request: {e}")

# ---------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------
async def main():
    try:
        await app.start()
        logger.info("🚀 Bot started successfully!")
        
        # Verify bot has proper access to the channel
        if not await verify_bot_admin():
            logger.error("❌ Bot verification failed. Stopping...")
            await app.stop()
            return
        
        # 1. Clear old requests
        await process_backlog()
        
        # 2. Listen for new ones
        logger.info("🤖 Bot is now Idle and listening for NEW requests...")
        await idle()
        
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error in main: {e}")
    finally:
        try:
            await app.send_message(ADMIN_ID, "🛑 Bot stopped!")
        except:
            pass
        await app.stop()
        logger.info("👋 Bot shutdown complete")

if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
