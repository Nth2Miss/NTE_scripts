import subprocess
import os
import sys
import ctypes
import hashlib
import requests
import json
import time

# ==================== 配置区 ====================
# 远程 version.json 的地址
MANIFEST_URL = "https://gitee.com/Nth2Miss/nte-update/raw/master/version.json"

# 定义允许自动清理的本地目录
MANAGED_DIRS = ['utils', 'scripts', 'templates', 'assets']


# ===============================================

class Logger(object):
    """日志重定向类：同时将输出发送到控制台（如果存在）和文件"""

    def __init__(self, filename="launcher_log.txt"):
        self.terminal = sys.stdout
        # 'w' 模式每次启动清空旧日志
        self.log = open(filename, "w", encoding="utf-8", buffering=1)

    def write(self, message):
        # 兼容无窗口模式：当 sys.stdout 为 None 时不执行 terminal.write
        if self.terminal:
            try:
                self.terminal.write(message)
            except:
                pass
        if self.log:
            self.log.write(message)

    def flush(self):
        if self.terminal:
            try:
                self.terminal.flush()
            except:
                pass
        if self.log:
            self.log.flush()


def get_root_path():
    """获取当前程序所在的绝对路径"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_file_hash(filepath):
    """计算本地文件的 MD5 值"""
    if not os.path.exists(filepath):
        return None
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def cleanup_unused_files(remote_files_dict):
    """清理本地存在但清单中没有的文件"""
    root = get_root_path()
    print(f"[{time.strftime('%H:%M:%S')}] >>> 正在检查过期文件...")

    for folder in MANAGED_DIRS:
        folder_path = os.path.join(root, folder)
        if not os.path.exists(folder_path):
            continue

        for root_dir, _, files in os.walk(folder_path):
            for file in files:
                abs_path = os.path.join(root_dir, file)
                rel_path = os.path.relpath(abs_path, root).replace("\\", "/")

                # 如果这个本地文件不在远程清单里且在管理目录内，执行删除
                if rel_path not in remote_files_dict:
                    print(f"    [!] 清除过期文件: {rel_path}")
                    try:
                        os.remove(abs_path)
                    except Exception as e:
                        print(f"    [X] 清除失败: {e}")


def update_and_sync():
    """核心更新逻辑：增量下载、依赖同步、自更新"""
    root = get_root_path()
    python_exe = os.path.join(root, "Python", "python.exe")
    req_file = os.path.join(root, "requirements.txt")

    print(f"[{time.strftime('%H:%M:%S')}] >>> 正在检查在线更新...")
    try:
        resp = requests.get(MANIFEST_URL, timeout=5)
        if resp.status_code != 200:
            print(f"    [X] 无法连接服务器 (Code: {resp.status_code})")
            return

        remote_manifest = resp.json()
        base_url = remote_manifest.get("base_url", "")
        if base_url and not base_url.endswith('/'):
            base_url += '/'

        files_to_update = remote_manifest.get("files", {})

        need_pip_sync = False
        self_update_path = None

        for rel_path, remote_info in files_to_update.items():
            local_path = os.path.join(root, rel_path)

            # 支持清单中直接写哈希字符串，或写包含 hash 和 url 的对象（应对 Gitee 大文件限制）
            if isinstance(remote_info, dict):
                remote_hash = remote_info.get("hash")
                download_url = remote_info.get("url")
            else:
                remote_hash = remote_info
                download_url = base_url + rel_path

            # 比对本地和远程哈希
            if get_file_hash(local_path) != remote_hash:
                print(f"    [+] 下载更新: {rel_path}")

                if not download_url or "REPLACE_ME" in download_url:
                    print(f"    [X] 跳过: {rel_path} 的下载地址未配置。")
                    continue

                # 下载文件
                f_resp = requests.get(download_url, timeout=15)
                if f_resp.status_code != 200:
                    print(f"    [X] 下载失败: {rel_path} ({f_resp.status_code})")
                    continue

                # Gitee 安全校验：检查是否下载到了登录页 HTML
                content_sample = f_resp.content[:100].decode('utf-8', errors='ignore').lower()
                if rel_path.endswith('.exe') and ("<html" in content_sample or "doctype html" in content_sample):
                    print(f"    [X] 错误: {rel_path} 被服务器拦截（可能是 Gitee 1MB 限制）。")
                    continue

                # 写入文件（启动器自身先写为 .new 以免被占用）
                save_path = local_path + ".new" if rel_path.lower() == "launcher.exe" else local_path
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(f_resp.content)

                # 判定自更新准备
                if rel_path.lower() == "launcher.exe" and getattr(sys, 'frozen', False):
                    if get_file_hash(save_path) == remote_hash:
                        self_update_path = local_path
                    else:
                        print(f"    [X] 校验失败: {rel_path} 下载不完整。")

                if rel_path == "requirements.txt":
                    need_pip_sync = True

        # 清理过期文件
        cleanup_unused_files(files_to_update)

        # 执行自更新重启逻辑
        if self_update_path:
            print(">>> 启动器已更新，准备重启...")
            bat_path = os.path.join(root, "replace_launcher.bat")
            exe_name = os.path.basename(self_update_path)

            # 修改后的 .bat 内容
            # 1. setlocal & set _MEIPASS= : 清除环境变量，防止新程序寻找旧的 Temp 路径
            # 2. cd /d "{root}" : 确保在程序根目录操作
            # 3. start "" "{exe_name}" : 启动时不带路径，让它根据当前目录启动
            with open(bat_path, "w", encoding="gbk") as f:  # Windows 批处理建议用 gbk
                f.write(f"""@echo off
        setlocal
        cd /d "{root}"
        timeout /t 1 /nobreak >nul

        :loop
        taskkill /f /im "{exe_name}" >nul 2>&1
        timeout /t 1 /nobreak >nul
        if exist "{exe_name}" (
            del /f /q "{exe_name}"
            if exist "{exe_name}" goto loop
        )

        if exist "{exe_name}.new" (
            ren "{exe_name}.new" "{exe_name}"
        )

        :: 清除 PyInstaller 的临时环境变量，这是解决 DLL 报错的关键
        set _MEIPASS=
        start "" "{exe_name}"

        :: 自删除批处理
        del "%~f0"
        """)
            # 使用 detached 模式启动批处理
            subprocess.Popen(f'start /min "" "{bat_path}"', shell=True)
            sys.exit(0)

        # 同步第三方库依赖
        if need_pip_sync and os.path.exists(python_exe):
            print(">>> 发现依赖变动，正在同步本地环境...")
            subprocess.run([python_exe, "-m", "pip", "install", "-r", req_file, "--quiet"], check=True)
            print(">>> 依赖库同步完成。")

    except Exception as e:
        print(f"更新失败: {str(e)}")


def run_main():
    """启动主 GUI 程序"""
    print(">>> 启动器已启动 1.0.1")
    root = get_root_path()
    venv_pythonw = os.path.join(root, "Python", "pythonw.exe")
    main_script = os.path.join(root, "gui_main.py")

    if not os.path.exists(venv_pythonw):
        ctypes.windll.user32.MessageBoxW(0, f"环境缺失：\n{venv_pythonw}", "启动错误", 0x10)
        return

    print(f"[{time.strftime('%H:%M:%S')}] >>> 正在唤起主程序...")
    try:
        subprocess.Popen([venv_pythonw, main_script], cwd=root)
    except Exception as e:
        print(f"主程序启动失败: {str(e)}")


if __name__ == "__main__":
    # 初始化日志系统
    log_file_path = os.path.join(get_root_path(), "launcher_log.txt")
    sys.stdout = Logger(log_file_path)
    sys.stderr = sys.stdout

    print("========================================")
    print(f"启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    update_and_sync()
    run_main()