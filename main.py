import cv2
from utils.tools import ADBConnector, ensure_adb_connection, list_devices, execute_screenshot_and_match, random_click, random_sleep, random_sleep_extended
import sys

Round = 999

def main():
    try:
        # 确保ADB连接
        connector = ensure_adb_connection()

        # 列出设备
        devices = list_devices(connector)
        
        # 如果有设备，执行截图和模板匹配
        if devices:
            first_device = devices[0]

            for i in range(Round):
                print(f"\n第{i + 1}次运行")
                # 再次进行
                res = execute_screenshot_and_match(first_device, connector, "templates/restart.png",(1682, 1700, 2147, 1778), debug=False)
                print(f"识别{res}")
                if res:
                    random_click(1682, 1700, 2147, 1778, connector, first_device)
                    random_sleep(3)

                    random_click(1440, 1190, 1980, 1250, connector, first_device)

                    random_sleep_extended(80, 90)



        
    except RuntimeError as e:
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
    cv2.waitKey()
    cv2.destroyAllWindows()