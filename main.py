import os
import asyncio

from loguru import logger
from colorama import init, Fore

from converter import TGConverter
from config import BANNER, API_HASH, API_ID
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from tgdumper import TGDumper

init(autoreset=True)


def inpt(text=None):
    if text:
        print(text)

    return input(Fore.MAGENTA + "❯ ")


async def main():
    print(BANNER)

    if not API_HASH or not API_ID:
        logger.error("API_HASH or API_ID is not set")
        exit()

    mode = inpt(
        f"""
{Fore.CYAN}Choose a mode:{Fore.RESET}
[1] - {Fore.YELLOW}Convert tdata to string session{Fore.RESET}
[2] - {Fore.YELLOW}Convert session to tdata{Fore.RESET}
[3] - {Fore.YELLOW}Dump dialog or group chat{Fore.RESET}
"""
    )

    tg_converter = TGConverter(API_ID, API_HASH)

    if mode == "1":
        tdatas_path = inpt("Choose the folder where tdatas are located:")

        if os.path.exists(tdatas_path) is None:
            logger.error("Invalid path")
            exit()

        try:
            for tdata_folder in os.listdir(tdatas_path):
                await tg_converter.tdata_to_string(tdatas_path + "/" + tdata_folder)
        except Exception as err:
            logger.error(err)
        else:
            logger.success("All tdatas converted")
            logger.info("You can find session data in the 'sessions_sessions' folder")

    elif mode == "2":
        sessions_path = inpt("Choose the folder where session files are located:")

        if os.path.exists(sessions_path) is None:
            logger.error("Invalid path")
            exit()

        try:
            for session_file in os.listdir(sessions_path):
                await tg_converter.session_to_tdata(sessions_path + "/" + session_file)
        except Exception as err:
            logger.error(err)
        else:
            logger.success("All sessions converted")
            logger.info("You can find tdata data in the 'tdata_converted' folder")

    elif mode == "3":
        session_mode = inpt(
            f"""
Choose session mode:{Fore.RESET}
[1] - {Fore.YELLOW}String Session from .txt{Fore.RESET}
[2] - {Fore.YELLOW}.session File Session{Fore.RESET}
"""
        )

        if session_mode == "1":
            session_file = inpt("Enter path to .txt string session: ")
        elif session_mode == "2":
            session_file = inpt("Enter path to .session file: ")
        else:
            logger.error("Invalid mode")
            exit()

        if os.path.exists(session_file):
            if session_file.endswith(".txt"):
                with open(session_file, "r") as f:
                    auth_key = f.read().strip().replace("\n", "")
                session = StringSession(auth_key)
            elif session_file.endswith(".session"):
                session = session_file
            else:
                logger.error("Invalid session file")
                exit()

            messages_limit = inpt(
                "Enter number of messages to download (enter to download all): "
            )
            messages_limit = int(messages_limit) if messages_limit else None

            photo_download = inpt("Download photos from chat? (y/n): ").lower() == "y"
            video_download = inpt("Download videos from chat? (y/n): ").lower() == "y"
            voice_download = inpt("Download voice messages? (y/n): ").lower() == "y"

            client = TelegramClient(session, API_ID, API_HASH)
            dumper = TGDumper(client)
            
            async with client:
                await dumper.export_dialog(
                    messages_limit, photo_download, video_download, voice_download
                )
                
            logger.success("Dialog exported check 'web' folder")
        else:
            logger.error("Session file not found.")
            exit()
    else:
        logger.error("Invalid mode")


if __name__ == "__main__":
    asyncio.run(main())
