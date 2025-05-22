import tkinter as tk
import queue
import threading
import json
import os
import sys
from chess.screenshot import capture_region, get_position, update_params
from chess import engine

class SimpleGUIApp:  
    # 创建单例, 方便其他模块向主界面传递信息
    _instance = None  

    def __new__(cls, *args, **kwargs):  
        if not cls._instance:  
            cls._instance = super(SimpleGUIApp, cls).__new__(cls)  
            # 初始化实例（确保只初始化一次）  
            cls._instance.__init__(*args, **kwargs)  
        return cls._instance 
    
    # 初始化主窗口
    def __init__(self, root):  
        self.root = root  
        self.root.title("象棋助手")  

        x, y = self.read_coordinate()
        self.root.geometry(f"360x120+{x+180}+{0}") #窗口大小和位置
        self.root.resizable(False, False) # 禁用窗口缩放
        self.dot_window = None # 存储Toplevel窗口的引用

        # 创建文本框
        self.text_area = tk.Text(self.root, wrap=tk.WORD, width=16, height=6, font=("Kai", 20))  
        self.text_area.grid(row=0, column=0, padx=5, pady=5, rowspan=4)

        # 创建一个框架来包含两列按钮  
        frame_for_buttons = tk.Frame(self.root)  
        frame_for_buttons.grid(row=0, column=1, padx=5, pady=5, sticky='nsew')  
        
        # 在框架内使用网格布局  
        frame_for_buttons.grid_rowconfigure(0, weight=1)
        frame_for_buttons.grid_rowconfigure(1, weight=1)
        frame_for_buttons.grid_rowconfigure(2, weight=1)
        frame_for_buttons.grid_columnconfigure(0, weight=1)  
        frame_for_buttons.grid_columnconfigure(1, weight=1)

        # 创建右侧第一列按钮
        self.button_1 = tk.Button(frame_for_buttons, text="显示原点",  command=self.on_button_click_1)
        self.button_1.grid(row=0, column=0, padx=2, pady=5)

        self.button_2 = tk.Button(frame_for_buttons, text="窗口置顶",  command=self.on_button_click_2)
        self.button_2.grid(row=1, column=0, padx=2, pady=5)

        self.button_3 = tk.Button(frame_for_buttons, text="开始下棋",  command=self.on_button_click_3)
        self.button_3.grid(row=2, column=0, padx=2, pady=5)

        # 创建右侧第二列按钮
        self.button_4 = tk.Button(frame_for_buttons, text="重新计算",  command=self.on_button_click_4)
        self.button_4.grid(row=0, column=1, padx=2, pady=5)

        # self.button_5 = tk.Button(frame_for_buttons, text="按钮5")
        # self.button_5.grid(row=1, column=1, padx=5, pady=5)

        # self.button_6 = tk.Button(frame_for_buttons, text="按钮6", command=self.on_button_click_6)
        # self.button_6.grid(row=2, column=2, padx=5, pady=5, sticky='nsew')
        
        self.engine_params = {"platform":"TT","movetime":"3000","depth":"20","goParam":"depth"}
        update_params(self.engine_params)

        # 创建右侧第二列下拉菜单
        self.menu_options = ["depth", "movetime"]
        self.variable = tk.StringVar(self.root)  
        self.variable.set(self.menu_options[0])  # 默认选择第一个选项  
        self.variable.trace_add("write", self.on_option_change)
        self.option_menu = tk.OptionMenu(frame_for_buttons, self.variable, *self.menu_options)  
        self.option_menu.grid(row=1, column=1, padx=2, pady=5) 

        # 创建一个框架来包含两个小按钮  
        frame_for_buttons_6 = tk.Frame(frame_for_buttons)  
        frame_for_buttons_6.grid(row=2, column=1, padx=2, pady=5)  
        
        # 在框架内使用网格布局  
        frame_for_buttons_6.grid_rowconfigure(0, weight=1)
        frame_for_buttons_6.grid_columnconfigure([0,1,2], weight=1)  
        
        button_6a = tk.Button(frame_for_buttons_6, text="+", command=self.on_button_click_add)  
        button_6a.grid(row=0, column=0, sticky="ew")  

        key = self.menu_options[0]
        default_text = self.engine_params[key]
        self.lbl_value = tk.Label(frame_for_buttons_6, text=default_text)
        self.lbl_value.grid(row=0, column=1, sticky="ew")

        button_6b = tk.Button(frame_for_buttons_6, text="-", command=self.on_button_click_cut)  
        button_6b.grid(row=0, column=2, sticky="ew") 

        # 配置行和列的权重，使按钮高度与文本框相当
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure([0, 1], weight=1)

        # 初始化文本（空）  
        self.lines = [""] * 3  
        # 添加事件对象来控制capture_region线程的停止  
        self.stop_event = threading.Event() 

        # 是否监听 S 键
        self.listening_k = False
        # 窗口置顶/取消置顶
        self.is_on_top = False
        # 棋盘原点/重新定位
        self.is_show_dot = True
        # 开始下棋/停止下棋
        self.is_start = True
        # 给检查队列的定时器设置id,便于管理定时器
        self.check_queue_id = None

        # self.root.after(500, lambda: print(f"按钮的尺寸：宽度={self.button_4.winfo_width()}, 高度={self.button_4.winfo_height()}"))

    # 按钮: 棋盘原点/棋盘定位
    def on_button_click_1(self):  
        if self.is_show_dot:
            self.is_show_dot = False
            self.button_1.config(text="重新定位")
            self.coordinate_origin_dot()
        else:
            self.text_area.delete(1.0, tk.END)
            self.text_area.insert(tk.END, "将光标移到棋盘左上角,\n不要点击,\n然后按下S键~", ) 
            self.start_listening_k()

    # 按钮: 窗口置顶/取消
    def on_button_click_2(self):  
        if not self.is_on_top:
            self.root.attributes('-topmost', True)  # 将窗口置于顶层
            self.button_2.config(text="取消置顶")
        else:
            self.root.attributes('-topmost', False)
            self.button_2.config(text="窗口置顶")
        self.is_on_top = not self.is_on_top
  
    # 按钮:开始下棋/停止下棋
    def on_button_click_3(self):  
        if self.is_start:
            self.button_3.config(text="停止下棋")
            self.create_queue()
        else:
            self.button_3.config(text="开始下棋")
            # 设置事件，通知capture_region线程停止
            self.stop_event.set() 
            # 关闭引擎进程
            engine.terminate_engine()
        self.is_start = not self.is_start
        
    # 按钮:重新计算
    def on_button_click_4(self):  
        self.button_3.config(text="停止下棋") #重新计算实际就是重启while循环,等同于"开始下棋",只是不会重复启动引擎
        self.is_start = False
        if self.check_queue_id is not None:
            self.root.after_cancel(self.check_queue_id)
        self.stop_event.set()
        self.stop_event.clear()
        self.create_queue()
    
    # 在子线程中执行截图和引擎计算逻辑
    def create_queue(self):
        # 首先停止之前的线程（如果有的话）  
        if hasattr(self, 'capture_thread') and self.capture_thread.is_alive():  
            self.stop_event.set()  # 通知正在运行的线程停止  
            self.capture_thread.join()  # 等待线程结束  
    
        # 重置停止事件  
        self.stop_event.clear() 

        #创建一个线程和队列,用于执行截图和返回引擎计算结果
        self.result_queue = queue.Queue()  
        self.capture_thread = threading.Thread(target=self.capture_func, args=(self.result_queue,))  
        self.capture_thread.start()
        # 创建一个定时器来定期检查队列  
        self.check_queue_id = self.root.after(100, self.check_queue) 

    # 简单封装一下对capture_region的调用,避免直接调用  
    def capture_func(self, result_queue):  
        capture_region(result_queue, self.stop_event)

    def check_queue(self):  
        if not self.result_queue.empty():  
            text = self.result_queue.get()  
            self.update_text(text)  
        # 继续检查队列，每100毫秒检查一次  
        self.root.after(100, self.check_queue) 

    # 下拉菜单
    def on_option_change(self, *args):
        selected_option = self.variable.get()
        self.engine_params["goParam"] = selected_option
        self.lbl_value["text"] = f"{self.engine_params[selected_option]}"
        update_params(self.engine_params)

    # 按钮 +    
    def on_button_click_add(self): 
        key = self.engine_params["goParam"]
        param_value = int(self.engine_params[key])

        if key == "depth" and param_value < 200:
            param_value = param_value+1
        elif key == "movetime" and param_value < 20000:
            param_value = param_value+2000

        self.engine_params[key] = f"{param_value}"
        self.lbl_value["text"] = f"{param_value}"
        update_params(self.engine_params)
    
    # 按钮 -
    def on_button_click_cut(self): 
        key = self.engine_params["goParam"]
        param_value = int(self.engine_params[key])
        if key == "depth" and param_value > 1:
            param_value = param_value-1
        elif key == "movetime" and param_value > 2000:
            param_value = param_value-2000
        self.engine_params[key] = f"{param_value}"
        self.lbl_value["text"] = f"{param_value}"
        update_params(self.engine_params)
        
    # 监听 S 键
    def start_listening_k(self):
        self.listening_k = True
        self.root.bind('<KeyPress-s>', self.on_key_press)

    def on_key_press(self, event):
        if self.listening_k:
            board_region = get_position()
            x = board_region['left']
            y = board_region['top']-10
            if self.dot_window is not None:  
                # 更新Toplevel窗口的位置  
                self.dot_window.geometry(f"10x10+{x}+{y}")
                self.text_area.delete(1.0, tk.END)
                self.text_area.insert(tk.END, "定位完成!\n")
            
    

    def update_text(self, text):    
        # 更新文本  
        if len(text) == 4:
            self.lines = ["", self.lines[2], text] 
        else:
            self.lines = [text, self.lines[1], self.lines[2]] 
        # print(self.lines)
  
        # 清空ScrolledText  
        self.text_area.delete(1.0, tk.END)  
  
        # 重新插入文本，并设置不同的字体大小  
        for i, line in enumerate(self.lines):  
            if i == 0:  
                font_size = 18
                font_color="red"
            elif i == 1:  
                font_size = 26
                font_color=""
            else:  
                font_size = 34
                font_color="white"
            self.text_area.tag_config(f"size{i}", foreground=font_color, font=("Kai", font_size))  
            self.text_area.insert(tk.END, line + "\n", f"size{i}")  

        # 第三行闪烁
        if len(text) == 4:
            self.text_flash()

    def text_flash(self):
        self.root.after(200)
        self.text_area.tag_config("size2", foreground="red", font=("Kai", 34))
        self.root.update()
        self.root.after(200)
        self.text_area.tag_config("size2", foreground="white", font=("Kai", 26))
        self.root.update()
        self.root.after(200)
        self.text_area.tag_config("size2", foreground="red", font=("Kai", 34))
        self.root.update()


    def coordinate_origin_dot(self):  
        # 读取本地坐标文件
        x, y = self.read_coordinate()

        # 创建一个Toplevel窗口  
        self.dot_window = tk.Toplevel(self.root)  
        self.dot_window.overrideredirect(True)  # 移除窗口的边框和标题栏  
        self.dot_window.geometry(f"10x10+{x}+{y}")  # 设置窗口大小为10x10，并放置在指定位置  
    
        # 在窗口中绘制红点  
        canvas = tk.Canvas(self.dot_window, width=10, height=10, bg='red')  
        canvas.pack()  
        canvas.create_oval(0, 0, 10, 10, fill='red')  # 绘制一个红色的圆点 

    def read_coordinate(self):
        print(f"工作路径:{os.getcwd()}")
        x = 400
        y = 200
        try:  
            # 读取存在本地的坐标 
            file_path = self.resource_path("json/coordinates.json")
            print(f"当前路径:{file_path}")
            with open(file_path, 'r') as file:
                data = json.load(file)
                board_region = data['region1']
                x = board_region['left']
                y = board_region['top']-10  
        except FileNotFoundError:  
            print("未找到coordinates.json文件") 
        return x, y
    
    def resource_path(self, relative_path):  
        """ 获取资源文件的绝对路径 """  
        if hasattr(sys, '_MEIPASS'):  
            # 如果是打包后的应用，则使用 sys._MEIPASS  
            return os.path.join(sys._MEIPASS, relative_path)  
        return os.path.join(os.path.abspath("./chess_assistant/app/"), relative_path) 
    
# 创建并显示GUI  
def main():  
    root = tk.Tk()  
    app = SimpleGUIApp(root)  
    root.mainloop() 