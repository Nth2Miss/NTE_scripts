import sys
import time
import importlib.util
import os
import threading
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot, QMetaObject, Q_ARG, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QWidget, QApplication,
    QTableWidgetItem, QHeaderView
)
from PyQt6.QtGui import QFont, QIcon
from qfluentwidgets import (
    FluentWindow, SubtitleLabel, BodyLabel, PrimaryPushButton, PushButton,
    TextEdit, FluentIcon as FIF, InfoBar, InfoBarPosition, ProgressBar,
    NavigationItemPosition, ScrollArea, LineEdit, SwitchButton, PasswordLineEdit,
    MessageBox, SettingCard, ExpandSettingCard, ComboBox, TableWidget, CardWidget
)

import ctypes
try:
    # 与启动器不同的 ID，让主程序独立显示
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NTE.Main.Yihuan.v1")
except:
    pass

# ============================================
# 1. 路径自动定位与环境初始化
# ============================================
def get_root_path():
    # Nuitka 或 PyInstaller 编译后的环境
    if getattr(sys, 'frozen', False):
        # sys.executable 指向 .exe 的完整路径
        return os.path.dirname(os.path.abspath(sys.executable))
    # 源码开发环境
    return os.path.dirname(os.path.abspath(__file__))

PROJECT_ROOT = get_root_path()

# 将工作目录切换至程序根目录，解决所有相对路径问题
os.chdir(PROJECT_ROOT)

# 确保项目根目录在模块搜索路径中
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import utils.tools
    from utils.tools import set_running_state, StopScriptException
    APP_CONFIG = utils.tools.config_mgr
except ImportError as e:
    print(f"导入错误: {e}")
    APP_CONFIG = None


# ============================================
# 2. 辅助类：日志流 & 工作线程
# ============================================
class EmittingStream(QObject):
    textWritten = pyqtSignal(str)

    def write(self, text): self.textWritten.emit(str(text))

    def flush(self): pass


class Worker(QThread):
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, script_path):
        super().__init__()
        self.script_path = script_path

    def run(self):
        if not self.script_path or not os.path.exists(self.script_path):
            self.error_signal.emit(f"错误: 找不到文件 {self.script_path}")
            self.finished_signal.emit()
            return

        set_running_state(True)
        file_name = os.path.basename(self.script_path)
        print(f"=== 正在启动: {file_name} ===")

        # --- 在线程启动时自动初始化 PC 动态分辨率 ---
        try:
            import utils.tools
            utils.tools.init_resolution()
        except Exception as e:
            print(f"⚠️ 分辨率同步异常: {e}")

        # --- 劫持 sleep 以便主界面随时中断 ---
        original_sleep = time.sleep

        def interruptible_sleep(seconds):
            end_time = time.time() + seconds
            while time.time() < end_time:
                if hasattr(utils.tools, 'check_running'):
                    utils.tools.check_running()
                left = end_time - time.time()
                original_sleep(min(0.1, max(0, left)))

        time.sleep = interruptible_sleep

        try:
            mod_name = f"script_{int(time.time())}"
            spec = importlib.util.spec_from_file_location(mod_name, self.script_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module

            os.chdir(PROJECT_ROOT)
            spec.loader.exec_module(module)

            if hasattr(module, 'run'):
                module.run()
            elif hasattr(module, 'main'):
                module.main()
            else:
                print(f"错误: {file_name} 中未找到 run() 或 main() 函数")

        except StopScriptException:
            print(">>> 🛑 脚本已成功停止")
        except Exception as e:
            import traceback
            print(f"❌ 运行出错: {e}\n{traceback.format_exc()}")
            self.error_signal.emit(str(e))
        finally:
            time.sleep = original_sleep
            self.finished_signal.emit()

    def stop(self):
        set_running_state(False)


# ============================================
# 3. 侧边栏独立的日志面板 (LogInterface)
# ============================================
class LogInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('logInterface')
        self.scrollWidget = QWidget()
        self.vBoxLayout = QVBoxLayout(self.scrollWidget)

        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(20)

        self.titleLabel = SubtitleLabel('详细运行日志', self.scrollWidget)
        self.titleLabel.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        self.vBoxLayout.addWidget(self.titleLabel)

        self.logCard = CardWidget(self.scrollWidget)
        self.cardLayout = QVBoxLayout(self.logCard)
        self.cardLayout.setContentsMargins(15, 15, 15, 15)

        self.logText = TextEdit(self.logCard)
        self.logText.setReadOnly(True)
        self.logText.setFixedHeight(450)
        self.cardLayout.addWidget(self.logText)

        self.btnLayout = QHBoxLayout()
        self.clearBtn = PushButton("清空日志台", self.logCard)
        self.clearBtn.setIcon(FIF.DELETE)
        self.clearBtn.clicked.connect(self.logText.clear)
        self.btnLayout.addStretch(1)
        self.btnLayout.addWidget(self.clearBtn)
        self.cardLayout.addLayout(self.btnLayout)

        self.vBoxLayout.addWidget(self.logCard)
        self.vBoxLayout.addStretch(1)

    @pyqtSlot(str)
    def append_log(self, text):
        """接收日志并自动渲染 HTML 染色效果"""
        current_time = time.strftime("%H:%M:%S", time.localtime())
        cleaned_text = text.strip()

        if "✅" in cleaned_text or "成功" in cleaned_text:
            html = f'<font color="#0F7B42">[{current_time}] {cleaned_text}</font>'
        elif "❌" in cleaned_text or "错误" in cleaned_text or "异常" in cleaned_text:
            html = f'<font color="#851614"><b>[{current_time}] {cleaned_text}</b></font>'
        elif "[步骤]" in cleaned_text:
            html = f'<font color="#0066CC">[{current_time}] {cleaned_text}</font>'
        else:
            html = f'<font color="#777777">[{current_time}]</font> <font color="#333333">{cleaned_text}</font>'
        self.logText.append(html)


# ============================================
# 4. 连接管理页面
# ============================================
class ConnectInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('connectInterface')
        self.scrollWidget = QWidget()
        self.vBoxLayout = QVBoxLayout(self.scrollWidget)

        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(20)

        self.titleLabel = SubtitleLabel('应用连接管理', self.scrollWidget)
        self.titleLabel.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        self.vBoxLayout.addWidget(self.titleLabel)

        self.connectCard = SettingCard(
            FIF.APPLICATION,
            "连接到《异环》",
            "必须先锁定 HTGame.exe 游戏窗口才能启用自动化脚本识图和控制",
            self.scrollWidget
        )
        self.statusTag = BodyLabel("未连接")
        self.connectBtn = PrimaryPushButton("立即连接")
        self.connectBtn.clicked.connect(self.try_connect)

        self.connectCard.hBoxLayout.addWidget(self.statusTag)
        self.connectCard.hBoxLayout.addSpacing(15)
        self.connectCard.hBoxLayout.addWidget(self.connectBtn)
        self.connectCard.hBoxLayout.addSpacing(15)

        self.vBoxLayout.addWidget(self.connectCard)
        self.vBoxLayout.addStretch(1)

    def try_connect(self, silent_fail=False):
        import utils.tools
        import win32gui  # 引入底层的 win32gui 来读取名字

        win = utils.tools.find_game_window()
        if win:
            utils.tools.init_resolution()
            self.statusTag.setText("✅ 已连接")
            self.statusTag.setStyleSheet("color: #5cb85c;")

            real_title = win32gui.GetWindowText(win)

            InfoBar.success("连接成功", f"已锁定窗口: {real_title}", parent=self)
            self.window().setProperty("game_connected", True)
            return True
        else:
            self.statusTag.setText("❌ 未找到应用")
            self.statusTag.setStyleSheet("color: #d9534f;")
            # 启动时的自动连接如果失败，不弹窗报错以免打扰用户
            if not silent_fail:
                InfoBar.error("连接失败", "请确保《异环》游戏已启动", parent=self)
            return False


# ============================================
# 4. 控制台主页 (HomeInterface)
# ============================================
class HomeInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('homeInterface')
        self.worker = None
        self.start_timestamp = None
        self.run_timer = QTimer(self)
        self.run_timer.timeout.connect(self.update_run_time_slot)

        self.scrollWidget = QWidget()
        self.vBoxLayout = QVBoxLayout(self.scrollWidget)

        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.init_ui()

        # 绑定表格数据槽
        from utils.tools import status_notifier
        status_notifier.callback = self.on_status_updated

    def init_ui(self):
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(20)

        self.titleLabel = SubtitleLabel('PC 自动化控制台', self.scrollWidget)
        self.titleLabel.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        self.vBoxLayout.addWidget(self.titleLabel)

        # ==================================
        # 【新增】脚本动态读取与调试卡片
        # ==================================
        self.debugCard = SettingCard(
            FIF.DEVELOPER_TOOLS,
            "脚本调试模式",
            "自动读取 scripts 目录下的脚本，选择后运行 (用于开发测试)",
            self.scrollWidget
        )

        # 下拉框
        self.scriptComboBox = ComboBox()
        self.scriptComboBox.setMinimumWidth(150)
        self.refresh_scripts()  # 初始化读取

        # 刷新脚本列表按钮
        self.refreshBtn = PushButton(FIF.SYNC, "")
        self.refreshBtn.setToolTip("刷新脚本列表")
        self.refreshBtn.clicked.connect(self.refresh_scripts)

        # 运行按钮
        self.runDebugBtn = PrimaryPushButton("运行选定脚本")
        self.runDebugBtn.setIcon(FIF.PLAY)
        self.runDebugBtn.clicked.connect(self.start_debug_script)

        # 将组件拼接到卡片右侧
        self.debugCard.hBoxLayout.addWidget(self.scriptComboBox)
        self.debugCard.hBoxLayout.addSpacing(10)
        self.debugCard.hBoxLayout.addWidget(self.refreshBtn)
        self.debugCard.hBoxLayout.addSpacing(10)
        self.debugCard.hBoxLayout.addWidget(self.runDebugBtn)
        self.debugCard.hBoxLayout.addSpacing(15)

        self.vBoxLayout.addWidget(self.debugCard)
        # ====== 初始化时根据配置决定是否显示调试卡片 ======
        is_debug = APP_CONFIG.get("debug_mode", False) if APP_CONFIG else False
        self.debugCard.setVisible(is_debug)
        # ==================================

        # 店长特供卡片
        self.shopCard = ExpandSettingCard(
            FIF.PLAY,
            "自动化店长特供1-1",
            "点击右侧按钮运行专属脚本，展开可进行配置操作",
            self.scrollWidget
        )
        self.runShopBtn = PrimaryPushButton("运行脚本", self.shopCard)
        self.runShopBtn.setIcon(FIF.PLAY)
        self.runShopBtn.clicked.connect(self.start_shop_script)
        self.shopCard.addWidget(self.runShopBtn)

        # 卡片下拉部分：文本与重置按钮
        self.shopConfigWidget = QWidget()
        self.shopConfigLayout = QVBoxLayout(self.shopConfigWidget)
        self.shopConfigLayout.setContentsMargins(20, 15, 20, 15)

        self.actionRow = QWidget(self.shopConfigWidget)
        self.actionLayout = QHBoxLayout(self.actionRow)
        self.actionLayout.setContentsMargins(0, 0, 0, 0)

        self.opLabel = BodyLabel("操作", self.actionRow)
        self.actionLayout.addWidget(self.opLabel)
        self.actionLayout.addStretch(1)

        self.resetBtn = PushButton("重置配置", self.actionRow)
        self.resetBtn.setIcon(FIF.UPDATE)
        self.resetBtn.clicked.connect(self.reset_shop_config)
        self.actionLayout.addWidget(self.resetBtn)

        self.shopConfigLayout.addWidget(self.actionRow)
        self.shopCard.viewLayout.addWidget(self.shopConfigWidget)
        self.vBoxLayout.addWidget(self.shopCard)

        # 日志操作区
        self.btnLayout = QHBoxLayout()
        self.stopBtn = PushButton("停止运行", self.scrollWidget)
        self.stopBtn.setIcon(FIF.PAUSE)
        self.stopBtn.setEnabled(False)
        self.stopBtn.clicked.connect(self.stop_script)

        self.clearBtn = PushButton("清空看板", self.scrollWidget)
        self.clearBtn.setIcon(FIF.DELETE)
        self.clearBtn.clicked.connect(self.clear_table_data)

        self.btnLayout.addWidget(self.stopBtn)
        self.btnLayout.addWidget(self.clearBtn)
        self.btnLayout.addStretch(1)
        self.vBoxLayout.addLayout(self.btnLayout)

        self.progressBar = ProgressBar(self.scrollWidget)
        self.progressBar.hide()
        self.vBoxLayout.addWidget(self.progressBar)

        self.vBoxLayout.addSpacing(15)

        self.tableTitleLabel = BodyLabel('📊 实时运行状态看板', self.scrollWidget)
        self.tableTitleLabel.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.vBoxLayout.addWidget(self.tableTitleLabel)

        self.statusTable = TableWidget(self.scrollWidget)
        self.statusTable.setBorderVisible(True)
        self.statusTable.setBorderRadius(8)
        self.statusTable.setSelectionMode(TableWidget.SelectionMode.NoSelection)
        self.statusTable.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.statusTable.setColumnCount(1)
        self.statusTable.setRowCount(5)
        self.statusTable.horizontalHeader().hide()
        self.statusTable.setVerticalHeaderLabels(['运行时长', '当前脚本', '目标轮次', '当前进度', '当前操作步骤'])
        self.statusTable.verticalHeader().show()
        self.statusTable.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.statusTable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.statusTable.setFixedHeight(200)

        self.clear_table_data()
        self.vBoxLayout.addWidget(self.statusTable)
        self.vBoxLayout.addStretch(1)

    def set_debug_visibility(self, visible):
        """动态控制调试卡片的显示与隐藏"""
        self.debugCard.setVisible(visible)

    def refresh_scripts(self):
        """扫描 scripts 目录并更新下拉框"""
        self.scriptComboBox.clear()
        scripts_dir = os.path.join(PROJECT_ROOT, "scripts")
        if os.path.exists(scripts_dir):
            for file in os.listdir(scripts_dir):
                if file.endswith(".py"):
                    self.scriptComboBox.addItem(file)
            print(">>> 脚本列表已刷新")
        else:
            print(f">>> 找不到 scripts 目录: {scripts_dir}")

    def clear_table_data(self):
        self.statusTable.setItem(0, 0, QTableWidgetItem("-"))
        self.statusTable.setItem(1, 0, QTableWidgetItem("-"))
        self.statusTable.setItem(2, 0, QTableWidgetItem("-"))
        self.statusTable.setItem(3, 0, QTableWidgetItem("-"))
        self.statusTable.setItem(4, 0, QTableWidgetItem("就绪 / 未启动"))

    def update_run_time_slot(self):
        """每秒被 QTimer 触发一次，全自动计算并覆盖刷新表格第 1 行（索引 0）"""
        if self.start_timestamp is not None:
            elapsed = int(time.time() - self.start_timestamp)
            hrs = elapsed // 3600
            mins = (elapsed % 3600) // 60
            secs = elapsed % 60
            time_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"
            self.statusTable.setItem(0, 0, QTableWidgetItem(time_str))

    def on_status_updated(self, current_round, step_desc, total_round=None):
        if total_round is not None:
            self.statusTable.setItem(2, 0, QTableWidgetItem(f"{total_round} 次"))
        self.statusTable.setItem(3, 0, QTableWidgetItem(f"第 {current_round} 轮"))
        step_item = QTableWidgetItem(step_desc)
        if "✅" in step_desc or "成功" in step_desc:
            step_item.setForeground(Qt.GlobalColor.darkGreen)
        elif "❌" in step_desc or "错误" in step_desc:
            step_item.setForeground(Qt.GlobalColor.red)
        self.statusTable.setItem(4, 0, step_item)

    def start_debug_script(self):
        """运行下拉框选中的脚本"""
        selected_script = self.scriptComboBox.text()
        if not selected_script:
            self.show_info("提示", "请先选择一个脚本", True)
            return

        if not self.window().property("game_connected"):
            InfoBar.warning("尚未连接应用", "请先在【连接应用】页面锁定游戏窗口", position=InfoBarPosition.TOP_RIGHT,
                            parent=self)
            return

        script_path = os.path.join(PROJECT_ROOT, "scripts", selected_script)
        if not os.path.exists(script_path):
            self.show_info("提示", f"未找到脚本: {script_path}", True)
            return

        self.toggle_ui(True)
        main_win = self.window()
        if hasattr(main_win, 'logInterface'):
            main_win.logInterface.logText.clear()

        # 开始运行时，记录当前时间戳，并启动每秒定时器
        self.start_timestamp = time.time()
        self.statusTable.setItem(0, 0, QTableWidgetItem("00:00:00"))
        self.run_timer.start(1000)

        self.statusTable.setItem(1, 0, QTableWidgetItem(selected_script))
        self.statusTable.setItem(2, 0, QTableWidgetItem("- 次"))
        self.statusTable.setItem(3, 0, QTableWidgetItem("准备中..."))

        self.worker = Worker(script_path)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.error_signal.connect(lambda e: self.show_info("出错", "请查看侧边栏日志", True))
        self.worker.start()

    def start_shop_script(self):
        # 强制检查应用连接状态
        if not self.window().property("game_connected"):
            InfoBar.warning("尚未连接应用", "请先在【连接应用】页面锁定游戏窗口", position=InfoBarPosition.TOP_RIGHT,
                            parent=self)
            return

        script_path = os.path.join(PROJECT_ROOT, "scripts", "shop_special.py")
        if not os.path.exists(script_path):
            self.show_info("提示", f"未找到脚本: {script_path}", True)
            return

        self.toggle_ui(True)
        main_win = self.window()
        if hasattr(main_win, 'logInterface'):
            main_win.logInterface.logText.clear()

        # 开始运行时，记录当前时间戳，并启动每秒定时器
        self.start_timestamp = time.time()
        self.statusTable.setItem(0, 0, QTableWidgetItem("00:00:00"))
        self.run_timer.start(1000)

        self.statusTable.setItem(1, 0, QTableWidgetItem("shop_special.py"))
        self.statusTable.setItem(2, 0, QTableWidgetItem("- 次"))
        self.statusTable.setItem(3, 0, QTableWidgetItem("准备中..."))

        self.worker = Worker(script_path)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.error_signal.connect(lambda e: self.show_info("出错", "请查看侧边栏日志", True))
        self.worker.start()

    def stop_script(self):
        if self.worker:
            self.stopBtn.setText("停止中...")
            self.stopBtn.setEnabled(False)
            self.worker.stop()

    def on_finished(self):
        self.toggle_ui(False)
        self.stopBtn.setText("停止运行")
        self.run_timer.stop()
        self.start_timestamp = None
        self.clear_table_data()
        self.show_info("结束", "任务已停止")

    def reset_shop_config(self):
        print(">>> 正在重置店长特供配置...")
        self.show_info("提示", "配置已成功重置")

    def toggle_ui(self, running):
        self.runShopBtn.setEnabled(not running)
        self.runDebugBtn.setEnabled(not running)
        self.scriptComboBox.setEnabled(not running)
        self.refreshBtn.setEnabled(not running)
        self.stopBtn.setEnabled(running)
        if running:
            self.progressBar.show()
            self.progressBar.setRange(0, 0)
        else:
            self.progressBar.hide()

    def show_info(self, title, content, is_error=False):
        func = InfoBar.error if is_error else InfoBar.success
        func(title=title, content=content, position=InfoBarPosition.TOP_RIGHT, parent=self, duration=3000)

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
        super().closeEvent(event)


# ============================================
# 5. 其他设置页面 (包含邮件和热重载)
# ============================================
class OtherSettingInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('otherSettingInterface')
        self.scrollWidget = QWidget()
        self.vBoxLayout = QVBoxLayout(self.scrollWidget)

        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(20)

        self.titleLabel = SubtitleLabel('其他设置', self.scrollWidget)
        self.titleLabel.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        self.vBoxLayout.addWidget(self.titleLabel)

        self.emailCard = ExpandSettingCard(
            FIF.MAIL, "邮件通知", "设置 SMTP 服务以接收自动化脚本运行结果的实时通知", self.scrollWidget
        )
        self.emailSwitch = SwitchButton()
        self.emailSwitch.setOnText("已开启")
        self.emailSwitch.setOffText("已关闭")
        if APP_CONFIG:
            self.emailSwitch.setChecked(APP_CONFIG.get("email_enabled", False))
        self.emailSwitch.checkedChanged.connect(
            lambda checked: APP_CONFIG.set("email_enabled", checked) if APP_CONFIG else None
        )
        self.emailCard.addWidget(self.emailSwitch)

        self.emailConfigWidget = QWidget()
        self.configLayout = QVBoxLayout(self.emailConfigWidget)
        self.configLayout.setContentsMargins(20, 10, 20, 20)
        self.configLayout.setSpacing(15)

        def add_row(label, key, widget, default=""):
            row = QHBoxLayout()
            row.addWidget(BodyLabel(label))
            val = APP_CONFIG.get(key, default) if APP_CONFIG else default
            widget.setText(val)
            widget.textChanged.connect(lambda t: APP_CONFIG.set(key, t) if APP_CONFIG else None)
            row.addWidget(widget, 1)
            self.configLayout.addLayout(row)
            return widget

        self.smtpInput = add_row("SMTP 服务器:", "email_smtp", LineEdit(), "smtp.qq.com")
        self.portInput = add_row("SMTP 端口号:", "email_port", LineEdit(), "465")
        self.senderInput = add_row("发件人邮箱:", "email_sender", LineEdit())
        self.pwdInput = PasswordLineEdit()
        self.pwdInput.setPlaceholderText("填入邮箱授权码")
        add_row("邮箱授权码:", "email_pwd", self.pwdInput)
        self.receiverInput = add_row("收件人邮箱:", "email_receiver", LineEdit())

        self.testMailBtn = PushButton("发送测试邮件")
        self.testMailBtn.setIcon(FIF.MAIL)
        self.testMailBtn.clicked.connect(self.test_send_mail)
        self.configLayout.addWidget(self.testMailBtn, 0, Qt.AlignmentFlag.AlignRight)

        self.emailCard.viewLayout.addWidget(self.emailConfigWidget)
        self.vBoxLayout.addWidget(self.emailCard)

        self.reloadUtilsCard = SettingCard(
            FIF.SYNC, "开发与调试", "重新加载 utils 模块，修改底层代码后无需重启即可生效", self.scrollWidget
        )
        self.reloadUtilsBtn = PushButton("重载 Utils", self.reloadUtilsCard)
        self.reloadUtilsBtn.setIcon(FIF.UPDATE)
        self.reloadUtilsBtn.clicked.connect(self.reload_utils)

        self.reloadUtilsCard.hBoxLayout.addStretch(1)
        self.reloadUtilsCard.hBoxLayout.addWidget(self.reloadUtilsBtn)
        self.reloadUtilsCard.hBoxLayout.addSpacing(15)
        self.vBoxLayout.addWidget(self.reloadUtilsCard)
        self.vBoxLayout.addStretch(1)

    def test_send_mail(self):
        self.testMailBtn.setEnabled(False)
        self.testMailBtn.setText("发送中...")

        def worker():
            try:
                from utils.notification import send_notification
                result = send_notification("自动化平台 - 测试邮件", "测试成功！")
                success, msg = result if result else (False, "无返回结果")
                QMetaObject.invokeMethod(self, "show_msg", Qt.ConnectionType.QueuedConnection,
                                         Q_ARG(str, "success" if success else "error"), Q_ARG(str, msg))
            except Exception as e:
                QMetaObject.invokeMethod(self, "show_msg", Qt.ConnectionType.QueuedConnection,
                                         Q_ARG(str, "error"), Q_ARG(str, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def reload_utils(self):
        self.reloadUtilsBtn.setEnabled(False)
        self.reloadUtilsBtn.setText("重载中...")
        try:
            import importlib
            import utils.tools
            importlib.reload(utils.tools)
            global set_running_state, StopScriptException, APP_CONFIG
            set_running_state = utils.tools.set_running_state
            StopScriptException = utils.tools.StopScriptException
            APP_CONFIG = utils.tools.config_mgr

            # 重新绑定分发单例的插头，防止断连
            main_win = self.window()
            if main_win:
                utils.tools.status_notifier.callback = main_win.homeInterface.on_status_updated
                if hasattr(main_win, 'logInterface'):
                    utils.tools.status_notifier.log_callback = main_win.logInterface.append_log

            InfoBar.success("操作成功", "Utils 已重新加载", position=InfoBarPosition.TOP_RIGHT, parent=self)
            print("=== Utils 模块重载成功 ===")
        except Exception as e:
            InfoBar.error("重载失败", str(e), position=InfoBarPosition.TOP_RIGHT, parent=self)
        finally:
            self.reloadUtilsBtn.setEnabled(True)
            self.reloadUtilsBtn.setText("重载 Utils")

    @pyqtSlot(str, str)
    def show_msg(self, type_str, msg):
        self.testMailBtn.setEnabled(True)
        self.testMailBtn.setText("发送测试邮件")
        if type_str == "success":
            InfoBar.success("成功", msg, position=InfoBarPosition.TOP_RIGHT, parent=self)
        else:
            InfoBar.error("失败", msg, position=InfoBarPosition.TOP_RIGHT, parent=self)


# ============================================
# 6. 基础设置页面
# ============================================
class SettingInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName('settingInterface')
        self.scrollWidget = QWidget()
        self.vBoxLayout = QVBoxLayout(self.scrollWidget)

        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(20)

        self.titleLabel = SubtitleLabel('基础设置', self.scrollWidget)
        self.titleLabel.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        self.vBoxLayout.addWidget(self.titleLabel)

        # ====== 新增：开发者选项卡片 ======
        self.debugCard = SettingCard(
            FIF.DEVELOPER_TOOLS,
            "开发者选项",
            "开启后，将在【控制台】页面显示“脚本调试模式”",
            self.scrollWidget
        )
        self.debugSwitch = SwitchButton()
        self.debugSwitch.setOnText("已开启")
        self.debugSwitch.setOffText("已关闭")

        # 读取初始配置
        is_debug = APP_CONFIG.get("debug_mode", False) if APP_CONFIG else False
        self.debugSwitch.setChecked(is_debug)
        self.debugSwitch.checkedChanged.connect(self.on_debug_changed)

        self.debugCard.hBoxLayout.addWidget(self.debugSwitch)
        self.debugCard.hBoxLayout.addSpacing(15)

        self.vBoxLayout.addWidget(self.debugCard)
        self.vBoxLayout.addStretch(1)

    def on_debug_changed(self, is_checked):
        if APP_CONFIG:
            APP_CONFIG.set("debug_mode", is_checked)

        # 动态通知 HomeInterface 更新卡片显示状态
        if hasattr(self.window(), "homeInterface"):
            self.window().homeInterface.set_debug_visibility(is_checked)


# ============================================
# 7. 主窗口组装
# ============================================
class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setProperty("game_connected", False)
        self.setWindowTitle('异环 自动化平台')
        icon_path = os.path.join(PROJECT_ROOT, 'assets', 'logo.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(950, 720)

        # 1. 连接应用
        self.connectInterface = ConnectInterface(self)
        self.connectInterface.setObjectName('connectInterface')
        self.addSubInterface(self.connectInterface, FIF.LINK, '连接应用')

        # 2. 控制台主页
        self.homeInterface = HomeInterface(self)
        self.homeInterface.setObjectName('homeInterface')
        self.addSubInterface(self.homeInterface, FIF.HOME, '控制台')

        # 3.其他设置页面
        self.otherSettingInterface = OtherSettingInterface(self)
        self.otherSettingInterface.setObjectName('otherSettingInterface')
        self.addSubInterface(self.otherSettingInterface, FIF.SETTING, '其他设置')

        # 4. 实例化详细日志面板
        self.logInterface = LogInterface(self)
        self.logInterface.setObjectName('logInterface')

        # 同时打通通知单例的 log 数据流向
        from utils.tools import status_notifier
        status_notifier.log_callback = self.logInterface.append_log

        # 对系统标准的 print 劫持，加入详细日志面板
        self.original_stdout = sys.stdout
        self.emitting_stream = EmittingStream()
        self.emitting_stream.textWritten.connect(self.logInterface.append_log)
        sys.stdout = self.emitting_stream

        # 锁定日志面板在“设置”上方 (NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.logInterface, FIF.DOCUMENT, '详细日志', NavigationItemPosition.BOTTOM)

        # 5. 基础设置页面
        self.settingInterface = SettingInterface(self)
        self.settingInterface.setObjectName('settingInterface')
        self.addSubInterface(self.settingInterface, FIF.SETTING, '设置', NavigationItemPosition.BOTTOM)

        # ====== 延迟 100ms 触发自动连接 ======
        QTimer.singleShot(100, self.auto_connect_on_startup)

    def auto_connect_on_startup(self):
        """应用启动时自动尝试连接"""
        print(">>> 正在尝试自动连接游戏...")

        if self.connectInterface.try_connect(silent_fail=True):
            # 连接成功，使用 FluentWidgets 内置方法跳转到控制台
            self.switchTo(self.homeInterface)

    def closeEvent(self, event):
        w = MessageBox('确认退出', '确定要关闭程序吗？', self)
        w.yesButton.setText('确定')
        w.cancelButton.setText('取消')
        if w.exec():
            sys.stdout = self.original_stdout  # 关闭前恢复系统标准流
            event.accept()
        else:
            event.ignore()


if __name__ == '__main__':
    if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, 'PassThrough'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())