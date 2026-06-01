import time
import random
import os
import json
import re
from typing import Optional, Dict, Any

import cv2
import numpy as np
import win32gui
import win32ui
import win32con
import win32api
import win32process
import ctypes
import platform
import psutil
import threading
import pytesseract
from PIL import Image

# 强制开启系统的 DPI 感知，获取真实的物理分辨率
try:
    if platform.release() == '10' or platform.release() == '11':
        ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per Monitor DPI Aware
    else:
        ctypes.windll.user32.SetProcessDPIAware()
except Exception as e:
    print(f"⚠️ 设置 DPI 感知失败: {e}")

# ============================================
# 全局运行控制与窗口句柄
# ============================================
_IS_RUNNING = True
TARGET_PROCESS_NAME = "HTGame.exe"  # 游戏窗口进程
_TARGET_HWND = None  # 现在存放的是 Win32 的窗口句柄 (HWND)

# 配置分辨率
RESOLUTION_CONFIG = {
    "base_width": 2560,
    "base_height": 1440,
    "curr_width": None,
    "curr_height": None
}


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

    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] and proc.info['name'].lower() == TARGET_PROCESS_NAME.lower():
            target_pid = proc.info['pid']
            break

    if not target_pid:
        return None

    hwnds = []

    def callback(hwnd, hwnds_list):
        if win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == target_pid:
                title = win32gui.GetWindowText(hwnd).strip()
                if title:
                    hwnds_list.append(hwnd)
        return True

    win32gui.EnumWindows(callback, hwnds)

    if hwnds:
        _TARGET_HWND = hwnds[0]
        real_title = win32gui.GetWindowText(_TARGET_HWND)
        print(f"[*] 通过进程 {TARGET_PROCESS_NAME} 锁定成功！")
        return _TARGET_HWND

    return None


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
    后台发包只需要“相对于窗口客户区”的内部坐标。
    只做缩放，不再加上窗口在屏幕上的绝对坐标。
    """
    if not RESOLUTION_CONFIG["curr_width"] or not RESOLUTION_CONFIG["curr_height"]:
        return x, y

    scale_x = RESOLUTION_CONFIG["curr_width"] / RESOLUTION_CONFIG["base_width"]
    scale_y = RESOLUTION_CONFIG["curr_height"] / RESOLUTION_CONFIG["base_height"]

    rel_x = int(x * scale_x)
    rel_y = int(y * scale_y)
    return rel_x, rel_y


def adapt_region(x1: int, y1: int, x2: int, y2: int):
    """
    将 2560x1440 基准下的矩形区域换算为当前窗口客户区的实际区域
    """
    rx1, ry1 = adapt_coord(x1, y1)
    rx2, ry2 = adapt_coord(x2, y2)
    return min(rx1, rx2), min(ry1, ry2), max(rx1, rx2), max(ry1, ry2)


# ============================================
# PC 后台原生控制与图像识别 (Win32 API)
# ============================================
class PCAutomation:
    def __init__(self):
        pass

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

    def take_screenshot(self, region: Optional[tuple] = None):  #
        """
        获取截图，可选裁剪区域 (x1, y1, x2, y2)
        """
        full_img = self.capture_screen()
        if full_img is None: return None
        if region:
            x1, y1, x2, y2 = region
            # 自动适配分辨率
            rx1, ry1 = adapt_coord(x1, y1)
            rx2, ry2 = adapt_coord(x2, y2)
            return full_img[ry1:ry2, rx1:rx2]
        return full_img

    @staticmethod
    def set_foreground():
        """强制将游戏窗口带到最前台并激活"""
        import win32gui, win32con
        hwnd = _TARGET_HWND
        if hwnd:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            try:
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
                shell.SendKeys('%')
                win32gui.SetForegroundWindow(hwnd)
                win32gui.BringWindowToTop(hwnd)
                print(">>> 已成功将游戏窗口置于前台")
                time.sleep(0.5)
            except Exception as e:
                print(f"⚠️ 无法置顶窗口: {e}")

    def click(self, x: int, y: int, move: bool = False, show_log: bool = False):
        """统一鼠标点击接口"""
        hwnd = _TARGET_HWND
        if not hwnd: return

        rel_x, rel_y = adapt_coord(x, y)

        original_pos = None

        win32gui.SendMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)

        try:
            if move:
                original_pos = win32api.GetCursorPos()
                screen_x, screen_y = win32gui.ClientToScreen(hwnd, (rel_x, rel_y))
                win32api.SetCursorPos((screen_x, screen_y))
                # 增加停顿时间，让游戏引擎充分意识到鼠标已停稳
                time.sleep(0.05)
                
                # 完全使用物理级硬件输入，避免 PostMessage 在恢复原坐标时产生拖拽误判
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                time.sleep(random.uniform(0.02, 0.05))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                
                # 关键：松手后必须停顿，防止瞬间恢复原位置被引擎算作手势滑动
                time.sleep(0.1)
            else:
                lparam = win32api.MAKELONG(rel_x, rel_y)
                # 纯后台时也要先发送 MOUSEMOVE 确保坐标正确
                win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
                time.sleep(0.01)
                win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
                time.sleep(random.uniform(0.02, 0.05))
                win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)

        except Exception as e:
            print(f"点击异常: {e}")

        finally:
            if move and original_pos:
                try:
                    win32api.SetCursorPos(original_pos)
                except Exception:
                    pass

        if show_log:
            mode_str = "物理闪现" if move else "纯后台"
            print(f"点击[{mode_str}]: 逻辑({x}, {y}) -> 客户区({rel_x}, {rel_y})")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5, move: bool = True, show_log: bool = False):
        """统一鼠标拖拽/滑动接口"""
        hwnd = _TARGET_HWND
        if not hwnd: return

        rel_x1, rel_y1 = adapt_coord(x1, y1)
        rel_x2, rel_y2 = adapt_coord(x2, y2)
        
        original_pos = None

        win32gui.SendMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)

        try:
            if move:
                # 纯物理硬件级模拟（针对模拟器/游戏引擎拦截了底层输入的情况）
                original_pos = win32api.GetCursorPos()
                screen_x1, screen_y1 = win32gui.ClientToScreen(hwnd, (rel_x1, rel_y1))
                
                sw = win32api.GetSystemMetrics(0)
                sh = win32api.GetSystemMetrics(1)
                
                mx1 = int(screen_x1 * 65535 / sw)
                my1 = int(screen_y1 * 65535 / sh)
                
                win32api.mouse_event(win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_MOVE, mx1, my1, 0, 0)
                time.sleep(0.05)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                time.sleep(0.05)
                
                start_time = time.time()
                while True:
                    elapsed = time.time() - start_time
                    if elapsed >= duration:
                        break
                    t = elapsed / duration
                    curr_x = int(rel_x1 + (rel_x2 - rel_x1) * t)
                    curr_y = int(rel_y1 + (rel_y2 - rel_y1) * t)
                    
                    screen_x, screen_y = win32gui.ClientToScreen(hwnd, (curr_x, curr_y))
                    mx = int(screen_x * 65535 / sw)
                    my = int(screen_y * 65535 / sh)
                    win32api.mouse_event(win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_MOVE, mx, my, 0, 0)
                    time.sleep(0.01)

                screen_x2, screen_y2 = win32gui.ClientToScreen(hwnd, (rel_x2, rel_y2))
                mx2 = int(screen_x2 * 65535 / sw)
                my2 = int(screen_y2 * 65535 / sh)
                win32api.mouse_event(win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_MOVE, mx2, my2, 0, 0)
                time.sleep(0.05)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                time.sleep(0.02)
                
            else:
                # 纯软件队列模拟（PostMessage）
                lparam1 = win32api.MAKELONG(rel_x1, rel_y1)
                win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam1)
                time.sleep(0.01)
                win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam1)
                time.sleep(0.05)

                start_time = time.time()
                while True:
                    elapsed = time.time() - start_time
                    if elapsed >= duration:
                        break
                    t = elapsed / duration
                    curr_x = int(rel_x1 + (rel_x2 - rel_x1) * t)
                    curr_y = int(rel_y1 + (rel_y2 - rel_y1) * t)
                    
                    lparam_move = win32api.MAKELONG(curr_x, curr_y)
                    win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, lparam_move)
                    time.sleep(0.01)

                lparam2 = win32api.MAKELONG(rel_x2, rel_y2)
                win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, lparam2)
                win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam2)

        except Exception as e:
            print(f"滑动异常: {e}")
            
        finally:
            if move and original_pos:
                try:
                    win32api.SetCursorPos(original_pos)
                except Exception:
                    pass

        if show_log:
            mode_str = "物理闪现" if move else "纯后台"
            print(f"滑动[{mode_str}]: 逻辑({x1}, {y1})->({x2}, {y2}) | 客户区({rel_x1}, {rel_y1})->({rel_x2}, {rel_y2})")

    def scroll(self, x: int, y: int, delta: int = -120, times: int = 1, interval: float = 0.05, move: bool = True, show_log: bool = False):
        """统一鼠标滚轮滚动接口"""
        hwnd = _TARGET_HWND
        if not hwnd: return

        rel_x, rel_y = adapt_coord(x, y)
        original_pos = None

        win32gui.SendMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)

        try:
            if move:
                original_pos = win32api.GetCursorPos()
                screen_x, screen_y = win32gui.ClientToScreen(hwnd, (rel_x, rel_y))
                win32api.SetCursorPos((screen_x, screen_y))
                time.sleep(0.02)
                
                # 多次发送滚动事件，模拟真实的连续滚动
                for _ in range(times):
                    win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
                    time.sleep(interval)
            else:
                # WM_MOUSEWHEEL 期望的 lparam 是屏幕绝对坐标
                screen_x, screen_y = win32gui.ClientToScreen(hwnd, (rel_x, rel_y))
                wparam = win32api.MAKELONG(0, delta)
                lparam_screen = win32api.MAKELONG(screen_x, screen_y)
                
                for _ in range(times):
                    win32gui.PostMessage(hwnd, win32con.WM_MOUSEWHEEL, wparam, lparam_screen)
                    time.sleep(interval)

        except Exception as e:
            print(f"滚动异常: {e}")
            
        finally:
            if move and original_pos:
                try:
                    win32api.SetCursorPos(original_pos)
                except Exception:
                    pass

        if show_log:
            mode_str = "物理闪现" if move else "纯后台"
            print(f"滚动[{mode_str}]: 逻辑({x}, {y}), 滚轮量={delta}")

    def swipe_in_region(self, region: tuple, direction: str = 'up', duration: float = 0.5, move: bool = True, show_log: bool = False):
        """
        在指定区域内按方向滑动
        :param region: (x1, y1, x2, y2)
        :param direction: 'up' (向上滑, 也就是下拉页面), 'down' (向下滑), 'left' (向左滑), 'right' (向右滑)
        """
        x1, y1, x2, y2 = region
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        
        pad_x = (x2 - x1) * 0.2
        pad_y = (y2 - y1) * 0.2
        
        start_x, end_x = cx, cx
        start_y, end_y = cy, cy
        
        if direction == 'up':
            start_y = int(y2 - pad_y)
            end_y = int(y1 + pad_y)
        elif direction == 'down':
            start_y = int(y1 + pad_y)
            end_y = int(y2 - pad_y)
        elif direction == 'left':
            start_x = int(x2 - pad_x)
            end_x = int(x1 + pad_x)
        elif direction == 'right':
            start_x = int(x1 + pad_x)
            end_x = int(x2 - pad_x)
            
        self.swipe(start_x, start_y, end_x, end_y, duration=duration, move=move, show_log=show_log)

    def send_key(self, key: str, show_log: bool = False):
        """纯后台按键"""
        hwnd = _TARGET_HWND
        if not hwnd: return

        key_upper = key.upper()
        if len(key_upper) == 1:
            vk_code = ord(key_upper)
        else:
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

        win32gui.SendMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)

        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk_code, 0)
        time.sleep(random.uniform(0.03, 0.05))
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk_code, 0)

        if show_log:
            print(f"纯后台按键: '{key_upper}'")


class ImageMatcher:
    @staticmethod
    def compare_template(screen_bgr, template_path: str, threshold: float = 0.8) -> Dict:
        """模板匹配（支持分辨率自适应缩放 + 透明通道Mask免疫背景干扰）"""
        # 以包含 Alpha 通道的方式读取图片 (IMREAD_UNCHANGED)
        template_img = cv2.imread(template_path, cv2.IMREAD_UNCHANGED)
        if template_img is None:
            raise ValueError(f"无法读取模板图片: {template_path}")

        # 分离透明通道掩码 (Alpha Mask)
        alpha_mask = None
        if len(template_img.shape) == 3 and template_img.shape[2] == 4:
            template_bgr = template_img[:, :, :3]
            alpha_mask = template_img[:, :, 3]
        else:
            template_bgr = template_img

        # 1. 获取当前分辨率与基础分辨率
        curr_w = RESOLUTION_CONFIG.get("curr_width")
        curr_h = RESOLUTION_CONFIG.get("curr_height")
        # 默认回退到 2K 分辨率，确保字典中没有 base_width 时也能正常工作
        base_w = RESOLUTION_CONFIG.get("base_width", 2560)
        base_h = RESOLUTION_CONFIG.get("base_height", 1440)

        # 2. 如果成功获取了当前窗口大小，且与基础分辨率不同，则执行等比例缩放
        if curr_w and curr_h and (curr_w != base_w or curr_h != base_h):
            scale_x = curr_w / base_w
            scale_y = curr_h / base_h

            new_w = max(1, int(template_bgr.shape[1] * scale_x))
            new_h = max(1, int(template_bgr.shape[0] * scale_y))

            # 智能选择插值算法
            if scale_x > 1.0 or scale_y > 1.0:
                interp = cv2.INTER_LINEAR
            else:
                interp = cv2.INTER_AREA

            template_bgr = cv2.resize(template_bgr, (new_w, new_h), interpolation=interp)
            
            # 如果有透明掩码，也要等比例缩放掩码
            if alpha_mask is not None:
                alpha_mask = cv2.resize(alpha_mask, (new_w, new_h), interpolation=interp)

        # 3. 统一转换为灰度图
        screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)

        # 4. 执行底层匹配（带 Mask 容错）
        try:
            if alpha_mask is not None:
                res = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED, mask=alpha_mask)
            else:
                res = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        except Exception:
            # 兜底：防止某些极老版本的 OpenCV 不支持 mask 参数
            res = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)

        # 将矩阵中的 inf 和 NaN 全部替换为 0.0，防止程序崩溃或异常误判
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)

        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        is_match = max_val >= threshold

        # 5. 计算匹配到的中心点坐标
        cx = max_loc[0] + template_bgr.shape[1] // 2
        cy = max_loc[1] + template_bgr.shape[0] // 2

        # 反向缩放回逻辑坐标
        if curr_w and curr_h and (curr_w != base_w or curr_h != base_h):
            scale_x = curr_w / base_w
            scale_y = curr_h / base_h
            cx = int(cx / scale_x)
            cy = int(cy / scale_y)

        return {
            "is_match": is_match,
            "max_corr": float(max_val),
            "center_point": (cx, cy) if is_match else None
        }


# ============================================
# OCR 模块
# ============================================
class OCRManager:
    _initialized = False

    @classmethod
    def init_tesseract(cls):
        if not cls._initialized:
            # 动态定位项目目录下的 Tesseract
            tess_path = os.path.join(PROJECT_ROOT, "bin", "Tesseract-OCR", "tesseract.exe")
            pytesseract.pytesseract.tesseract_cmd = tess_path
            cls._initialized = True

    @classmethod
    def get_text_from_region(cls, region: tuple, config: str = "--psm 6"):
        """
        :param config: 默认为 psm 6 (单个文本块)，如果识别单行可以用 psm 7
        """
        cls.init_tesseract()
        pc = PCAutomation()
        img = pc.take_screenshot(region)
        if img is None: return ""

        # --- 通用预处理：提升识别率但保持文字特征 ---
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 放大 2 倍对 Tesseract 很有帮助
        upscaled = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

        # 即使要识别文字，二值化也能有效去除背景噪声
        _, binary = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        pil_img = Image.fromarray(binary)

        try:
            # 使用传入的 config，外部不传则使用默认
            text = pytesseract.image_to_string(pil_img, config=config, lang='chi_sim+eng')
            return text.strip()
        except Exception as e:
            print(f"Tesseract 识别异常: {e}")
            return ""

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

    status_notifier.log(f"等待 {sleep_time:.2f} 秒...")
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


# ============================================
# 统一状态与日志分发器（用于主页表格与侧边栏日志分流）
# ============================================
class ScriptStatusSignaler:
    def __init__(self):
        self.callback = None
        self.log_callback = None

    def update(self, current_round: int, step_desc: str, total_round: int = None):
        """同步更新主界面单行看板表格的状态"""
        if self.callback:
            self.callback(current_round, step_desc, total_round)
        # 步骤也会自动在侧边栏详细日志中同步写一份
        self.log(f"[步骤] {step_desc}")

    def log(self, text: str):
        """同步将详细调试信息追加到侧边栏日志面板"""
        if self.log_callback:
            self.log_callback(text)
        else:
            print(text)

# 全局单例，供所有自动化业务脚本和GUI导入共享
status_notifier = ScriptStatusSignaler()