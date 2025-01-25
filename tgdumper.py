import os

from telethon import TelegramClient
from telethon.tl.types import User, PeerUser, Chat
from telethon.sessions import StringSession
from loguru import logger
from tqdm import tqdm


class TGDumper:
    def __init__(self, client):
        self.client = client

    async def export_dialog(
        self, messages_limit, photo_download, video_download, voice_download
    ):
        user_list = []

        # Create directories for web, img, and video
        os.makedirs("web/img", exist_ok=True)
        os.makedirs("web/video", exist_ok=True)
        os.makedirs("web/voice", exist_ok=True)

        # Fetch dialogs and display them
        logger.info("Fetching dialogs...")
        dialogs = await self.client.get_dialogs()  # Get all dialogs
        index = 0

        chat_type = input("Select chat type (1 for personal messages, 2 for groups): ")

        for i, dialog in enumerate(dialogs):
            entity = dialog.entity
            if chat_type == "1" and isinstance(entity, User) and not entity.bot:
                user_list.append(entity)
                logger.info(
                    f"User found: [{index}] {entity.first_name} {entity.last_name} (@{entity.username})"
                )
                index += 1
            elif chat_type == "2" and isinstance(entity, Chat):
                user_list.append(entity)
                logger.info(f"Group found: [{index}] {entity.title}")
                index += 1
        # Choose a user or group
        user_choice = int(
            input("Select a user/group by number: ")
        )  # Change to -1 for correct index

        if user_choice < 0 or user_choice >= len(user_list):
            logger.error("Invalid selection. Please select a valid number.")
            return  # Exit main function if selection is invalid

        selected_chat = user_list[user_choice]
        logger.info(
            f"Selected chat: {selected_chat.title if isinstance(selected_chat, Chat) else selected_chat.first_name}"
        )

        UserData = {
            "first_name": (
                selected_chat.first_name
                if isinstance(selected_chat, User)
                else selected_chat.title
            ),
            "last_name": (
                selected_chat.last_name if isinstance(selected_chat, User) else ""
            ),
            "username": (
                selected_chat.username if isinstance(selected_chat, User) else ""
            ),
            "messages": [],
        }

        peer = (
            PeerUser(selected_chat.id)
            if isinstance(selected_chat, User)
            else selected_chat
        )

        # Fetch messages
        logger.info(f"Fetching messages for {UserData['first_name']}...")
        messages = await self.client.get_messages(
            peer, limit=messages_limit
        )  # Fetch all messages

        # Create the initial HTML structure
        self._create_html_file(UserData)

        # Use tqdm to show progress
        for message in tqdm(messages, desc="Downloading messages", unit="message"):
            # Get sender information
            sender = (
                await self.client.get_entity(message.sender_id)
                if message.sender_id
                else None
            )
            sender_name = sender.first_name if sender else "Unknown"

            msg_data = {
                "id": message.id,
                "text": message.text,
                "sender": sender_name,  # Use sender's name
                "date": message.date.strftime("%Y-%m-%d %H:%M:%S"),  # Add sending time
            }

            if message.media:
                if message.photo and photo_download:
                    try:
                        # If the message contains a photo, download it
                        file_path = await message.download_media(file="web/img/")
                        msg_data["media"] = file_path.replace("web/", "")
                        logger.info(f"Downloaded photo for message ID: {message.id}")
                    except Exception as err:
                        logger.error(err)
                elif message.video and video_download:
                    # If the message contains a video, download it
                    try:
                        file_path = await message.download_media(file="web/video/")
                        msg_data["media"] = file_path.replace("web/", "")
                        logger.info(f"Downloaded video for message ID: {message.id}")
                    except Exception as err:
                        logger.error(err)
                elif message.voice and voice_download:
                    try:
                        # If the message contains a voice message, download it
                        file_path = await message.download_media(file="web/voice/")
                        msg_data["media"] = file_path.replace("web/", "")
                        logger.info(
                            f"Downloaded voice message for message ID: {message.id}"
                        )
                    except Exception as err:
                        logger.error(err)

            UserData["messages"].append(msg_data)

            # Save each message to HTML
            self._save_message_to_html(msg_data)

        logger.info("All messages processed successfully.")

    def _create_html_file(self, user_data):
        # Create the initial HTML structure
        html_content = f"""
        <html>
            <head>
            <title>Chat with {user_data['first_name']} {user_data['last_name']}</title>
            <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
            <style>
                body {{
                    background-color: #343a40; /* Dark background */
                    color: #ffffff; /* White text */
                }}
                .chat-container {{
                    max-width: 600px;
                    margin: auto;
                    padding: 20px;
                    border: 1px solid #495057; /* Border color */
                    border-radius: 5px;
                    background-color: #212529; /* Dark background for container */
                }}
                .message {{
                    margin-bottom: 15px;
                    background-color: #495057; /* Background color for message */
                    padding: 10px;
                    border-radius: 5px;
                }}
                .message p {{
                    margin: 0;
                    color: #ffffff; /* White text for message */
                }}
                .message img, .message video, .message audio {{
                    max-width: 100%;
                    height: auto;
                }}
                strong {{
                    color: #ffc107; /* Color for sender's name */
                }}
                .timestamp {{
                    font-size: 0.8em;
                    color: #adb5bd; /* Color for timestamp */
                }}
            </style>
        </head>
        <body>
            <div class="chat-container">
                <h1>Chat with {user_data['first_name']} {user_data['last_name']} (@{user_data['username']})</h1>
        """
        # Save the initial HTML structure to the file
        with open("web/chat_export.html", "w", encoding="UTF-8") as file:
            file.write(html_content)

    def _save_message_to_html(self, message):
        # Append each message to the HTML file
        with open("web/chat_export.html", "a", encoding="UTF-8") as file:
            file.write(
                f"""
                <div class="message">
                    <strong>{message['sender']}:</strong>
                    <p>{message['text']}</p>
                    <span class="timestamp">{message['date']}</span>
            """
            )
            if "media" in message:
                if message["media"].endswith((".jpg", ".jpeg", ".png")):
                    file.write(f'<img src="{message["media"]}" alt="Image"><br>')
                elif message["media"].endswith((".mp4", ".mov")):
                    file.write(
                        f'<video controls><source src="{message["media"]}" type="video/mp4">Your browser does not support the video tag.</video><br>'
                    )
                elif message["media"].endswith(
                    (".ogg", ".mp3", ".wav", ".m4a", ".oga", ".aiff")
                ):  # Check for audio files
                    file.write(
                        f'<audio controls><source src="{message["media"]}" type="audio/ogg">Your browser does not support the audio tag.</audio><br>'
                    )
            file.write("</div>")
