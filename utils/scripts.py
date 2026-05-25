from utils.tools import *
import time


def timeout(connector, device_id):
    print("-> 执行超时重试...")
    # esc
    click(100, 80, connector, device_id)
    time.sleep(0.1)
    click(2600, 1667, connector, device_id)
    time.sleep(0.1)
    click(1465, 1030, connector, device_id)

