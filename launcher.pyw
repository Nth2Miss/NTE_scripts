import subprocess
import os

# 设置环境变量或直接指向全路径
env_path = r"D:\miniconda3\Scripts\activate.bat"
script_path = "gui_main.py"

# 使用 pythonw 运行可以隐藏控制台
subprocess.Popen(f'cmd /c "{env_path} Py312 && python {script_path}"', shell=True, creationflags=subprocess.CREATE_NO_WINDOW)