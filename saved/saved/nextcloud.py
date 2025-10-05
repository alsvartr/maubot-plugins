import requests
import json
from aiohttp import BasicAuth

from mautrix.util.async_db import UpgradeTable, Connection

class NextCloud:
    def __init__(self, http_client):
        self.http = http_client

    async def check_auth(self, uri: str, login: str, app_password: str):
        headers = {"OCS-APIRequest": "true"}
        endpoint = f"{uri.rstrip('/')}/ocs/v2.php/cloud/user?format=json"

        async with self.http.get(
            endpoint,
            auth=BasicAuth(login, app_password),
            headers=headers,
            timeout=10
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data["ocs"]["meta"]["status"] == "ok":
                    return True
                return False
            return False

    async def get_auth_link(self, uri: str, ua: str) -> str:
        headers = {"User-Agent": ua}
        endpoint = f"{uri.rstrip('/')}/login/v2"

        async with self.http.post(endpoint, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                self.poll_url = data["poll"]["endpoint"]
                self.token = data["poll"]["token"]
                self.login_url = data["login"]
                return self.login_url
            return None

    async def get_app_password(self) -> str:
        async with self.http.post(self.poll_url, data={"token": self.token}, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["loginName"], data["appPassword"]
            elif resp.status == 404:
                return None, None
            else:
                raise ValueError(f"HTTP {resp.status}")

    async def save_note(self, uri: str, login: str, app_password: str, note_data: dict):
        # note_data = {
        #     "title": "",
        #     "content": "",
        #     "category": "",
        #     "favorite": False
        # }

        headers = {
            "OCS-APIRequest": "true",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        endpoint = f"{uri}/index.php/apps/notes/api/v1/notes"

        try:
            async with self.http.post(
                endpoint,
                headers=headers,
                auth=BasicAuth(login, app_password),
                data=json.dumps(note_data),
                timeout=10
            ) as resp:
                if resp.status == 200:
                    return True, None
                else:
                    error_text = await resp.text()
                    return False, f"HTTP {resp.status_code}: {resp.text}"
        except Exception as e:
            return False, str(e)