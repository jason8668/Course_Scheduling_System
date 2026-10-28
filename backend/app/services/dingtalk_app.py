"""钉钉企业内部应用:工作通知一对一推送(个人上课提醒)。

与群机器人 webhook 不同:这条路发的是「工作通知」,只能由企业内部应用发出,
收件人是企业通讯录里的 userid。学校钉钉管理员建好应用并授权(工作通知 +
通讯录读取)后,管理员把 appKey/appSecret/agentId 填进系统管理。

调用链:access_token(2 小时有效,一次任务只取一次) →
按手机号查 userid(查到即缓存到教师档案,下次不再查) →
asyncsend_v2 发 markdown 工作通知。任何一步失败都只记日志、
由呼叫端决定跳过,绝不影响站内通知与课务流程。
"""

import logging
import re

logger = logging.getLogger(__name__)

_OAPI = "https://oapi.dingtalk.com"


def _check(payload: dict, what: str) -> dict:
    if payload.get("errcode") != 0:
        raise RuntimeError(f"钉钉{what}失败:{payload.get('errmsg', payload)}")
    return payload


def normalize_mobile(mobile: str) -> str:
    """手机号归一化:去空格/横杠,去 +86 前缀,供 getbymobile 使用。"""
    digits = re.sub(r"[\s\-]", "", mobile or "")
    if digits.startswith("+86"):
        digits = digits[3:]
    elif len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits


class DingTalkAppClient:
    """一次任务共用一个实例:token 只取一次,多位老师共用。"""

    def __init__(self, app_key: str, app_secret: str, agent_id: str) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        try:
            self._agent_id = int(agent_id)
        except (TypeError, ValueError):
            raise ValueError("钉钉 agentId 应为数字") from None
        self._token: str | None = None

    @property
    def token(self) -> str:
        if self._token is None:
            import httpx

            resp = httpx.get(
                f"{_OAPI}/gettoken",
                params={"appkey": self._app_key, "appsecret": self._app_secret},
                timeout=5.0,
            )
            resp.raise_for_status()
            self._token = str(_check(resp.json(), "取 access_token")["access_token"])
        return self._token

    def get_userid(self, mobile: str) -> str | None:
        """按手机号查企业内 userid;查不到(不在通讯录)回 None,不掷错。"""
        import httpx

        mobile = normalize_mobile(mobile)
        if not mobile:
            return None
        try:
            resp = httpx.post(
                f"{_OAPI}/topapi/v2/user/getbymobile",
                params={"access_token": self.token},
                json={"mobile": mobile},
                timeout=5.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - 查不到就跳过该老师,任务继续
            logger.warning("钉钉按手机号查 userid 失败(%s):%s", mobile, exc)
            return None
        if payload.get("errcode") != 0:
            logger.warning(
                "钉钉按手机号查不到 userid(%s):%s", mobile, payload.get("errmsg", payload)
            )
            return None
        return str(payload["result"]["userid"])

    def send_work_notification(self, userid: str, title: str, text: str) -> None:
        """发一则 markdown 工作通知;失败掷出例外(由呼叫端记日志并跳过)。"""
        import httpx

        resp = httpx.post(
            f"{_OAPI}/topapi/message/corpconversation/asyncsend_v2",
            params={"access_token": self.token},
            json={
                "agent_id": self._agent_id,
                "userid_list": userid,
                "msg": {"msgtype": "markdown", "markdown": {"title": title, "text": text}},
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        _check(resp.json(), "发工作通知")
