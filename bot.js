require('dotenv').config();
const { Telegraf } = require('telegraf');
const { TelegramClient } = require('telegram');
const { StringSession } = require('telegram/sessions');
const { Api } = require('telegram/tl');

// Environment variables
const BOT_TOKEN = process.env.BOT_TOKEN;
const API_ID = parseInt(process.env.API_ID);
const API_HASH = process.env.API_HASH;
const ADMIN_ID = parseInt(process.env.ADMIN_ID);

if (!BOT_TOKEN || !API_ID || !API_HASH || !ADMIN_ID) {
  console.error('Missing required environment variables');
  process.exit(1);
}

// Bot instance
const bot = new Telegraf(BOT_TOKEN);

// Store user state
const userState = new Map();

function getState(userId) {
  if (!userState.has(userId)) {
    userState.set(userId, {
      step: 'idle',
      client: null,
      phone: null,
      phoneCodeHash: null,
      sessionString: '',
      channelId: null,
      isApproving: false,
    });
  }
  return userState.get(userId);
}

// Admin check middleware
bot.use((ctx, next) => {
  if (ctx.from && ctx.from.id === ADMIN_ID) return next();
  // Optionally ignore non-admin
});

bot.start(async (ctx) => {
  const state = getState(ctx.from.id);
  state.step = 'awaiting_phone';
  await ctx.reply('Welcome! Send your phone number (e.g., +918002591484).');
});

bot.on('text', async (ctx) => {
  const userId = ctx.from.id;
  const state = getState(userId);
  const text = ctx.message.text;

  try {
    if (state.step === 'awaiting_phone') {
      const phone = text.trim();
      state.phone = phone;

      // Create client
      const client = new TelegramClient(new StringSession(''), API_ID, API_HASH, {
        connectionRetries: 5,
      });
      state.client = client;

      await ctx.reply('Connecting to Telegram...');
      await client.connect();

      await ctx.reply('Sending OTP...');
      const sendCodeResult = await client.sendCode(
        { apiId: API_ID, apiHash: API_HASH },
        phone
      );
      state.phoneCodeHash = sendCodeResult.phoneCodeHash;

      state.step = 'awaiting_code';
      await ctx.reply('OTP sent! Please enter the code:');
    } 
    else if (state.step === 'awaiting_code') {
      const code = text.trim();
      const client = state.client;
      const phone = state.phone;
      const phoneCodeHash = state.phoneCodeHash;

      try {
        await client.invoke(
          new Api.auth.SignIn({
            phoneNumber: phone,
            phoneCodeHash: phoneCodeHash,
            phoneCode: code,
          })
        );
      } catch (error) {
        if (error.errorMessage === 'SESSION_PASSWORD_NEEDED') {
          state.step = 'awaiting_2fa';
          await ctx.reply('Two‑factor authentication is enabled. Please enter your password:');
          return;
        }
        throw error;
      }

      await handleSuccessfulLogin(ctx, state, client);
    } 
    else if (state.step === 'awaiting_2fa') {
      const password = text.trim();
      const client = state.client;

      await client.invoke(
        new Api.auth.CheckPassword({
          password: await client._getPassword(password),
        })
      );

      await handleSuccessfulLogin(ctx, state, client);
    } 
    else if (state.step === 'awaiting_channel') {
      const channelInput = text.trim();
      const client = state.client;

      try {
        // Ensure client is connected
        if (!client.connected) await client.connect();

        let chat = await client.getEntity(channelInput);
        const me = await client.getMe();
        const participant = await client.getParticipant(chat, me);
        const isAdmin = participant && (participant instanceof Api.ChannelParticipantAdmin || participant instanceof Api.ChannelParticipantCreator);

        if (!isAdmin) {
          await ctx.reply('❌ You are not an admin in that channel.');
          return;
        }

        if (participant.adminRights && !participant.adminRights.inviteUsers) {
          await ctx.reply('❌ You lack "Add Members" permission.');
          return;
        }

        state.channelId = chat.id;
        state.step = 'idle';
        await ctx.reply(`✅ Channel ${chat.title} (ID: ${chat.id}) set. Starting approval...`);

        startApprovalForUser(userId, ctx);
      } catch (error) {
        console.error('Channel error:', error);
        await ctx.reply('❌ Cannot access channel. Check ID/username and admin status.');
      }
    } 
    else {
      await ctx.reply('Use /start to begin.');
    }
  } catch (error) {
    console.error('Error:', error);
    await ctx.reply('An error occurred: ' + error.message);
  }
});

async function handleSuccessfulLogin(ctx, state, client) {
  const sessionString = client.session.save();
  state.sessionString = sessionString;
  await ctx.reply('✅ Login successful! Now send the channel ID or username (e.g., @FocketTricks).');
  state.step = 'awaiting_channel';
}

async function startApprovalForUser(userId, ctx) {
  const state = getState(userId);
  if (state.isApproving) return;
  state.isApproving = true;

  const client = state.client;
  const channelId = state.channelId;

  // Backfill old requests
  (async () => {
    try {
      await ctx.reply('🔄 Fetching all pending join requests...');
      let count = 0, errors = 0;
      const chat = await client.getEntity(channelId);

      const requestsIter = client.iterChatJoinRequests(channelId, { limit: 100 });

      for await (const req of requestsIter) {
        try {
          await client.invoke(
            new Api.messages.ApproveChatJoinRequest({
              peer: channelId,
              userId: req.userId,
            })
          );
          count++;
          if (count % 10 === 0) {
            console.log(`Approved ${count} users...`);
          }
          await new Promise(resolve => setTimeout(resolve, 200));
        } catch (e) {
          if (e.errorMessage === 'FLOOD_WAIT') {
            const seconds = e.seconds || 5;
            console.log(`Flood wait, sleeping ${seconds}s`);
            await new Promise(resolve => setTimeout(resolve, seconds * 1000));
            try {
              await client.invoke(
                new Api.messages.ApproveChatJoinRequest({
                  peer: channelId,
                  userId: req.userId,
                })
              );
              count++;
            } catch {
              errors++;
            }
          } else {
            errors++;
          }
        }
      }

      await ctx.reply(`✅ Backfill complete! Approved ${count} users (errors: ${errors}).`);
    } catch (error) {
      console.error('Backfill error:', error);
      await ctx.reply('❌ Backfill error: ' + error.message);
    } finally {
      state.isApproving = false;
    }
  })();

  // Real-time handler for new requests
  client.addEventHandler(async (update) => {
    if (update instanceof Api.UpdateBotChatInviteRequester) {
      if (update.peer.channelId && update.peer.channelId.toString() === channelId.toString()) {
        try {
          await client.invoke(
            new Api.messages.ApproveChatJoinRequest({
              peer: channelId,
              userId: update.userId,
            })
          );
          console.log(`Approved new user ${update.userId}`);
          await ctx.telegram.sendMessage(ADMIN_ID, `✅ New request approved: ${update.userId}`);
        } catch (e) {
          console.error('Error approving new request:', e);
        }
      }
    }
  });
}

// Graceful shutdown
async function shutdown(signal) {
  console.log(`Received ${signal}, shutting down gracefully...`);
  try {
    await bot.stop();
  } catch (err) {
    console.error('Error stopping bot:', err);
  }
  // Also disconnect any Telegram clients
  for (const [userId, state] of userState.entries()) {
    if (state.client && state.client.connected) {
      try {
        await state.client.disconnect();
        console.log(`Disconnected client for user ${userId}`);
      } catch (err) {
        console.error(`Error disconnecting client for user ${userId}:`, err);
      }
    }
  }
  process.exit(0);
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

// Launch bot with error handling
bot.launch().then(() => {
  console.log('Bot started successfully');
}).catch(err => {
  console.error('Failed to start bot:', err);
  process.exit(1);
});
