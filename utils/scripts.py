from utils.tools import *
import time

def select_commission_multiplier(connector, device_id):
    """
    读取全局配置并点击对应的委托手册倍率
    """

    # 获取用户在 GUI 中选择的倍率
    multiplier = config_mgr.get("commission_multiplier", "不使用")

    # === 委托手册倍率坐标 ===
    MULTIPLIER_COORDS = {
        "100%": (1080, 1020),
        "200%": (1400, 1020),
        "800%": (1720, 1020),
        "2000%": (2030, 1020)
    }
    # =========================================================

    if multiplier != "不使用" and multiplier in MULTIPLIER_COORDS:
        print(f"-> 正在选择委托手册倍率: {multiplier}")
        time.sleep(1)  # 等待倍率选项弹出的动画时间
        click(*MULTIPLIER_COORDS[multiplier], connector, device_id)
        time.sleep(0.5)  # 点击后稍等

def fuwei(connector, device_id):
    print("-> 执行角色复位...")
    # esc
    click(100, 80, connector, device_id)
    time.sleep(0.1)
    # 设置
    click(2000, 1700, connector, device_id)
    time.sleep(0.1)
    # 复位角色
    click(110, 870, connector, device_id)
    time.sleep(0.1)
    click(2400, 1290, connector, device_id)
    time.sleep(0.1)
    click(1470, 1030, connector, device_id)

def ult(connector, device_id):
    print("-> 执行大招...")
    click(2050, 1650, connector, device_id)

def reg(connector, device_id, show_log=True):
    if show_log:
        print("-> 执行技能...")
    click(1950, 1650, connector, device_id, show_log)


def spiral(connector, device_id, num):
    print("-> 执行螺旋操作...")
    for i in range(num):
        print(f"   螺旋第 {i + 1} 次")
        click(2425, 1060, connector, device_id, show_log=False)
        time.sleep(0.5)

def sprint(connector, device_id):
    print("-> 执行冲刺...")
    click(2680, 1065, connector, device_id)


def timeout(connector, device_id):
    print("-> 执行超时重试...")
    # esc
    click(100, 80, connector, device_id)
    time.sleep(0.1)
    click(2600, 1667, connector, device_id)
    time.sleep(0.1)
    click(1465, 1030, connector, device_id)

