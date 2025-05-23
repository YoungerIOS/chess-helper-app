import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QLoggingCategory
from ui.main_window import MainWindow

# 禁用ICC相关的警告
QLoggingCategory.setFilterRules("qt.gui.icc.warning=false")

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

# 这个if是判断当前脚本文件是否为独立直接运行的,如果是,则条件通过, 
# 如果是作为模块导入到其他文件后运行到这里的,则条件不通过.  
if __name__ == "__main__":  
    main()