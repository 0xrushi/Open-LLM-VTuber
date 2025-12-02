import asyncio
import edge_tts

TEXT = "Hello, this is a test of the emergency broadcast system."
VOICE = "en-US-AvaMultilingualNeural"
OUTPUT_FILE = "test_tts.mp3"

async def main():
    print(f"Generating TTS for: '{TEXT}' using voice: {VOICE}")
    communicate = edge_tts.Communicate(TEXT, VOICE)
    await communicate.save(OUTPUT_FILE)
    print(f"Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Error: {e}")
