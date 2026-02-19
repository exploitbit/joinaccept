import asyncio
import logging
import sys
from pyrogram import Client, idle, filters
from pyrogram.types import ChatJoinRequest, Message
from pyrogram.errors import FloodWait, UserAlreadyParticipant, PeerIdInvalid, ChatAdminRequired, ChannelInvalid
from pyrogram.enums import ChatType

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# For USER account (not bot) - Get from https://my.telegram.org/apps
API_ID = 33277483  # Your API ID
API_HASH = "65b9f007d9d208b99519c52ce89d3a2a"  # Your API Hash

# Your user account phone number (with country code)
PHONE_NUMBER = "+918002591484"  # Replace with your phone number

# Admin ID for notifications (your own user ID)
ADMIN_ID = 8469993808

# Channel to monitor
CHANNEL_ID = -1003784917581  # Your channel ID

# Global variables
CHANNEL_INFO = None
app = None

# ---------------------------------------------------------
# FUNCTION: Create client (user account, not bot)
# ---------------------------------------------------------
def create_client():
    """Create a Pyrogram client for user account"""
    return Client(
        "user_approver",
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=PHONE_NUMBER,  # User account phone
        workdir="./sessions"  # Directory to store session files
    )

# ---------------------------------------------------------
# FUNCTION: Verify User is Admin in Channel
# ---------------------------------------------------------
async def verify_user_admin(client, channel_id):
    """Check if user is admin in the specified channel"""
    try:
        # Try to get chat info
        chat = await client.get_chat(channel_id)
        logger.info(f"✅ Connected to chat: {chat.title} (ID: {chat.id})")
        
        global CHANNEL_INFO
        CHANNEL_INFO = chat
        
        # Verify user is admin
        try:
            user_member = await client.get_chat_member(channel_id, "me")
            if not user_member.privileges or not user_member.privileges.can_invite_users:
                logger.error("❌ User doesn't have 'can_invite_users' permission!")
                logger.error("   Please make the user an admin with 'Add Members' permission.")
                return False
        except Exception as e:
            logger.error(f"❌ User is not an admin in the channel: {e}")
            return False
        
        logger.info("✅ User has proper admin privileges")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to verify user admin status: {e}")
        return False

# ---------------------------------------------------------
# FUNCTION: Process ALL Pending Requests
# ---------------------------------------------------------
async def process_all_pending_requests(client, channel_id):
    """Process ALL pending join requests (old and new)"""
    logger.info("=" * 50)
    logger.info("🚀 STARTING COMPLETE BACKFILL OF ALL PENDING REQUESTS")
    logger.info("=" * 50)
    
    # Notify admin that work has started
    try:
        await client.send_message(
            ADMIN_ID, 
            "🔄 **Starting Complete Backfill**\n\n"
            "Processing ALL pending join requests (old and new)..."
        )
    except Exception as e:
        logger.warning(f"Could not message admin: {e}")

    count = 0
    errors = 0
    
    try:
        # Get chat info
        chat = await client.get_chat(channel_id)
        logger.info(f"📢 Processing ALL requests for: {chat.title}")
        
        # Keep fetching until no more requests
        has_more = True
        offset_date = None
        offset_user = None
        
        while has_more:
            try:
                # Fetch pending join requests with pagination
                requests = await client.get_chat_join_requests(
                    chat_id=channel_id,
                    limit=100,  # Max 100 per request
                    offset_date=offset_date,
                    offset_user=offset_user
                )
                
                request_list = list(requests)
                batch_count = len(request_list)
                
                if batch_count == 0:
                    has_more = False
                    break
                
                logger.info(f"📦 Fetched batch of {batch_count} requests (Total so far: {count})")
                
                # Process each request in the batch
                for request in request_list:
                    try:
                        await client.approve_chat_join_request(
                            chat_id=channel_id,
                            user_id=request.user.id
                        )
                        count += 1
                        
                        # Log progress
                        if count % 10 == 0:
                            logger.info(f"✅ Progress: {count} users approved...")
                        
                        # Update offset for next batch
                        offset_date = request.date
                        offset_user = request.user.id
                        
                        # Small delay to avoid rate limits
                        await asyncio.sleep(0.2)
                        
                    except FloodWait as e:
                        logger.warning(f"⚠️ Rate Limit! Sleeping for {e.value} seconds.")
                        await asyncio.sleep(e.value)
                        # Retry this request
                        try:
                            await client.approve_chat_join_request(
                                chat_id=channel_id,
                                user_id=request.user.id
                            )
                            count += 1
                        except Exception as retry_error:
                            logger.error(f"❌ Retry failed: {retry_error}")
                            errors += 1
                            
                    except UserAlreadyParticipant:
                        logger.debug(f"User {request.user.id} already in channel")
                        pass
                        
                    except Exception as e:
                        logger.error(f"❌ Error approving {request.user.id}: {e}")
                        errors += 1
                
                # Send progress update every 100 users
                if count % 100 == 0 and count > 0:
                    progress_msg = f"✅ **Backfill Progress:** {count} users approved so far..."
                    logger.info(progress_msg)
                    try:
                        await client.send_message(ADMIN_ID, progress_msg)
                    except:
                        pass
                
            except Exception as e:
                logger.error(f"❌ Error fetching requests batch: {e}")
                has_more = False
        
        # Final summary
        final_msg = (
            f"🎉 **Backfill Complete!**\n\n"
            f"📊 **Summary:**\n"
            f"• Total approved: {count}\n"
            f"• Errors: {errors}\n"
            f"• Channel: {chat.title}"
        )
        logger.info(final_msg)
        try:
            await client.send_message(ADMIN_ID, final_msg)
        except Exception as e:
            logger.warning(f"Could not send final message: {e}")
            
    except Exception as e:
        logger.error(f"❌ Fatal error in backfill process: {e}")
        try:
            await client.send_message(ADMIN_ID, f"❌ Backfill failed: {e}")
        except:
            pass

# ---------------------------------------------------------
# HANDLER: Accept New Incoming Requests (Real-time)
# ---------------------------------------------------------
@app.on_chat_join_request()
async def approve_new_request(client, request: ChatJoinRequest):
    # Check if this is for our channel
    if request.chat.id != CHANNEL_ID:
        return
    
    try:
        user = request.from_user
        await client.approve_chat_join_request(
            chat_id=request.chat.id,
            user_id=user.id
        )
        
        logger.info(f"⚡ New request approved: {user.first_name} (ID: {user.id})")

        # --- NOTIFY ADMIN ---
        admin_text = (
            f"✅ **New Request Approved**\n"
            f"👤 Name: {user.first_name}\n"
            f"🆔 ID: `{user.id}`\n"
            f"📊 Username: @{user.username if user.username else 'None'}"
        )
        await client.send_message(ADMIN_ID, admin_text)

    except FloodWait as e:
        logger.warning(f"⚠️ Rate limit: Sleeping {e.value}s")
        await asyncio.sleep(e.value)
        # Retry
        try:
            await client.approve_chat_join_request(
                chat_id=request.chat.id,
                user_id=request.from_user.id
            )
        except Exception as retry_error:
            logger.error(f"❌ Retry failed: {retry_error}")
    except UserAlreadyParticipant:
        logger.info(f"User {request.from_user.id} already in channel")
    except Exception as e:
        logger.error(f"❌ Error approving new request: {e}")

# ---------------------------------------------------------
# COMMAND: /start_approval - Manually start approval process
# ---------------------------------------------------------
@app.on_message(filters.command("start_approval") & filters.user(ADMIN_ID))
async def start_approval(client: Client, message: Message):
    """Manually start the approval process for all pending requests"""
    await message.reply_text("🔄 Starting approval process for ALL pending requests...")
    
    # Run the backfill process
    await process_all_pending_requests(client, CHANNEL_ID)

# ---------------------------------------------------------
# COMMAND: /status - Check status
# ---------------------------------------------------------
@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def check_status(client: Client, message: Message):
    """Check current status"""
    status_text = (
        f"📊 **Bot Status**\n\n"
        f"**Channel:** {CHANNEL_INFO.title if CHANNEL_INFO else 'Unknown'}\n"
        f"**Channel ID:** `{CHANNEL_ID}`\n"
        f"**Status:** ✅ Active\n\n"
        f"**Commands:**\n"
        f"• `/start_approval` - Approve ALL pending requests\n"
        f"• `/status` - This message"
    )
    await message.reply_text(status_text)

# ---------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------
async def main():
    global app
    app = create_client()
    
    try:
        await app.start()
        logger.info("🚀 User client started successfully!")
        
        # First, verify we have admin access
        if not await verify_user_admin(app, CHANNEL_ID):
            logger.error("❌ Cannot proceed: User is not an admin!")
            logger.error("Please make the user an admin in the channel first.")
            await app.stop()
            return
        
        # Ask user if they want to process old requests now
        logger.info("")
        logger.info("=" * 50)
        logger.info("🔔 **ACTION REQUIRED**")
        logger.info("=" * 50)
        logger.info("Send /start_approval to the bot to begin processing ALL pending requests")
        logger.info("Or wait for new requests to be auto-approved")
        logger.info("")
        
        # Send startup message
        await app.send_message(
            ADMIN_ID,
            "🚀 **User Approver Started!**\n\n"
            f"📢 Monitoring channel: {CHANNEL_INFO.title}\n\n"
            "**Commands:**\n"
            "• `/start_approval` - Approve ALL pending requests (old + new)\n"
            "• `/status` - Check status\n\n"
            "⚠️ New requests will be auto-approved in real-time."
        )
        
        logger.info("🤖 Bot is now idle...")
        await idle()
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        await app.stop()
        logger.info("👋 Shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
