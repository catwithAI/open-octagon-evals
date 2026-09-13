"""Optional Feishu notification adapter; credentials are always supplied at runtime."""
from __future__ import annotations
import json, os
from dataclasses import dataclass
from urllib.request import Request, urlopen

@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str
    base_url: str = "https://open.feishu.cn"

    @classmethod
    def from_env(cls) -> "FeishuConfig":
        app_id, secret = os.getenv("FEISHU_APP_ID"), os.getenv("FEISHU_APP_SECRET")
        if not app_id or not secret: raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET are required")
        return cls(app_id, secret, os.getenv("FEISHU_BASE_URL", cls.base_url))

class FeishuClient:
    def __init__(self, config: FeishuConfig, opener=urlopen): self.config, self.opener, self._token = config, opener, None
    def tenant_access_token(self) -> str:
        if self._token: return self._token
        req=Request(self.config.base_url + "/open-apis/auth/v3/tenant_access_token/internal", data=json.dumps({"app_id":self.config.app_id,"app_secret":self.config.app_secret}).encode(), headers={"Content-Type":"application/json"}, method="POST")
        with self.opener(req) as response: payload=json.loads(response.read())
        if payload.get("code", 0) != 0 or not payload.get("tenant_access_token"): raise RuntimeError(f"Feishu auth failed: {payload.get('msg','unknown error')}")
        self._token=payload["tenant_access_token"]; return self._token
    def send_text(self, receive_id: str, text: str, receive_id_type="open_id") -> dict:
        body={"receive_id":receive_id,"msg_type":"text","content":json.dumps({"text":text})}
        req=Request(self.config.base_url + f"/open-apis/im/v1/messages?receive_id_type={receive_id_type}", data=json.dumps(body).encode(), headers={"Content-Type":"application/json","Authorization":"Bearer " + self.tenant_access_token()}, method="POST")
        with self.opener(req) as response: payload=json.loads(response.read())
        if payload.get("code", 0) != 0: raise RuntimeError(f"Feishu send failed: {payload.get('msg','unknown error')}")
        return payload
