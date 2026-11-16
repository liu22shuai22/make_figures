"""把注册验证码发到用户邮箱。

环境变量优先，未设置的项目从 smtp.local.json 读取。
这个文件只放在本机，不要提交。
"""
from contextlib import closing, suppress
import json
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from auth import MailDeliveryError, MailNotConfiguredError

CONFIG_PATH = Path(__file__).with_name("smtp.local.json")
logger = logging.getLogger(__name__)

DELIVERY_ERRORS = {
    "connect": "无法连接邮件服务器，请检查后端的网络和代理设置",
    "login": "邮件服务器登录未完成，请检查后端与邮件服务器的连接",
    "send": "邮件服务器未确认接收验证码，请稍后再试",
}


def _text(value) -> str:
    return str(value).strip() if value is not None else ""


def _load_smtp():
    file_config = {}
    if CONFIG_PATH.is_file():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise MailNotConfiguredError from error
        if isinstance(loaded, dict):
            file_config = loaded
    host = _text(os.environ.get("SMTP_HOST") or file_config.get("host"))
    user = _text(os.environ.get("SMTP_USER") or file_config.get("user"))
    password = os.environ.get("SMTP_PASSWORD") or _text(file_config.get("password"))
    if not host or not user or not password:
        raise MailNotConfiguredError
    port_text = _text(os.environ.get("SMTP_PORT") or file_config.get("port") or "465") or "465"
    try:
        port = int(port_text)
    except ValueError as error:
        raise MailNotConfiguredError from error
    sender = _text(os.environ.get("SMTP_FROM") or file_config.get("from")) or user
    ssl_value = os.environ.get("SMTP_SSL")
    if ssl_value is None:
        ssl_value = file_config.get("ssl")
    if ssl_value is None:
        use_ssl = port == 465
    else:
        use_ssl = str(ssl_value).strip().lower() in {"1", "true", "yes"}
    return host, port, user, password, sender, use_ssl


def send_verification_code(email: str, code: str) -> None:
    host, port, user, password, sender, use_ssl = _load_smtp()
    message = EmailMessage()
    message["Subject"] = "ERFlow 注册验证码"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        f"你的 ERFlow 注册验证码是 {code}，10 分钟内有效。\n"
        "如果不是你本人在注册，忽略这封邮件即可。\n"
    )
    stage = "connect"
    try:
        tls_context = ssl.create_default_context()
        connection = (
            smtplib.SMTP_SSL(host, port, timeout=12, context=tls_context)
            if use_ssl else smtplib.SMTP(host, port, timeout=12)
        )
        with closing(connection) as smtp:
            if not use_ssl:
                smtp.starttls(context=tls_context)
            stage = "login"
            smtp.login(user, password)
            stage = "send"
            smtp.send_message(message)
            # SMTP 已接受邮件，退出连接失败不应让验证码写入失败。
            with suppress(OSError):
                smtp.quit()
    except OSError as error:  # SMTPException 也继承 OSError。
        logger.warning("Verification email failed: stage=%s error=%s smtp_code=%s errno=%s",
                       stage, type(error).__name__, getattr(error, "smtp_code", None), error.errno)
        if isinstance(error, smtplib.SMTPAuthenticationError):
            raise MailDeliveryError("邮件服务器拒绝登录，请检查发件邮箱和 SMTP 授权码") from error
        raise MailDeliveryError(DELIVERY_ERRORS[stage]) from error
