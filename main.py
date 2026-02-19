import asyncio
import logging
import sys
from pyrogram import Client, idle, filters
from pyrogram.types import ChatJoinRequest, Message
from pyrogram.errors import FloodWait, UserAlreadyParticipant, PeerIdInvalid, ChatAdminRequired, ChannelInvalid, InviteHashExpired, UsernameNotOccupied

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

# Admin ID for notifications
ADMIN_ID = 8469993808

# Global variable to store the channel ID (will be set via /add command)
CHANNEL_ID = None
CHANNEL_INFO = None

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
async def verify_bot_admin(channel_id):
    """Check if bot is admin in the specified channel"""
    try:
        # Try to get chat info to verify access
        chat = await app.get_chat(channel_id)
        logger.info(f"✅ Connected to chat: {chat.title} (ID: {chat.id})")
        
        # Store channel info globally
        global CHANNEL_INFO
        CHANNEL_INFO = chat
        
        # Verify bot is admin (try to get its privileges)
        try:
            bot_member = await app.get_chat_member(channel_id, "me")
            if not bot_member.privileges or not bot_member.privileges.can_invite_users:
                logger.error("❌ Bot is not an admin or doesn't have 'can_invite_users' permission!")
                logger.error("   Please add the bot as an admin with 'Add members' permission.")
                return False
        except Exception as e:
            logger.error(f"❌ Bot is not an admin in the channel: {e}")
            return False
        
        logger.info("✅ Bot has proper admin privileges")
        return True
    except ChatAdminRequired:
        logger.error("❌ Bot is not an admin in the channel!")
        logger.error("   Please add the bot as an admin with 'Add members' permission.")
        return False
    except ChannelInvalid:
        logger.error(f"❌ Channel ID {channel_id} is invalid!")
        logger.error("   Make sure the channel exists and the bot is added to it.")
        return False
    except PeerIdInvalid:
        logger.error(f"❌ Peer ID {channel_id} is invalid!")
        logger.error("   Make sure you're using the correct ID format.")
        logger.error("   For channels, it should be like: -1001234567890")
        logger.error("   For public channels, you can also use @username")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to verify bot admin status: {e}")
        return False

# ---------------------------------------------------------
# COMMAND: /add - Add a channel to monitor
# ---------------------------------------------------------
@app.on_message(filters.command("add") & filters.user(ADMIN_ID))
async def add_channel(client: Client, message: Message):
    """Add a channel to monitor for join requests"""
    global CHANNEL_ID, CHANNEL_INFO
    
    # Get the channel identifier from the command
    command_parts = message.text.split()
    
    if len(command_parts) < 2:
        await message.reply_text(
            "❌ **Usage:** `/add <channel_id or @username>`\n\n"
            "Examples:\n"
            "• `/add -1001234567890` (for private channels)\n"
            "• `/add @my_channel` (for public channels)\n\n"
            "⚠️ Make sure the bot is an admin in the channel first!"
        )
        return
    
    channel_input = command_parts[1].strip()
    
    # Send initial message
    status_msg = await message.reply_text(f"🔍 Verifying access to {channel_input}...")
    
    try:
        # Try to parse the channel identifier
        # Check if it's a numeric ID (with or without -100 prefix)
        if channel_input.lstrip('-').isdigit():
            channel_id = int(channel_input)
        else:
            # Assume it's a username
            channel_id = channel_input
        
        # Verify bot can access the channel
        if await verify_bot_admin(channel_id):
            CHANNEL_ID = channel_id
            await status_msg.edit_text(
                f"✅ **Channel added successfully!**\n\n"
                f"**Channel:** {CHANNEL_INFO.title}\n"
                f"**ID:** `{CHANNEL_INFO.id}`\n"
                f"**Type:** {'Private' if CHANNEL_INFO.username is None else 'Public'}\n"
                f"**Username:** @{CHANNEL_INFO.username if CHANNEL_INFO.username else 'N/A'}\n\n"
                f"🔄 Now processing any pending join requests..."
            )
            
            # Start processing backlog for this channel
            asyncio.create_task(process_backlog_for_channel(channel_id))
            
        else:
            await status_msg.edit_text(
                f"❌ **Failed to add channel!**\n\n"
                f"Could not verify bot admin status for {channel_input}.\n\n"
                f"**Please check:**\n"
                f"1. The bot is added to the channel\n"
                f"2. The bot is an **admin** with 'Add Members' permission\n"
                f"3. The channel ID/username is correct"
            )
    
    except ValueError:
        await status_msg.edit_text(
            f"❌ **Invalid channel identifier!**\n\n"
            f"Please provide a valid channel ID (like -1001234567890) or @username."
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:** {str(e)}")

# ---------------------------------------------------------
# COMMAND: /status - Check current bot status
# ---------------------------------------------------------
@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def check_status(client: Client, message: Message):
    """Check the current status of the bot"""
    global CHANNEL_ID, CHANNEL_INFO
    
    if CHANNEL_ID is None:
        await message.reply_text(
            "❌ **No channel configured!**\n\n"
            "Use `/add <channel_id>` to add a channel first."
        )
        return
    
    status_text = (
        f"📊 **Bot Status**\n\n"
        f"**Channel:** {CHANNEL_INFO.title if CHANNEL_INFO else 'Unknown'}\n"
        f"**Channel ID:** `{CHANNEL_ID}`\n"
        f"**Status:** {'✅ Active' if CHANNEL_INFO else '⚠️ Not verified'}\n\n"
        f"**Bot is running and monitoring for join requests.**"
    )
    
    await message.reply_text(status_text)

# ---------------------------------------------------------
# COMMAND: /stop - Stop monitoring current channel
# ---------------------------------------------------------
@app.on_message(filters.command("stop") & filters.user(ADMIN_ID))
async def stop_monitoring(client: Client, message: Message):
    """Stop monitoring the current channel"""
    global CHANNEL_ID, CHANNEL_INFO
    
    if CHANNEL_ID is None:
        await message.reply_text("❌ No channel is currently being monitored.")
        return
    
    old_channel = CHANNEL_INFO.title if CHANNEL_INFO else str(CHANNEL_ID)
    CHANNEL_ID = None
    CHANNEL_INFO = None
    
    await message.reply_text(f"✅ Stopped monitoring {old_channel}.")

# ---------------------------------------------------------
# FUNCTION: Process Old "Backlog" Requests for a specific channel
# ---------------------------------------------------------
async def process_backlog_for_channel(channel_id):
    """Process pending join requests for a specific channel"""
    logger.info(f"⏳ Starting Backfill for channel {channel_id}: Fetching existing pending requests...")
    
    # Notify Admin that work has started
    try:
        await app.send_message(ADMIN_ID, f"🔄 Processing backlog of old requests for {channel_id}...")
    except Exception as e:
        logger.warning(f"Could not message admin: {e}")

    count = 0
    errors = 0
    
    try:
        # First verify we can access the channel
        try:
            chat = await app.get_chat(channel_id)
            logger.info(f"📢 Processing requests for: {chat.title}")
        except Exception as e:
            logger.error(f"❌ Cannot access channel: {e}")
            return
        
        # Iterate through ALL pending requests
        async for request in app.get_chat_join_requests(channel_id):
            try:
                await app.approve_chat_join_request(
                    chat_id=channel_id,
                    user_id=request.user.id
                )
                count += 1
                
                # Log every 10 users for progress
                if count % 10 == 0:
                    logger.info(f"✅ Backfill progress: {count} users approved so far...")
                
                # Send a progress update to Admin every 50 users
                if count % 50 == 0:
                    msg = f"✅ Backfill Update: Approved {count} users so far for {chat.title}..."
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
                    await app.approve_chat_join_request(chat_id=channel_id, user_id=request.user.id)
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

        final_msg = f"🎉 Backfill Complete for {chat.title}! Total old requests approved: {count} | Errors: {errors}"
        logger.info(final_msg)
        try:
            await app.send_message(ADMIN_ID, final_msg)
        except Exception as e:
            logger.warning(f"Could not send final message to admin: {e}")
            
    except Exception as e:
        logger.error(f"❌ Fatal error in backfill process: {e}")
        try:
            await app.send_message(ADMIN_ID, f"❌ Backfill failed for channel {channel_id}: {e}")
        except:
            pass

# ---------------------------------------------------------
# HANDLER: Accept New Incoming Requests (Real-time)
# ---------------------------------------------------------
@app.on_chat_join_request()
async def approve_new_request(client, message: ChatJoinRequest):
    global CHANNEL_ID
    
    # Check if this is for our configured channel
    if CHANNEL_ID is None or message.chat.id != CHANNEL_ID:
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
            f"📊 Username: @{user.username if user.username else 'None'}\n"
            f"📢 Channel: {message.chat.title}"
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
        
        # Notify admin that bot is running
        await app.send_message(
            ADMIN_ID,
            "🚀 **Bot Started!**\n\n"
            "Use `/add <channel_id>` to start monitoring a channel.\n"
            "Use `/status` to check current status.\n"
            "Use `/stop` to stop monitoring."
        )
        
        logger.info("🤖 Bot is now Idle and waiting for /add command...")
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
