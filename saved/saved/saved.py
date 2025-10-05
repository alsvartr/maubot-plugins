from typing import Optional, Tuple, Any, Type
import time
from html import escape

from mautrix.types import TextMessageEventContent, MessageType, Format, RelatesTo, RelationType

from maubot import Plugin, MessageEvent
from maubot.handlers import command

from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from maubot import Plugin, MessageEvent
from maubot.handlers import command

from mautrix.util.async_db import UpgradeTable, Connection

import urllib.parse

from .nextcloud import *

upgrade_table = UpgradeTable()

@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute(
        """CREATE TABLE app_passwords (
            uid TEXT NOT NULL UNIQUE PRIMARY KEY,
            uri TEXT NOT NULL,
            login TEXT NOT NULL,
            password TEXT NOT NULL
        )"""
    )

def non_empty_string(x: str) -> Tuple[str, Any]:
    if not x:
        return x, None
    return "", x

class Config(BaseProxyConfig):
  def do_update(self, helper: ConfigUpdateHelper) -> None:
    helper.copy("nextcloud_url")
    helper.copy("app_name")
    helper.copy("title_prefix")
    helper.copy("categories")

class SavedBot(Plugin):
    async def start(self) -> None:
        await super().start()
        self.config.load_and_update()
        self.nextcloud = NextCloud(self.http)

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config

    @classmethod
    def get_db_upgrade_table(cls) -> UpgradeTable | None:
        return upgrade_table

    @command.new("check", help="Check nextcloud auth")
    async def check_handler(self, evt: MessageEvent) -> None:
        uri, login, app_password = await self.load_app_password(evt.sender)
        res = False
        if app_password != None:
            if await self.nextcloud.check_auth(uri, login, app_password):
                res = True
                
        if res:
            await evt.reply(f"✅ Nextcloud connected")
        else:
            await evt.reply(f"❌ Nextcloud not connected")

    @command.new("auth", help="Auth to nextcloud instance")
    @command.argument("url", pass_raw=True, required=False)
    async def auth_handler(self, evt: MessageEvent, url: str) -> None:
        if not self.config["nextcloud_url"] and not url:
            await evt.reply("Usage: '!auth https://cloud.example.com'")
            return None

        nc_url = self.config["nextcloud_url"] or url

        auth_link = await self.nextcloud.get_auth_link(nc_url, self.config["app_name"])
        if auth_link == None:
            await evt.reply(f"Error getting auth link, check bot logs")
            return None
        else:
            await evt.reply(
                f"Follow this link to create nextcloud app password:\n\n {auth_link}\n\n"
                "⏳Bot will wait for 5 minutes!"
            )

        start = time.time()
        while time.time() - start < 300:
            try:
                login, app_password = await self.nextcloud.get_app_password()
                if app_password == None:
                    time.sleep(1)
                    continue
                else:
                    await self.save_app_password(evt.sender, nc_url, login, app_password)
                    await evt.reply("✅ Sucessfully connected")
                    break
            except ValueError as e:
                await evt.reply(f"❌ Error: {e}")
        else:
            await evt.reply(f"⚠️ Timeout wating for app password, giving up")

    @command.new("n", help="Save note")
    @command.argument("message", pass_raw=True, required=True, parser=non_empty_string)
    async def note_handler(self, evt: MessageEvent, message: str) -> None:
        uri, login, app_password = await self.load_app_password(evt.sender)
        if app_password == None:
            await evt.reply("Nextcloud not connected, use auth command to authorize")
            return None

        if not await self.nextcloud.check_auth(uri, login, app_password):
            await evt.reply("Nextcloud auth failed, rerun auth command or check nextcloud logs")
            return None

        content, title = self.parse_title(message)
        prefix = self.config["title_prefix"]
        if prefix:
            title = f"{prefix} {title}"

        for item in self.config["categories"]:
            if content in item:
                category = item[content]
                break

        note_data = {
            "title": title,
            "content": message,
            "category": category,
            "favorite": False
        }
        result, error = await self.nextcloud.save_note(uri, login, app_password, note_data)

        if result == True:
            await evt.reply(f"Note saved as '{title}' in '{category}'")
        else:
            await evt.reply(f"Error saving note: {error}")

    def parse_title(self, body: str):
        body = body.strip()
        if body.startswith(("http://", "https://")):
            content = "link"
            parsed = urllib.parse.urlparse(body)
            domain = parsed.netloc
            path = (parsed.path + ('?' + parsed.query if parsed.query else ''))[:6]
            if path:
                title = f"{domain} - {path}..."
            else:
                title = domain
        else:
            content = "text"
            title = body.split('\n')[0][:30]
        
        return content, title

    async def save_app_password(self, uid: str, uri: str, login: str, app_password: str) -> None:
        q = """
            INSERT INTO app_passwords (uid, uri, login, password) VALUES ($1, $2, $3, $4)
            ON CONFLICT (uid) DO UPDATE SET uri=excluded.uri, password=excluded.password
        """
        await self.database.execute(q, uid, uri, login, app_password)

    async def load_app_password(self, uid: str):
        q = "SELECT uri, login, password FROM app_passwords WHERE uid=$1"
        row = await self.database.fetchrow(q, uid)
        if row:
            return row["uri"], row["login"], row["password"]
        else:
            return None, None, None