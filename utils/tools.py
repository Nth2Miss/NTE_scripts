import time
import random
import os
import json
from typing import Optional, Dict, Any

import cv2
import numpy as np
import win32gui
import win32ui
import win32con
import win32api
import win32process
import ctypes
import psutil

# ============================================
# 全局运行控制与窗口句柄
# ============================================
_IS_RUNNING = True
TARGET_PROCESS_NAME = "HTGame.exe"  # 游戏窗口进程
_TARGET_HWND = None  # 现在存放的是 Win32 的窗口句柄 (HWND)


class StopScriptException(Exception): pass


class TimeoutException(Exception): pass


def set_running_state(state: bool):
    global _IS_RUNNING
    _IS_RUNNING = state


def check_running():
    if not _IS_RUNNING:
        raise StopScriptException("用户请求停止脚本")


def smart_sleep(seconds: float):
    end_time = time.time() + seconds
    while time.time() < end_time:
        check_running()
        time.sleep(min(0.1, end_time - time.time()))


# ============================================
# 配置管理
# ============================================
class ConfigManager:
    DEFAULT_CONFIG = {
        "email_enabled": False, "email_smtp": "smtp.qq.com", "email_port": "465",
        "email_sender": "", "email_pwd": "", "email_receiver": ""
    }

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.data = self.DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.data.update(json.load(f))
            except Exception as e:
                print(f"读取配置失败: {e}")

    def save(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value: Any):
        self.data[key] = value; self.save()


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_mgr = ConfigManager(os.path.join(PROJECT_ROOT, "config.json"))


# ============================================
# 窗口管理与分辨率自适应 (后台化重构)
# ============================================
def find_game_window():
    """通过进程名 (HTGame.exe) 查找对应的真实可见窗口"""
    global _TARGET_HWND
    target_pid = None

    # 1. 遍历当前电脑所有进程，找到 HTGame.exe 的进程 PID
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] and proc.info['name'].lower() == TARGET_PROCESS_NAME.lower():
            target_pid = proc.info['pid']
            break

    if not target_pid:
        return None  # 游戏根本没运行

    hwnds = []

    # 2. 遍历所有窗口，找出 PID 和游戏匹配的那个窗口
    def callback(hwnd, hwnds_list):
        # 必须是肉眼可见的窗口
        if win32gui.IsWindowVisible(hwnd):
            # 获取这个窗口属于哪个进程
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == target_pid:
                # 过滤掉一些游戏底层的无名幽灵窗口
                title = win32gui.GetWindowText(hwnd).strip()
                if title:
                    hwnds_list.append(hwnd)
        return True

    win32gui.EnumWindows(callback, hwnds)

    if hwnds:
        # 如果找到了，取第一个（通常就是主渲染窗口）
        _TARGET_HWND = hwnds[0]
        real_title = win32gui.GetWindowText(_TARGET_HWND)
        print(f"[*] 通过进程 {TARGET_PROCESS_NAME} 锁定成功！游戏真实标题是: '{real_title}'")
        return _TARGET_HWND

    return None


RESOLUTION_CONFIG = {
    "base_width": 1920,  # 开发基准宽度
    "base_height": 1080,  # 开发基准高度
    "curr_width": None,
    "curr_height": None
}


def init_resolution():
    """获取窗口客户区（去掉边框和标题栏后的实际渲染区域）的分辨率"""
    hwnd = find_game_window()
    if hwnd:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        RESOLUTION_CONFIG["curr_width"] = right - left
        RESOLUTION_CONFIG["curr_height"] = bottom - top
        print(f"✅ 游戏窗口锁定 | 客户区分辨率: {right - left}x{bottom - top}")
        return True
    return False


def adapt_coord(x: int, y: int):
    """
    【重要修改】后台发包只需要“相对于窗口客户区”的内部坐标。
    所以这里只做缩放，不再加上窗口在屏幕上的绝对坐标 (left, top)。
    """
    if not RESOLUTION_CONFIG["curr_width"] or not RESOLUTION_CONFIG["curr_height"]:
        return x, y

    scale_x = RESOLUTION_CONFIG["curr_width"] / RESOLUTION_CONFIG["base_width"]
    scale_y = RESOLUTION_CONFIG["curr_height"] / RESOLUTION_CONFIG["base_height"]

    rel_x = int(x * scale_x)
    rel_y = int(y * scale_y)
    return rel_x, rel_y


# ============================================
# PC 后台原生控制与图像识别 (Win32 API)
# ============================================
class PCAutomation:

    @staticmethod
    def capture_screen():
        """使用 PrintWindow 截图（支持遮挡）"""
        hwnd = _TARGET_HWND
        if not hwnd: return None
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0: return None

        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
        saveDC.SelectObject(saveBitMap)

        # 3 = PW_CLIENTONLY | PW_RENDERFULLCONTENT
        ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)

        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        img = np.frombuffer(bmpstr, dtype='uint8')
        img.shape = (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)
        img_cv = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)
        return img_cv

    @staticmethod
    def set_foreground():
        """强制将游戏窗口带到最前台并激活"""
        import win32gui, win32con
        hwnd = _TARGET_HWND
        if hwnd:
            # 如果窗口被最小化了，先恢复它
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            # 强行置顶并夺取焦点
            try:
                # 某些情况下 SetForegroundWindow 会报错，需要先发一个 Alt 键骗过系统
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
                shell.SendKeys('%')  # 发送一次 Alt 键

                win32gui.SetForegroundWindow(hwnd)
                win32gui.BringWindowToTop(hwnd)
                print(">>> 已成功将游戏窗口置于前台")
                time.sleep(0.5)  # 给窗口反应时间
            except Exception as e:
                print(f"⚠️ 无法置顶窗口: {e}")

    @staticmethod
    def click(x: int, y: int, is_actual: bool = False, ui_mode: bool = True, show_log: bool = True):
        """
        后台点击与 UI 闪现模式
        """
        hwnd = _TARGET_HWND
        if not hwnd: return

        if not is_actual:
            rel_x, rel_y = adapt_coord(x, y)
        else:
            rel_x, rel_y = int(x), int(y)

        lparam = win32api.MAKELONG(rel_x, rel_y)

        # 1. 焦点欺骗
        win32gui.SendMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)

        # 2. 物理鼠标闪现 (UI 模式)
        original_pos = None
        if ui_mode:
            try:
                original_pos = win32api.GetCursorPos()
                screen_x, screen_y = win32gui.ClientToScreen(hwnd, (rel_x, rel_y))
                win32api.SetCursorPos((screen_x, screen_y))

                # 【时序优化 1】：确保 Hover 被游戏稳定捕获 (20毫秒)
                time.sleep(0.02)
            except Exception:
                pass

        # 3. 按下与抬起
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)

        # 【时序优化 2】：按压时间固定在 20~30 毫秒之间，足够触发，绝对不会引起长按
        time.sleep(random.uniform(0.02, 0.03))

        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)

        # 4. 鼠标归位
        if ui_mode and original_pos:
            # 【时序优化 3】：
            # 必须等待游戏主线程彻底处理完 LBUTTONUP 消息！
            # 如果不加这个延迟，鼠标瞬间移走就会变成“拖拽滑动”
            time.sleep(0.03)
            try:
                win32api.SetCursorPos(original_pos)
            except Exception:
                pass

        if show_log:
            mode_str = "UI闪现" if ui_mode else "纯后台"
            print(f"后台点击[{mode_str}]: 传入({x}, {y}) -> 客户区({rel_x}, {rel_y})")

    @staticmethod
    def send_key(key: str, show_log: bool = True):
        """纯后台按键（对齐 ok-nte 的 send_key）"""
        hwnd = _TARGET_HWND
        if not hwnd: return

        # 支持单个字母和常见的特殊按键
        key_upper = key.upper()
        if len(key_upper) == 1:
            vk_code = ord(key_upper)
        else:
            # 常见特殊按键映射字典
            special_keys = {
                'SPACE': win32con.VK_SPACE,
                'ENTER': win32con.VK_RETURN,
                'ESC': win32con.VK_ESCAPE,
                'TAB': win32con.VK_TAB,
                'SHIFT': win32con.VK_SHIFT,
                'CTRL': win32con.VK_CONTROL,
                'ALT': win32con.VK_MENU
            }
            vk_code = special_keys.get(key_upper)
            if not vk_code:
                print(f"⚠️ 暂不支持的按键: '{key}'")
                return

        # 1. 焦点欺骗：必须有，否则后台游戏会丢弃键盘输入
        win32gui.SendMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)

        # 2. 发送按下指令
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk_code, 0)

        # 3. 按压时间必须跨越至少 2~3 个游戏渲染帧
        # 0.03 ~ 0.05 秒既能保证 100% 触发，又不会触发长按逻辑
        time.sleep(random.uniform(0.03, 0.05))

        # 4. 发送抬起指令
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk_code, 0)

        if show_log:
            print(f"后台按键: '{key_upper}'")


class ImageMatcher:
    @staticmethod
    def compare_template(screen_bgr, template_path: str, threshold: float = 0.8) -> Dict:
        """模板匹配 """
        template_bgr = cv2.imread(template_path)
        if template_bgr is None:
            raise ValueError(f"无法读取模板图片: {template_path}")

        res = cv2.matchTemplate(cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY),
                                cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY),
                                cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        is_match = max_val >= threshold

        # 计算中心点
        cx = max_loc[0] + template_bgr.shape[1] // 2
        cy = max_loc[1] + template_bgr.shape[0] // 2

        # 【重点】因为我们的截图就是窗口客户区，这里的 cx, cy 已经是窗口内部的相对坐标了！
        # 直接返回，不需要做任何屏幕绝对坐标的转换。

        return {
            "is_match": is_match,
            "max_corr": float(max_val),
            "center_point": (cx, cy) if is_match else None
        }


# ============================================
# 便捷高层 API
# ============================================
def random_sleep(min_time: float, max_time: float = None, variation: float = 0.1):
    check_running()
    if max_time is not None:
        sleep_time = random.uniform(min_time, max_time)
    else:
        base_variation = min_time * variation
        sleep_time = max(0.3, min_time + random.uniform(-base_variation, base_variation * 2))

    print(f"等待 {sleep_time:.2f} 秒")
    smart_sleep(sleep_time)


def execute_screenshot_and_match(template_path: str, threshold: float = 0.8) -> Dict:
    screen_img = PCAutomation.capture_screen()
    if screen_img is None:
        return {"is_match": False}
    return ImageMatcher.compare_template(screen_img, template_path, threshold)


def wait_until_match(template_path: str, timeout: int = 60, raise_err: bool = True, debug: bool = False,
                     threshold: float = 0.8) -> Optional[Dict]:
    print(f"后台等待: {os.path.basename(template_path)} (超时: {timeout}s)...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        check_running()
        res = execute_screenshot_and_match(template_path, threshold)
        if res.get('is_match'):
            return res
        elif debug:
            print(f"  未匹配，最高相似度: {res.get('max_corr', 0):.2f}")
        time.sleep(1.0)

    if raise_err:
        raise TimeoutException(f"等待超时：{timeout}秒内未找到目标 {os.path.basename(template_path)}")
    return None