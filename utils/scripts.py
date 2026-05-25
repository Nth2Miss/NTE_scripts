from utils.tools import *
import time


# 1. 在全局实例化底层的核心控制器
pc = PCAutomation()


# 2. 定义局部的 click 函数，拦截所有点击并强制加上 move=True
def click(*args, **kwargs):
    kwargs.setdefault("move", False)
    return pc.click(*args, **kwargs)

def timeout(connector, device_id):
    print("-> 执行超时重试...")
    # esc
    click(100, 80, connector, device_id)
    time.sleep(0.1)
    click(2600, 1667, connector, device_id)
    time.sleep(0.1)
    click(1465, 1030, connector, device_id)

