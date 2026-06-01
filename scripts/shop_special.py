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
    "1-1": os.path.normpath(os.path.join(PROJECT_ROOT, "templates", "1-1.png")),
}

COORDS = {
    "level_1_1": (215, 524),  # 关卡1-1
    "start_btn": (2293, 1340),  # 开始按钮
    "100T": (115, 592),  # 锤子
    "quit": (55, 59),  # 退出
    "claim": (1549, 1112),  # 领取

    # ocr 区域 (x1, y1, x2, y2)
    "progress_region": (2341, 132, 2487, 183)
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
    time.sleep(1)


def main():
    status_notifier.update(0, "正在初始化自动化脚本...")
    pc.set_foreground()
    time.sleep(2)

    run_count = 0

    # 1. 后台发送 F 键
    status_notifier.update(run_count, "后台按 F 键")
    pc.send_key('F')
    time.sleep(1)

    while True:
        run_count += 1
        # 1.5 在 (174, 393, 251, 850) 区域里按方向滑动
        # status_notifier.update(run_count, "区域内滑动(direction='up')")
        # pc.swipe_in_region((174, 393, 251, 850), direction='up', duration=1.5)
        # time.sleep(1)

        # 1.5 滚动到最上
        status_notifier.update(run_count, "鼠标滚轮滚动至最上")
        # times=50 表示连续快速向上滚动 50 次
        pc.scroll(250, 500, delta=120, times=50)
        time.sleep(0.3)

        # 2. 识图寻找 1-1 关卡并点击
        status_notifier.update(run_count, "开始检测模板: 1-1.png")
        level_1_1_result = wait_until_match(TEMPLATES["1-1"], timeout=10, threshold=0.8)
        
        if level_1_1_result and level_1_1_result.get("is_match"):
            cx, cy = level_1_1_result["center_point"]
            status_notifier.update(run_count, f"1-1 识图成功！准备点击坐标: ({cx}, {cy})")
            click(cx, cy)
        else:
            status_notifier.update(run_count, "未检测到 1-1 关卡，尝试继续后续流程...")
            
        time.sleep(0.3)

        # 3. 后台静默识图 (后续循环按完 F 后直接进入这里)
        status_notifier.update(run_count, "开始检测模板: start_business.png")
        try:
            start_business_result = wait_until_match(TEMPLATES["start_business"], timeout=15, threshold=0.8)

            if start_business_result and start_business_result.get("is_match"):
                # 获取返回的中心坐标并进行后台点击
                cx, cy = start_business_result["center_point"]
                status_notifier.update(run_count, f"识图成功！准备点击坐标: ({cx}, {cy})")

                click(cx, cy)
            else:
                status_notifier.update(run_count, "未检测到开始按钮，尝试继续后续流程...")

            # 等待加载进场
            time.sleep(6)

            # 4. 调用包含 OCR 验证的循环打击方法
            combat_prep(run_count)

            status_notifier.update(run_count, "✅ 单轮任务完成，准备开始下一轮...")

        except Exception as e:
            status_notifier.update(run_count, f"❌ 运行出错: {e}")
            time.sleep(5)
            continue


if __name__ == "__main__":
    main()