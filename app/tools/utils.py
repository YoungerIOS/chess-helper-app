import numpy as np
import os
import sys
import platform
from PIL import Image
import imagehash

# 管理开发环境与打包环境下的路径
def resource_path(*path_parts):
    """获取资源文件的绝对路径
    
    Args:
        *path_parts: 路径组件，如 'images', 'media', 'chessboard1.png'
                   或者单个字符串如 'json/game_config.json'
        
    Returns:
        str: 资源文件的绝对路径
        
    Examples:
        resource_path('json', 'game_config.json')
        resource_path('images', 'media', 'chessboard1.png')
        resource_path('json/game_config.json')  # 向后兼容
    """
    # 如果只有一个参数且包含路径分隔符，保持向后兼容
    if len(path_parts) == 1 and ('/' in path_parts[0] or '\\' in path_parts[0]):
        relative_path = path_parts[0]
    else:
        # 使用 os.path.join 构建路径
        relative_path = os.path.join(*path_parts)
    
    return _resource_path_impl(relative_path)

def _resource_path_impl(relative_path):
    """获取资源文件的绝对路径
    
    Args:
        relative_path: 相对于app目录的路径，如 'json/game_config.json'
        
    Returns:
        str: 资源文件的绝对路径
    """
    # 打包环境处理
    if hasattr(sys, '_MEIPASS'):
        return _get_packaged_resource_path(relative_path)
    
    # 开发环境处理
    return _get_development_resource_path(relative_path)

def _get_packaged_resource_path(relative_path):
    """获取打包环境下的资源路径"""
    base = sys._MEIPASS
    
    # 标准打包路径
    candidates = [
        os.path.join(base, 'app', relative_path),
        os.path.join(base, relative_path),
    ]
    
    # macOS .app 特殊路径
    if platform.system() == "Darwin":
        try:
            macos_dir = os.path.dirname(sys.executable)
            resources_dir = os.path.abspath(os.path.join(macos_dir, '..', 'Resources'))
            candidates.extend([
                os.path.join(resources_dir, 'app', relative_path),
                os.path.join(resources_dir, relative_path),
            ])
        except (OSError, ValueError):
            pass
    
    # 返回第一个存在的路径
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    
    # 如果都不存在，返回最可能的路径
    return candidates[0]

def _get_development_resource_path(relative_path):
    """获取开发环境下的资源路径"""
    # 获取当前文件所在目录（app/tools/）
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 获取项目根目录
    project_root = os.path.dirname(os.path.dirname(current_dir))
    # 构建app目录路径
    app_dir = os.path.join(project_root, 'app')
    
    # 开发环境的候选路径
    candidates = [
        os.path.join(app_dir, relative_path),  # 标准路径
        os.path.join(project_root, relative_path),  # 备用路径
    ]
    
    # 返回第一个存在的路径
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    
    # 如果都不存在，返回标准路径
    return candidates[0]

# 统一的路径管理方法
def get_app_cache_dir():
    """获取应用缓存目录"""
    if platform.system() == "Darwin":  # macOS
        # 使用 ~/Library/Caches/ChessHelper/
        home_dir = os.path.expanduser("~")
        cache_dir = os.path.join(home_dir, "Library", "Caches", "ChessHelper")
    elif platform.system() == "Windows":  # Windows
        # 使用 %LOCALAPPDATA%\ChessHelper\Cache\
        localappdata = os.environ.get('LOCALAPPDATA', os.path.expanduser("~"))
        cache_dir = os.path.join(localappdata, "ChessHelper", "Cache")
    else:  # Linux
        # 使用 ~/.cache/chess-helper/
        home_dir = os.path.expanduser("~")
        cache_dir = os.path.join(home_dir, ".cache", "chess-helper")
    
    # 确保目录存在
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def get_app_data_dir():
    """获取应用数据目录"""
    if platform.system() == "Darwin":  # macOS
        # 使用 ~/Library/Application Support/ChessHelper/
        home_dir = os.path.expanduser("~")
        data_dir = os.path.join(home_dir, "Library", "Application Support", "ChessHelper")
    elif platform.system() == "Windows":  # Windows
        # 使用 %APPDATA%\ChessHelper\
        appdata = os.environ.get('APPDATA', os.path.expanduser("~"))
        data_dir = os.path.join(appdata, "ChessHelper")
    else:  # Linux
        # 使用 ~/.local/share/chess-helper/
        home_dir = os.path.expanduser("~")
        data_dir = os.path.join(home_dir, ".local", "share", "chess-helper")
    
    # 确保目录存在
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

def app_cache_path(filename):
    """获取调试图片的完整路径"""
    cache_dir = get_app_cache_dir()
    full_path = os.path.join(cache_dir, filename)
    # 确保子目录存在
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path

def app_data_path(filename):
    """获取配置文件的完整路径"""
    data_dir = get_app_data_dir()
    full_path = os.path.join(data_dir, filename)
    # 确保子目录存在
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    return full_path


def get_engine_dir():
    """获取引擎文件夹路径，目录不存在时自动创建。

    开发环境使用 app 目录下的 Pikafish/ 文件夹；打包环境没有可写的
    资源目录，沿用用户数据目录中的 Pikafish/ 文件夹。
    """
    if getattr(sys, "frozen", False):
        engine_dir = os.path.join(get_app_data_dir(), "Pikafish")
    else:
        engine_dir = resource_path("Pikafish")
    os.makedirs(engine_dir, exist_ok=True)
    return engine_dir

def engine_path(*path_parts):
    """获取引擎文件夹内文件的完整路径"""
    return os.path.join(get_engine_dir(), *path_parts)

def user_config_path():
    """返回可写的用户配置路径，避免修改随应用分发的资源文件。"""
    return app_data_path("game_config.json")
 
# 筛选水平线
def filter_horizontal_lines(lines, img_width):  
    xMin = float('inf')  # 使用正无穷大作为x坐标最小值的初始值  
    xMax = float('-inf') # 使用负无穷大作为x坐标最大值的初始值  
    horizontal_lines = [] 
    for line in lines: 
        for x1, y1, x2, y2 in line:  
            if y1 == y2:  # 水平线  
                # 找出x坐标最小和最大的  
                xMin = min(xMin, min(x1, x2))  
                xMax = max(xMax, max(x1, x2))  
                # 直接将水平线添加到列表中  
                horizontal_lines.append(line) 
    result = keep_middle_lines(horizontal_lines, img_width, 'y') # 有些离的很近的直线 仅保留中间那条
    return result, xMin, xMax 

# 筛选竖直线
def filter_vertical_lines(lines, img_width):  
    yMin = float('inf')  # 使用正无穷大作为初始值  
    yMax = float('-inf') # 使用负无穷大作为初始值  
    vertical_lines = []  
  
    for line in lines:  
        for x1, y1, x2, y2 in line:  
            if x1 == x2:  # 纵线，竖线  
                # 找出纵坐标最小和最大的  
                yMin = min(yMin, min(y1, y2))  
                yMax = max(yMax, max(y1, y2))  
                # 直接将垂直线添加到列表中  
                vertical_lines.append(line)  
    result = keep_middle_lines(vertical_lines, img_width, 'x')
    return result, yMin, yMax

# 相邻很近的多条直线 取中间那条
def keep_middle_lines(lines, img_width, axis='y'):
    sorted_lines = sorted(lines, key=lambda x: x[0][1] if axis == 'y' else x[0][0])  # 按指定轴坐标排序

    square_side = img_width/9 # 棋盘格子边长取: 棋盘宽度/9
    #删除多余的线
    gap = square_side * 0.6 # 取格子宽度的0.6倍
    result_lines = []
    i = 0
    while i < len(sorted_lines):
        start_index = i
        # 找到间距小于 gap 的连续直线组
        while i < len(sorted_lines) - 1 and abs((sorted_lines[i + 1][0][1] if axis == 'y' else sorted_lines[i + 1][0][0]) - (sorted_lines[i][0][1] if axis == 'y' else sorted_lines[i][0][0])) <= gap:
            i += 1
        end_index = i
        if end_index - start_index + 1 > 1:  # 存在相邻且间距小于 gap 的直线组
            middle_index = (start_index + end_index) // 2
            result_lines.append(sorted_lines[middle_index])
        else:  # 单个直线或间距大于 gap 的直线
            result_lines.append(sorted_lines[i])
        i += 1

    # 补充缺少的横线
    if axis == 'y' and len(result_lines) < 10:
        x1, y1, x2, y2 = result_lines[0][0]
        if y1 > square_side:
            result_lines.insert(0, np.array([[x1, y1 - square_side, x2, y2 - square_side]], dtype=np.int32))
        a1, b1, a2, b2 = result_lines[-1][0]
        if b1 < img_width: # 近似认为img_width = 0.9*img_height 
            result_lines.append(np.array([[a1, b1 + square_side, a2, b2 + square_side]], dtype=np.int32))
     
    return result_lines

# 截取棋子图片名称中的字母代号
def cut_substring(string):
    index_ = string.find('_')
    index_dot = string.find('.')
    if index_!= -1 and index_dot!= -1:
        string = string[index_ + 1:index_dot]
        
    return string

# 判断某一方有没有走子
def check_repeat_position(array1, array2, is_red):
    if not array2:
        return False
    
    letter_change = False
    # upper_case_loss = False
    # 检查小写字母位置是否变化,以确定是不是黑棋走了一步
    for i in range(len(array1)):  # 遍历第一个数组的每一行
        for j in range(len(array1[i])):  # 遍历每一行的每一列
            # 检查哪一方
            letter = array1[i][j].islower() if is_red else array1[i][j].isupper()
            if letter and array1[i][j]!= array2[i][j]:  # 如果是小写(大写)字母且在两个数组中的对应位置字符不同
                letter_change = True  # 标记小写(大写)字母位置发生变化
                break  # 一旦发现有变化，就立即停止当前行的检查
        if letter_change:  # 如果在当前行发现了变化
            break  # 停止整个双层循环        
    # # 检查大写字母是否减少
    # upper_case_count1 = sum(1 for row in array1 for item in row if item.isupper())
    # upper_case_count2 = sum(1 for row in array2 for item in row if item.isupper())
    # if upper_case_count1 > upper_case_count2:
    #     upper_case_loss = True
    
    # 字母有变化即不是重复局面,取反返回
    return not letter_change

# 棋子数组转为FEN棋局字符串(不含轮哪方走棋信息)
def convert_array_to_fen(array, is_red):
    # 本方是黑方就反向遍历
    if not is_red:
        array = [row[::-1] for row in array[::-1]] 

    rows = []  
    for row in array:  
        # 初始化当前行的字符串和连续短横线计数器 
        row_str = []  
        empty_count = 0  

        # 遍历行中的每个元素  
        for cell in row:  
            if cell == '-':  
                # 如果当前是空位，增加连续空位的计数器  
                empty_count += 1 
            else:  
                # 如果是棋子，先处理之前的连续空位  
                if empty_count > 0:  
                    row_str.append(str(empty_count))  
                    empty_count = 0  
                # 添加非空元素  
                row_str.append(cell)  
  
        # 处理行末尾的连续空位  
        if empty_count > 0:  
            row_str.append(str(empty_count))  
  
        # 将当前行的字符串列表转换为单个字符串，并添加到结果列表中  
        rows.append(''.join(row_str))  

    fen_string = "/".join(rows)
    return fen_string, array

# 着法move转文字描述
def convert_move_to_chinese(move, board_array, is_red): 
    if not move or len(move) != 4:
        raise ValueError("着法为空或格式错误")
    # 棋子代码与中文名称的对应关系  
    PIECE_CODES = {  
        'r': '車',  
        'n': '馬',  
        'b': '象',  
        'a': '士',  
        'k': '将',  
        'p': '卒',  
        'c': '砲',  
        'R': '俥',  
        'N': '傌',  
        'B': '相',  
        'A': '仕',  
        'K': '帥',  
        'P': '兵',
        'C': '炮',
        'x': '暗',
        'X': '暗',
        '-': '空'
    }  

    CHINESE_NUM = {  
        0: '零',  
        1: '一',  
        2: '二',  
        3: '三',  
        4: '四',  
        5: '五',  
        6: '六',  
        7: '七',  
        8: '八',  
        9: '九'  
    }
  
    # 解析输入字符串，获取起点和终点坐标  
    start_col_char, start_row_str, end_col_char, end_row_str = move[0], move[1:2], move[2:3], move[-1]
 
    start_row = int(start_row_str) 
    end_row = int(end_row_str) 
    start_col = (ord(start_col_char) - ord('a')) 
    end_col = (ord(end_col_char) - ord('a')) 
    # print(f'起始列{start_col}, 起始行{start_row}, 最终列{end_col}, 最终行{end_row}') 
      
    # 从棋局数组中获取棋子类型  
    if is_red:
        # 红方在下: Row 0=Rank 9, Row 9=Rank 0
        # Rank r -> Row 9-r
        # Col c(a=0) -> Col c
        row_idx = 9 - start_row
        col_idx = start_col
    else:
        # 黑方在下: Row 0=Rank 0, Row 9=Rank 9
        # Rank r -> Row r
        # Col c(a=0) -> Col 8-c
        row_idx = start_row
        col_idx = 8 - start_col
        
    piece_type = board_array[row_idx][col_idx]
    
    # 验证起点是否有棋子，以及是否属于我方（防止空着法和对方着法）
    if piece_type == '-':
        return None
    
    is_my_piece = (is_red and piece_type.isupper()) or (not is_red and piece_type.islower())
    if not is_my_piece:
        return None

    piece_name = PIECE_CODES[piece_type]  
  
    # 判断移动类型（进、退、平）和构建棋谱描述
    start_colunm = CHINESE_NUM[(9 - start_col)] if is_red else (start_col + 1) 
    end_colunm   = CHINESE_NUM[(9 - end_col)] if is_red else (end_col + 1)
    crossed_row  = CHINESE_NUM[abs(end_row - start_row)] if is_red else abs(end_row - start_row)

    name = piece_name
    # 特殊情况: 如果同一列上有两个相同的棋子(车车,马马,炮炮,兵兵)(同列有2个以上兵的情况暂不考虑)
    if piece_type in ['r', 'R', 'n', 'N', 'c', 'C', 'p', 'P']:
        # 寻找相同棋子,返回首个找到的元素索引
        col_of_board = [row[start_col] for row in board_array]#遍历出要走的棋子所在的列上的所有棋子
        if col_of_board.count(piece_type) > 1: # 某类棋子数量大于1
            if col_of_board.index(piece_type) == 9 - start_row: 
            # 有2个同名棋子, index返回首次找到的,与目标棋子对比可以确定前后关系
                name = "前" if is_red else "后"
            else:
                name = "后" if is_red else "前"
            # 第二个字改为棋子名称
            start_colunm = piece_name

    # 普通情况
    if start_row == end_row:  
        # 平移  
        direction = "平"  
        # 所有棋子在平移时，末尾数字都表示列数  
        desc = f"{name}{start_colunm}{direction}{end_colunm}"  
    else:  
        # 前进或后退 
        action1 = "进" if is_red else "退"
        action2 = "退" if is_red else "进"
        direction = action1 if start_row < end_row else action2

        # 车、炮、卒、将帅 在描述"进" "退" 时，末尾数字是跨越的行数  
        if piece_type in ['r', 'R', 'c', 'C', 'p', 'P', 'k', 'K']:  
            desc = f"{name}{start_colunm}{direction}{crossed_row}"
        else:  
            # 马、象、士在"进" "退" 时，末尾数字是终点所在列数
            desc = f"{name}{(start_colunm)}{direction}{end_colunm}" 

    return desc

def convert_coords_to_move(from_pos, to_pos, is_red=False):
    """
    将棋盘坐标(from_pos, to_pos)转为move字符串.
    - a0始终是红方视角的左下角
    - from_pos, to_pos: (row, col)，数组坐标，左上角(0,0)
    - is_red: True表示红方在下，False表示黑方在下
    """
    if from_pos is None or to_pos is None:
        return ""
    if not isinstance(from_pos, (tuple, list)) or len(from_pos) != 2:
        return ""
    if not isinstance(to_pos, (tuple, list)) or len(to_pos) != 2:
        return ""
    try:
        from_row, from_col = int(from_pos[0]), int(from_pos[1])
        to_row, to_col = int(to_pos[0]), int(to_pos[1])
    except (ValueError, TypeError):
        return ""
    if is_red:
        move_from_col = from_col
        move_to_col = to_col
        move_from_row = 9 - from_row
        move_to_row = 9 - to_row
    else:
        move_from_col = 8 - from_col
        move_to_col = 8 - to_col
        move_from_row = from_row
        move_to_row = to_row
    return f"{chr(ord('a')+move_from_col)}{move_from_row}{chr(ord('a')+move_to_col)}{move_to_row}"

def convert_to_builtin_type(obj):
    """递归转换所有numpy类型为Python内置类型"""
    import numpy as np
    
    if isinstance(obj, dict):
        return {k: convert_to_builtin_type(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_builtin_type(i) for i in obj]
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    else:
        return obj
        
def compute_image_hash(image_array):
    """
    计算图像哈希值 (dHash)
    Args:
        image_array: numpy 数组 (BGR or RGB) 或 PIL Image
    Returns:
        hash string
    """
    try:
        if isinstance(image_array, np.ndarray):
            # 转换为 PIL Image
            if image_array.ndim == 3 and image_array.shape[2] == 3:
                # 假设是 BGR (OpenCV default)，需要转 RGB
                # 但 dHash 对灰度也行，转 RGB 比较保险
                img_rgb = image_array[..., ::-1] # BGR to RGB
                pil_img = Image.fromarray(img_rgb)
            elif image_array.ndim == 2:
                 pil_img = Image.fromarray(image_array)
            else:
                 return None
        elif isinstance(image_array, Image.Image):
            pil_img = image_array
        else:
            return None
            
        return str(imagehash.dhash(pil_img))
    except Exception:
        return None
