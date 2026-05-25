import os
import time
import re
import sys
from utils.tools import PCAutomation, wait_until_match, random_sleep, OCRManager, status_notifier


# =================================================================
# 1. 适配 Nuitka 的路径获取逻辑
# =================================================================
def get_project_root():
    if getattr(sys, 'frozen', False):
        # Nuitka 编译后，sys.executable 是 .exe 的绝对路径
        # 直接返回 .exe 所在的目录作为根目录
        return os.path.dirname(os.path.abspath(sys.executable))

    # 源码开发环境 (脚本在 /scripts 目录下)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


PROJECT_ROOT = get_project_root()

# 强制切换工作目录到程序根目录，确保相对路径资源加载稳定
os.chdir(PROJECT_ROOT)

# 配置区
TEMPLATES = {
    # 使用 PROJECT_ROOT 拼接绝对路径，确保 cv2.imread 能够读取成功
    "start_business": os.path.normpath(os.path.join(PROJECT_ROOT, "templates", "start_business.png")),
}

COORDS = {
    "level_1_1": (161, 393),  # 关卡1-1
    "start_btn": (1720, 1005),  # 开始按钮
    "100T": (86, 444),  # 锤子
    "quit": (41, 44),  # 退出
    "claim": (1162, 834),  # 领取

    # ocr 区域
    "progress_region": (1756, 99, 1865, 137)
}
# =================================================================

# 1. 在全局实例化底层的核心控制器
pc = PCAutomation()


# 2. 定义局部的 click 函数，拦截所有点击并强制加上 move=True
def click(*args, **kwargs):
    kwargs.setdefault("move", True)
    return pc.click(*args, **kwargs)


def combat_prep(run_count):
    """封装：基于OCR动态进度识别 -> 进场 -> 移动 -> 结算"""
    status_notifier.update(run_count, "开始驱赶刁民，等待进度达到 100...")

    # 设置一个最大循环次数，防止一直未能识别到导致的死循环卡死
    max_loops = 30

    for _ in range(max_loops):
        # 1. 获取目标区域 the OCR 识别文本
        text = OCRManager.get_text_from_region(COORDS["progress_region"])

        # 2. 匹配进度数字，如 "85 / 100" 或 "85/100"
        match = re.search(r'(\d+)\s*/\s*100', text)

        if match:
            current_progress = int(match.group(1))
            status_notifier.update(run_count, f"驱赶中，当前进度: {current_progress} / 100")

            # 判断进度是否达到目标
            if current_progress >= 100:
                status_notifier.update(run_count, "进度已满 (≥100)，停止点击！")
                break
        else:
            status_notifier.update(run_count, f"未读到标准进度，继续点击... (OCR: '{text}')")

        # 3. 进度未满或未读到，继续点击并稍作延迟
        click(*COORDS["100T"])
        time.sleep(1)

    # 4. 循环结束，执行后续结算流程
    time.sleep(1)
    click(*COORDS["quit"])
    time.sleep(1)
    click(*COORDS["claim"])
    status_notifier.update(run_count, "✅ 结算 领取奖励成功")
    time.sleep(5)


def main():
    status_notifier.update(0, "正在初始化自动化脚本...")
    pc.set_foreground()
    time.sleep(2)

    # 标记是否为第一次运行
    is_first_run = True
    run_count = 0

    while True:
        run_count += 1
        # 1. 后台发送 F 键 (每次循环都需要)
        status_notifier.update(run_count, "后台按 F 键")
        pc.send_key('F')
        time.sleep(2)

        # 2. 只有第一次运行时，才需要点击选择 1-1 关卡
        if is_first_run:
            status_notifier.update(run_count, "后台点击 关卡1-1")
            click(*COORDS["level_1_1"])
            time.sleep(1.5)
            # 修改标记，后续循环将跳过此判断体
            is_first_run = False
        else:
            status_notifier.update(run_count, "跳过关卡选择，直接检测开始模板...")

        # 3. 后台静默识图 (后续循环按完 F 后直接进入这里)
        status_notifier.update(run_count, "开始检测模板: start_business.png")
        try:
            start_business_result = wait_until_match(TEMPLATES["start_business"], timeout=15, threshold=0.8)

            if start_business_result and start_business_result.get("is_match"):
                # 获取返回的中心坐标并进行后台点击
                cx, cy = start_business_result["center_point"]
                status_notifier.update(run_count, f"识图成功！准备点击坐标: ({cx}, {cy})")

                # 加上 is_actual=True，跳过缩放，直接将后台识图坐标发送给窗口
                click(cx, cy, is_actual=True)
            else:
                status_notifier.update(run_count, "未检测到开始按钮，尝试继续后续流程...")

            # 等待加载进场
            time.sleep(6)

            # 4. 调用包含 OCR 验证的循环打击方法
            combat_prep(run_count)

            status_notifier.update(run_count, "✅ 单轮任务完成，准备开始下一轮...")
            time.sleep(2)

        except Exception as e:
            status_notifier.update(run_count, f"❌ 运行出错: {e}")
            # 如果出现异常，建议重置 is_first_run 以便重新开始流程
            is_first_run = True
            time.sleep(5)
            continue


if __name__ == "__main__":
    main()