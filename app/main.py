from ui import view
# import ui.view
import sys

print(f"Python路径:{sys.path}")

# 这个if是判断当前脚本文件是否为独立直接运行的,如果是,则条件通过, 
# 如果是作为模块导入到其他文件后运行到这里的,则条件不通过.  
if __name__ == "__main__":  
    view.main()