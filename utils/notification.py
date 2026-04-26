# -*- coding: utf-8 -*-
from plyer import notification
import smtplib
import threading
from email.mime.text import MIMEText
from email.header import Header
from utils.tools import config_mgr

# 定义通用标题前缀
APP_NAME = "异环 自动化"


def _send_system_core(title, message):
    """
    基础通知发送逻辑（系统右下角弹窗）
    """
    try:
        notification.notify(
            title=title,
            message=message,
            app_icon=None,  # 如果有 .ico 图标文件，可以在此处填写路径，例如 'icon.ico'
            timeout=5,  # 通知显示持续时间（秒）
        )
    except Exception:
        pass  # 忽略系统弹窗可能产生的报错，保持静默


def _send_email_core(subject, content):
    """
    内部方法：核心邮件发送逻辑
    """
    smtp_server = config_mgr.get("email_smtp", "")
    port_str = config_mgr.get("email_port", "465")
    sender = config_mgr.get("email_sender", "")
    password = config_mgr.get("email_pwd", "")
    receiver = config_mgr.get("email_receiver", "")

    if not all([smtp_server, port_str, sender, password, receiver]):
        return False, "邮件配置不完整，请在设置中补全"

    try:
        port = int(port_str)
        msg = MIMEText(content, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = sender
        msg['To'] = receiver

        if port == 465:
            server = smtplib.SMTP_SSL(smtp_server, port)
        else:
            server = smtplib.SMTP(smtp_server, port)
            server.starttls()

        server.login(sender, password)
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()
        return True, "邮件发送成功"
    except Exception as e:
        return False, f"发送失败: {str(e)}"


def send_notification(title, message):
    """
    统一通知触发器：
    1. Windows 系统右下角弹窗 (plyer)
    2. 邮件通知（如果在设置中开启）
    """
    # 1. 触发 Windows 弹窗
    _send_system_core(title, message)

    # 2. 触发邮件通知
    if config_mgr.get("email_enabled", False):
        # 注意：这里直接调用同步方法 _send_email_core 并返回它的结果
        # 因为调用这个函数的地方（如 gui_main.py 的 worker）通常已经在子线程里了
        return _send_email_core(title, message)

    return True, "系统弹窗已发送（邮件通知未开启）"


def send_success(count):
    """
    发送运行成功通知
    :param count: 运行的次数
    """
    title = f"{APP_NAME} - 运行完成"
    message = f"脚本执行成功！\n当前累计运行次数：{count} 次"
    send_notification(title, message)


def send_failure(error_msg="未知错误"):
    """
    发送运行失败/报错通知
    :param error_msg: 具体的错误信息
    """
    title = f"{APP_NAME} - 运行出错"
    message = f"脚本异常终止。\n原因：{error_msg}"
    send_notification(title, message)