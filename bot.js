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

// Store user state (only one admin, but we support multiple for completeness)
const userState = new Map(); // key: userId

// Helper to get or create state
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

// Middleware to check if user is admin
bot.use((ctx, next) => {
  if (ctx.from && ctx.from.id === ADMIN_ID) {
    return next();
  }
  // ignore non-admin
  return;
});

// /start command
bot.start(async (ctx) => {
  const state = getState(ctx.from.id);
  state.step = 'awaiting_phone';
  await ctx.reply(
    'Welcome! To begin, please send me your phone number in international format (e.g., +918002591484).'
  );
});

// Handle text messages
bot.on('text', async (ctx) => {
  const userId = ctx.from.id;
  const state = getState(userId);
  const text = ctx.message.text;

  try {
    if (state.step === 'awaiting_phone') {
      // User sent phone number
      const phone = text.trim();
      state.phone = phone;

      // Create a new Telegram client for this user
      const client = new TelegramClient(new StringSession(''), API_ID, API_HASH, {
        connectionRetries: 5,
      });
      state.client = client;

      await ctx.reply('Sending OTP to your Telegram app...');

      // Send code request
      const sendCodeResult = await client.sendCode(
        {
          apiId: API_ID,
          apiHash: API_HASH,
        },
        phone
      );
      state.phoneCodeHash = sendCodeResult.phoneCodeHash;

      state.step = 'awaiting_code';
      await ctx.reply('OTP sent! Please enter the code you received:');
    } 
    else if (state.step === 'awaiting_code') {
      // User sent OTP code
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
          // 2FA enabled
          state.step = 'awaiting_2fa';
          await ctx.reply('Two‑factor authentication is enabled. Please enter your password:');
          return;
        }
        throw error;
      }

      // Login successful
      await handleSuccessfulLogin(ctx, state, client);
    } 
    else if (state.step === 'awaiting_2fa') {
      // User sent 2FA password
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
      // User sent channel ID or username
      const channelInput = text.trim();
      const client = state.client;

      try {
        // Resolve channel
        let chat;
        if (channelInput.startsWith('-100') || /^-?\d+$/.test(channelInput)) {
          // Numeric ID
          chat = await client.getEntity(channelInput);
        } else {
          // Username
          chat = await client.getEntity(channelInput);
        }

        // Check if user is admin with invite permissions
        const me = await client.getMe();
        const participant = await client.getParticipant(chat, me);
        const isAdmin = participant && (participant instanceof Api.ChannelParticipantAdmin || participant instanceof Api.ChannelParticipantCreator);
        if (!isAdmin) {
          await ctx.reply('❌ You are not an admin in that channel. Please make sure you are an admin with "Add Members" permission.');
          return;
        }

        // Check for invite permission (optional)
        if (participant.adminRights && !participant.adminRights.inviteUsers) {
          await ctx.reply('❌ You lack the "Add Members" admin right. Please grant it and try again.');
          return;
        }

        state.channelId = chat.id;
        state.step = 'idle';
        await ctx.reply(`✅ Channel ${chat.title} (ID: ${chat.id}) set. Now starting approval process...`);

        // Start the approval process (backfill + listener)
        startApprovalForUser(userId, ctx);

      } catch (error) {
        console.error('Channel resolution error:', error);
        await ctx.reply('❌ Could not find that channel or access it. Please check the ID/username and ensure I am an admin there.');
      }
    } 
    else {
      await ctx.reply('Please use /start to begin.');
    }
  } catch (error) {
    console.error('Error in message handler:', error);
    await ctx.reply('An error occurred: ' + error.message);
  }
});

// Helper after successful login
async function handleSuccessfulLogin(ctx, state, client) {
  // Save session string
  const sessionString = client.session.save();
  state.sessionString = sessionString;

  await ctx.reply('✅ Login successful! Now, please send me the channel ID or username (e.g., @FocketTricks or -1001234567890).');
  state.step = 'awaiting_channel';
}

// Approval process
async function startApprovalForUser(userId, ctx) {
  const state = getState(userId);
  if (state.isApproving) return;
  state.isApproving = true;

  const client = state.client;
  const channelId = state.channelId;

  // Run backfill in background
  (async () => {
    try {
      await ctx.reply('🔄 Fetching all pending join requests...');
      let count = 0;
      let errors = 0;

      // Get chat title
      const chat = await client.getEntity(channelId);
      const chatTitle = chat.title || 'Unknown';

      // Use the getChatJoinRequests method
      const requestsIter = client.getChatJoinRequests(channelId, { limit: 100 });

      for await (const req of requestsIter) {
        try {
          // Approve the request
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
          // Small delay to avoid flood
          await new Promise(resolve => setTimeout(resolve, 200));
        } catch (e) {
          if (e.errorMessage === 'FLOOD_WAIT') {
            const seconds = e.seconds || 5;
            console.log(`Flood wait, sleeping ${seconds}s`);
            await new Promise(resolve => setTimeout(resolve, seconds * 1000));
            // retry once
            try {
              await client.invoke(
                new Api.messages.ApproveChatJoinRequest({
                  peer: channelId,
                  userId: req.userId,
                })
              );
              count++;
            } catch (retryErr) {
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
      await ctx.reply('❌ Error during backfill: ' + error.message);
    } finally {
      state.isApproving = false;
    }
  })();

  // Set up a handler for new join requests (real-time)
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

// Launch bot
bot.launch().then(() => {
  console.log('Bot started');
}).catch(err => {
  console.error('Failed to start bot:', err);
  process.exit(1);
});

// Enable graceful stop
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
