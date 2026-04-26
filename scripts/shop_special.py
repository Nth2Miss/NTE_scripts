import os
import time
import re
from utils.tools import PCAutomation, wait_until_match, random_sleep, OCRManager

# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# =================================================================
# --- 配置区 ---
TEMPLATES = {
    "start_business": os.path.join(PROJECT_ROOT, "templates", "start_business.png"),
}

COORDS = {
    "level_1_1": (161, 393),  # 关卡1-1
    "start_btn": (1720, 1005),  # 开始按钮
    "100T": (86, 444),  # 锤子
    "quit": (41, 44),  # 退出
    "claim": (1162, 834),  # 领取

    # ocr 区域
    "progress_region": (1767, 93, 1862, 138)
}
# =================================================================

# 1. 在全局实例化底层的核心控制器
pc = PCAutomation()


# 2. 定义局部的 click 函数，拦截所有点击并强制加上 move=True
def click(*args, **kwargs):
    kwargs.setdefault("move", True)
    return pc.click(*args, **kwargs)


def combat_prep():
    """封装：基于OCR动态进度识别 -> 进场 -> 移动 -> 结算"""
    print("-> 开始驱赶刁民，等待进度达到 100...")

    # 设置一个最大循环次数，防止一直未能识别到导致的死循环卡死
    max_loops = 100

    for _ in range(max_loops):
        # 1. 获取目标区域的 OCR 识别文本
        text = OCRManager.get_text_from_region(COORDS["progress_region"])

        # 2. 匹配进度数字，如 "85 / 100" 或 "85/100"
        match = re.search(r'(\d+)\s*/\s*100', text)

        if match:
            current_progress = int(match.group(1))
            print(f"-> OCR进度识别: {current_progress} / 100")

            # 判断进度是否达到目标
            if current_progress >= 100:
                print("-> 进度已满 (≥100)，停止点击！")
                break
        else:
            print(f"-> OCR未读到标准进度 (识别到结果:'{text}')，继续点击...")

        # 3. 进度未满或未读到，继续点击并稍作延迟
        click(*COORDS["100T"])
        time.sleep(1)

    # 4. 循环结束，执行后续结算流程
    time.sleep(1)
    click(*COORDS["quit"])
    time.sleep(1)
    click(*COORDS["claim"])
    print("-> 结算 领取奖励")
    time.sleep(5)


def main():
    print(">>> 开始执行: 自动化店长特供1-1...")

    print("2s后开始")
    time.sleep(2)

    while True:
        # 1. 后台发送 F 键
        print(">>> 执行操作: 后台按 F 键")
        pc.send_key('F')
        time.sleep(2)

        # 2. 后台点击关卡1-1
        print(">>> 执行操作: 后台点击 关卡1-1")
        click(*COORDS["level_1_1"])
        time.sleep(1)

        # 3. 后台静默识图
        print(">>> 开始检测模板: start_business.png")
        try:
            start_business_result = wait_until_match(TEMPLATES["start_business"], timeout=15, threshold=0.8)

            if start_business_result and start_business_result.get("is_match"):
                # 获取返回的中心坐标并进行后台点击
                cx, cy = start_business_result["center_point"]
                print(f">>> 识图成功！准备点击坐标: ({cx}, {cy})")

                # 加上 is_actual=True，跳过缩放，直接将后台识图坐标发送给窗口
                click(cx, cy, is_actual=True)

            time.sleep(6)

            # 4. 调用包含 OCR 验证的循环打击方法
            combat_prep()

        except Exception as e:
            print(f"发生异常: {e}")
            break


if __name__ == "__main__":
    main()