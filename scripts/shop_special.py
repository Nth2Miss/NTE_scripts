import os
import time
from utils.tools import PCAutomation, wait_until_match, random_sleep

# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# =================================================================
# --- 配置区 ---
TEMPLATES = {
    "start_business": os.path.join(PROJECT_ROOT, "templates", "start_business.png"),
}

COORDS = {
    "level_1_1": (161, 393),    # 关卡1-1
    "start_btn": (1720, 1005),  # 开始按钮
    "100T": (86, 444),          # 锤子
    "quit": (41, 44),           # 退出
    "claim": (1162, 834),       # 领取
}
# =================================================================

# 1. 在全局实例化底层的核心控制器
pc = PCAutomation()

# 2. 定义局部的 click 函数，拦截所有点击并强制加上 move=True
def click(*args, **kwargs):
    kwargs.setdefault("move", True)
    return pc.click(*args, **kwargs)

def combat_prep(times=3):
    """封装：确认选择 -> 进场 -> 移动 -> 开大"""
    print("-> 开始驱赶刁民...")
    for _ in range(times):
        # 使用我们封装的后台点击 (默认会触发 UI 物理闪现机制和坐标等比缩放)
        click(*COORDS["100T"])
        time.sleep(1)

    time.sleep(1)
    click(*COORDS["quit"])
    time.sleep(1)
    click(*COORDS["claim"])
    print("-> 结算 领取奖励")
    time.sleep(5)


def main():
    print(">>> 开始执行: 自动化店长特供1-1...")

    # PCAutomation.set_foreground()
    print("2s后开始")
    time.sleep(2)

    while True:
        # 1. 后台发送 F 键 (使用刚改好的 send_key)
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
                # 4. 获取返回的中心坐标并进行后台点击
                cx, cy = start_business_result["center_point"]
                print(f">>> 识图成功！准备点击坐标: ({cx}, {cy})")

                # 加上 is_actual=True，跳过缩放，直接将后台识图坐标发送给窗口
                click(cx, cy, is_actual=True)

            time.sleep(6)
            combat_prep(15)

        except Exception as e:
            print(f"发生异常: {e}")
            break

if __name__ == "__main__":
    main()