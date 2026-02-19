import asyncio
import logging
import sys
import os
from pyrogram import Client, idle, filters
from pyrogram.types import ChatJoinRequest, Message
from pyrogram.errors import FloodWait, UserAlreadyParticipant
from pyrogram.handlers import ChatJoinRequestHandler, MessageHandler

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION from Environment Variables ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
PHONE_NUMBER = os.environ.get("PHONE_NUMBER", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", 0))

# Validate required variables
missing = []
if not API_ID:
    missing.append("API_ID")
if not API_HASH:
    missing.append("API_HASH")
if not PHONE_NUMBER:
    missing.append("PHONE_NUMBER")
if not ADMIN_ID:
    missing.append("ADMIN_ID")
if not CHANNEL_ID:
    missing.append("CHANNEL_ID")

if missing:
    logger.error(f"❌ Missing required environment variables: {', '.join(missing)}")
    sys.exit(1)

# Global variables (will be set after client starts)
CHANNEL_INFO = None
approval_count = 0

# ---------------------------------------------------------
# Handler Functions (defined before client creation)
# ---------------------------------------------------------
async def approve_new_request(client: Client, request: ChatJoinRequest):
    """Handle new chat join requests in real time."""
    global approval_count

    if request.chat.id != CHANNEL_ID:
        return

    try:
        user = request.from_user
        await client.approve_chat_join_request(
            chat_id=request.chat.id,
            user_id=user.id
        )
        approval_count += 1
        logger.info(f"⚡ New request approved: {user.first_name} (ID: {user.id}) [Total: {approval_count}]")

        admin_text = (
            f"✅ **New Request Approved**\n"
            f"👤 Name: {user.first_name}\n"
            f"🆔 ID: `{user.id}`\n"
            f"📊 Username: @{user.username if user.username else 'None'}\n"
            f"📈 Total Approved: {approval_count}"
        )
        await client.send_message(ADMIN_ID, admin_text)

    except FloodWait as e:
        logger.warning(f"⚠️ Rate limit: Sleeping {e.value}s")
        await asyncio.sleep(e.value)
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


async def start_command(client: Client, message: Message):
    """Handle /start command to begin backfill."""
    await message.reply_text("🔄 Starting approval process for ALL pending requests...")
    await process_all_pending_requests(client, CHANNEL_ID)


async def status_command(client: Client, message: Message):
    """Handle /status command."""
    global approval_count
    status_text = (
        f"📊 **Bot Status**\n\n"
        f"**Channel:** {CHANNEL_INFO.title if CHANNEL_INFO else 'Unknown'}\n"
        f"**Channel ID:** `{CHANNEL_ID}`\n"
        f"**Total Approved:** {approval_count}\n"
        f"**Status:** ✅ Active\n\n"
        f"**Commands:**\n"
        f"• `/start` - Approve ALL pending requests\n"
        f"• `/status` - This message"
    )
    await message.reply_text(status_text)


# ---------------------------------------------------------
# Backfill Function
# ---------------------------------------------------------
async def process_all_pending_requests(client: Client, channel_id: int):
    """Process ALL pending join requests (old + new)."""
    global approval_count
    logger.info("=" * 50)
    logger.info("🚀 STARTING COMPLETE BACKFILL OF ALL PENDING REQUESTS")
    logger.info("=" * 50)

    try:
        await client.send_message(
            ADMIN_ID,
            "🔄 **Starting Complete Backfill**\n\nProcessing ALL pending join requests..."
        )
    except Exception as e:
        logger.warning(f"Could not message admin: {e}")

    count = 0
    errors = 0

    try:
        chat = await client.get_chat(channel_id)
        logger.info(f"📢 Processing ALL requests for: {chat.title}")

        has_more = True
        offset_date = None
        offset_user = None

        while has_more:
            try:
                # Fetch pending join requests with pagination
                requests = await client.get_chat_join_requests(
                    chat_id=channel_id,
                    limit=100,
                    offset_date=offset_date,
                    offset_user=offset_user
                )
                request_list = list(requests)
                batch_count = len(request_list)

                if batch_count == 0:
                    has_more = False
                    break

                logger.info(f"📦 Fetched batch of {batch_count} requests (Total so far: {count})")

                for request in request_list:
                    try:
                        await client.approve_chat_join_request(
                            chat_id=channel_id,
                            user_id=request.user.id
                        )
                        count += 1
                        approval_count += 1

                        if count % 10 == 0:
                            logger.info(f"✅ Progress: {count} users approved...")

                        offset_date = request.date
                        offset_user = request.user.id
                        await asyncio.sleep(0.2)

                    except FloodWait as e:
                        logger.warning(f"⚠️ Rate Limit! Sleeping for {e.value} seconds.")
                        await asyncio.sleep(e.value)
                        try:
                            await client.approve_chat_join_request(
                                chat_id=channel_id,
                                user_id=request.user.id
                            )
                            count += 1
                            approval_count += 1
                        except Exception as retry_error:
                            logger.error(f"❌ Retry failed: {retry_error}")
                            errors += 1
                    except UserAlreadyParticipant:
                        pass
                    except Exception as e:
                        logger.error(f"❌ Error approving {request.user.id}: {e}")
                        errors += 1

                # Send progress update every 100 users
                if count % 100 == 0 and count > 0:
                    try:
                        await client.send_message(
                            ADMIN_ID,
                            f"✅ **Backfill Progress:** {count} users approved so far..."
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send progress update: {e}")

            except Exception as e:
                logger.error(f"❌ Error fetching requests batch: {e}")
                has_more = False

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
        except Exception:
            pass


# ---------------------------------------------------------
# Helper: Verify User is Admin in Channel
# ---------------------------------------------------------
async def verify_user_admin(client: Client, channel_id: int) -> bool:
    """Check if the user is an admin with invite permissions."""
    global CHANNEL_INFO
    try:
        chat = await client.get_chat(channel_id)
        logger.info(f"✅ Connected to chat: {chat.title} (ID: {chat.id})")
        CHANNEL_INFO = chat

        # Verify user is admin
        try:
            user_member = await client.get_chat_member(channel_id, "me")
            if not user_member.privileges or not user_member.privileges.can_invite_users:
                logger.error("❌ User doesn't have 'can_invite_users' permission!")
                return False
        except Exception as e:
            logger.error(f"❌ User is not an admin: {e}")
            return False

        logger.info("✅ User has proper admin privileges")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to verify admin status: {e}")
        return False


# ---------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------
async def main():
    # Create client (user account, not bot)
    client = Client(
        "user_approver",
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=PHONE_NUMBER,
        workdir="./sessions"
    )

    # Register handlers
    client.add_handler(ChatJoinRequestHandler(approve_new_request))
    client.add_handler(MessageHandler(start_command, filters.command("start") & filters.user(ADMIN_ID)))
    client.add_handler(MessageHandler(status_command, filters.command("status") & filters.user(ADMIN_ID)))

    try:
        await client.start()
        logger.info("🚀 User client started successfully!")

        # Verify admin access
        if not await verify_user_admin(client, CHANNEL_ID):
            logger.error("❌ Cannot proceed: User is not an admin!")
            await client.stop()
            return

        # Send startup message
        await client.send_message(
            ADMIN_ID,
            "🚀 **User Approver Started on Railway!**\n\n"
            f"📢 Monitoring channel: {CHANNEL_INFO.title}\n\n"
            "**Commands:**\n"
            "• `/start` - Approve ALL pending requests\n"
            "• `/status` - Check status\n\n"
            "⚠️ New requests will be auto-approved in real-time."
        )

        logger.info("🤖 Bot is now idle. Send /start to approve all pending requests.")
        await idle()

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        await client.stop()
        logger.info("👋 Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
