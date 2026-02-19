from pyrogram import Client

API_ID = 33277483                # Your API ID
API_HASH = "65b9f007d9d208b99519c52ce89d3a2a"   # Your API hash
PHONE_NUMBER = "+918002591484"   # Your phone number with country code

async def main():
    async with Client(":memory:", api_id=API_ID, api_hash=API_HASH, phone_number=PHONE_NUMBER) as app:
        session_string = await app.export_session_string()
        print("\n✅ Your session string (copy it now):\n")
        print(session_string)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
