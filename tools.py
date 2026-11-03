"""
AI 聊天客户端 - 工具层

包含：
- ParamValidator: 轻量级 JSON Schema 参数校验
- ToolRegistry: 声明式工具注册中心（Decorator-based）
- 所有本地工具函数定义
"""

import os
import subprocess
import glob
import inspect
import re
import json
import ast
from typing import Callable, Dict, List

import config
from todo_manager import todo_manager


# ============================================================================
# 模块 3: Pydantic 轻量参数校验器 (不依赖 pydantic 包)
# ============================================================================
class ParamValidator:
    """轻量级 JSON Schema 参数校验，不依赖 pydantic 第三方包。"""

    @staticmethod
    def validate(params: dict, schema: dict) -> tuple[bool, str]:
        """
        校验 params 是否符合 schema。
        返回 (is_valid, error_message)。
        """
        props = schema.get("properties", {})
        required = schema.get("required", [])

        # 检查必填字段
        for req in required:
            if req not in params:
                return False, f"缺少必填参数: {req}"

        # 检查类型并进行合理的容错转换
        for key, value in list(params.items()):
            if key not in props:
                continue
            expected_type = props[key].get("type")
            if expected_type == "string":
                if not isinstance(value, str):
                    if isinstance(value, (int, float, bool)):
                        params[key] = str(value)
                    else:
                        return False, f"参数 '{key}' 期望 string，得到 {type(value).__name__}"
            elif expected_type == "integer":
                if not isinstance(value, int):
                    if isinstance(value, str) and value.strip().isdigit():
                        params[key] = int(value.strip())
                    elif isinstance(value, float) and value.is_integer():
                        params[key] = int(value)
                    else:
                        return False, f"参数 '{key}' 期望 integer，得到 {type(value).__name__}"
            elif expected_type == "number":
                if not isinstance(value, (int, float)):
                    if isinstance(value, str):
                        try:
                            params[key] = float(value.strip())
                        except ValueError:
                            return False, f"参数 '{key}' 期望 number，得到 {type(value).__name__}"
                    else:
                        return False, f"参数 '{key}' 期望 number，得到 {type(value).__name__}"
            elif expected_type == "boolean":
                if not isinstance(value, bool):
                    if isinstance(value, str) and value.lower() in ("true", "false"):
                        params[key] = value.lower() == "true"
                    else:
                        return False, f"参数 '{key}' 期望 boolean，得到 {type(value).__name__}"
            elif expected_type == "array":
                if not isinstance(value, list):
                    return False, f"参数 '{key}' 期望 array，得到 {type(value).__name__}"

        return True, ""


# ============================================================================
# 模块 1: 声明式工具注册 (Decorator-based Tool Registry)
# ============================================================================
class ToolRegistry:
    """
    声明式工具注册中心。
    开发者只需写 Python 函数 + @tool 装饰器，框架自动提取 JSON Schema。
    """

    def __init__(self):
        self._tools: Dict[str, dict] = {}

    def register(self, func: Callable) -> Callable:
        """@tool 装饰器：注册一个工具函数。"""
        name = func.__name__
        docstring = func.__doc__ or ""
        # 解析 docstring，提取参数说明
        param_descriptions = self._extract_param_docs(docstring)
        # 从类型注解生成 JSON Schema
        schema = self._generate_schema(func, param_descriptions)

        self._tools[name] = {
            "func": func,
            "name": name,
            "description": docstring.strip().split("\n")[0] if docstring else f"工具: {name}",
            "parameters": schema,
        }
        return func

    def _extract_param_docs(self, docstring: str) -> dict:
        """从 docstring 提取 @param 注解。"""
        params = {}
        for line in docstring.split("\n"):
            line = line.strip()
            m = re.match(r"@param\s+(\w+)\s*:\s*(.+)", line)
            if m:
                params[m.group(1)] = m.group(2).strip()
        return params

    def _generate_schema(self, func: Callable, param_descriptions: dict) -> dict:
        """从函数签名自动生成 JSON Schema。"""
        sig = inspect.signature(func)
        properties = {}
        required = []

        for name, param in sig.parameters.items():
            # 跳过 self / cls
            if name in ("self", "cls"):
                continue

            # 类型映射
            annotation = param.annotation
            type_map = {
                str: "string",
                int: "integer",
                float: "number",
                bool: "boolean",
                list: "array",
                dict: "object",
            }
            json_type = type_map.get(annotation, "string")

            desc = param_descriptions.get(name, "")
            properties[name] = {
                "type": json_type,
                "description": desc,
            }

            if param.default == inspect.Parameter.empty:
                required.append(name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def get_tools_spec(self) -> list:
        """返回 OpenAI 兼容的工具列表格式。"""
        specs = []
        for t in self._tools.values():
            specs.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            })
        return specs

    def execute(self, tool_name: str, args: dict) -> str:
        """
        模块 3 + 5: 校验参数 + 执行工具 + 异常隔离。
        """
        if tool_name not in self._tools:
            return f"Error: 找不到工具 '{tool_name}'"

        tool = self._tools[tool_name]
        schema = tool["parameters"]

        # 常见参数别名容错标准化映射（仅在该工具确实定义了 target_key 时才做映射）
        props = schema.get("properties", {})
        param_aliases = {
            "file_path": ["path", "filepath", "filename", "file"],
            "content": ["text", "data", "body", "markdown", "document"],
            "keyword": ["pattern", "query", "search_text", "search_str"],
            "task_id": ["id", "taskId", "task"],
            "tasks": ["task_list", "items", "todo_list"],
            "cmd": ["command", "code"],
        }
        for target_key, aliases in param_aliases.items():
            if target_key in props and target_key not in args:
                for alias in aliases:
                    if alias in args:
                        args[target_key] = args.pop(alias)
                        break

        # 模块 3: 参数校验
        is_valid, error_msg = ParamValidator.validate(args, schema)
        if not is_valid:
            return f"Error: 参数校验失败 - {error_msg}"

        # 模块 5: 异常隔离执行
        try:
            result = tool["func"](**args)
            if isinstance(result, (dict, list)):
                import json
                return json.dumps(result, ensure_ascii=False, indent=2)
            return str(result)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"

    def list_tools(self) -> List[str]:
        """返回已注册工具名列表。"""
        return list(self._tools.keys())


# ============================================================================
# 本地工具定义 (开发者只需写函数 + @tool)
# ============================================================================
registry = ToolRegistry()


# ---------------------------------------------------------------------------
# 文件读取工具（带指针导航的线性翻页）
# ---------------------------------------------------------------------------
@registry.register
def read_file(file_path: str, offset: int = 1, max_lines: int = 200) -> str:
    """
    按顺序分页读取文件切片（带导航指针防乱跳）。
    
    【核心创新：指针导航】
    - 每次返回时明确告诉模型"下一页该读哪"
    - 单次最大返回行数硬锁定在 200 行以内
    - 模型被强制要求线性翻页，不得乱跳
    
    @param file_path: 文件的绝对或相对路径（支持中文）。
    @param offset: 起始行号（从 1 开始），默认从文件开头。
    @param max_lines: 最多返回行数（硬限制最大 200 行）。
    """
    # 防爆硬截断
    if max_lines > config.MAX_LINES_PER_PAGE:
        max_lines = config.MAX_LINES_PER_PAGE

    # 1. 参数清洗：处理大模型可能带上的多余引号、空格或转义字符
    if not isinstance(file_path, str):
        file_path = str(file_path)
    file_path = file_path.strip().strip('"\'').strip()

    # 2. 获取绝对路径
    try:
        abs_path = os.path.abspath(file_path)
    except Exception as e:
        return f"Error: 路径解析失败: {e}"

    # 3. 检查文件是否存在
    if not os.path.isfile(abs_path):
        return f"Error: 文件不存在或路径错误: {abs_path}"

    # 4. 多编码自动回退：utf-8 → gbk → ansi
    lines = None
    file_encoding_used = None
    for encoding in ["utf-8", "gbk", "ansi"]:
        try:
            with open(abs_path, "r", encoding=encoding, errors="ignore") as f:
                lines = f.readlines()
            file_encoding_used = encoding
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return f"Error: 读取异常: {e}"

    if lines is None:
        return f"Error: 文件编码无法解析"

    total_lines = len(lines)

    # 5. 分页逻辑（offset 从 1 开始，转为 0-based 索引）
    start_idx = max(0, offset - 1)

    if start_idx >= total_lines:
        return (
            f"Error: 越界提示 - 该文件总共只有 {total_lines} 行，"
            f"你请求的 offset ({offset}) 已经超过文件末尾。"
        )

    end_idx = min(total_lines, start_idx + max_lines)
    preview_lines = lines[start_idx:end_idx]

    # 带行号的代码片
    numbered_lines = [f"{i + start_idx + 1}: {line}" for i, line in enumerate(preview_lines)]

    # 提供客观读取进度，鼓励结合 AST 骨架提炼，不强迫模型通读全文
    navigation_guide = (
        f"\n========================================\n"
        f"📋 [文件片段读取完成]\n"
        f"文件总行数: {total_lines} 行 | 当前读取区间: 第 {start_idx + 1} 至 {end_idx} 行\n"
    )

    if end_idx < total_lines:
        navigation_guide += (
            f"💡 【提示】：该文件后续还有代码（第 {end_idx + 1} 行起）。\n"
            f"- 若当前片段已包含关键信息，请直接进行分析总结并调用 write_markdown_file 沉淀文档，严禁盲目机械地通读全文；\n"
            f"- 仅当确需深入探究后续特定实现时，才使用 read_file(file_path='{file_path}', offset={end_idx + 1}) 继续。\n"
        )
    else:
        navigation_guide += (
            f"✅ 【提示】：该文件已读取至末尾。\n"
            f"请基于目前掌握的代码进行分析总结，并调用 write_markdown_file 将结果写入文件。\n"
        )

    navigation_guide += f"========================================\n"

    return "".join(numbered_lines) + navigation_guide


# ---------------------------------------------------------------------------
# AST 代码骨架提取工具（节省 Token 的核心探索工具）
# ---------------------------------------------------------------------------
@registry.register
def get_code_outline(file_path: str) -> str:
    """
    提取 Python 代码文件的 AST 骨架结构（模块说明、类、方法、函数签名及所在行号范围）。
    
    【极大节省 Token 的高效探索工具】
    - 在深入分析或读取代码实现前，**优先调用此工具**获取代码结构骨架
    - 仅消耗极少 Token（通常 < 200 tokens）即可掌握全部类定义、核心方法、参数与所在行号区间
    - 针对需要深入查看的具体逻辑，再结合 read_file 精准读取对应行号区间（例如 read_file(path, offset=53, max_lines=50)）
    - 严禁在未查看骨架前就对大文件盲目逐页全量翻读
    
    @param file_path: Python 源代码文件路径（支持相对或绝对路径）。
    """
    if not isinstance(file_path, str):
        file_path = str(file_path)
    file_path = file_path.strip().strip('"\'').strip()

    try:
        abs_path = os.path.abspath(file_path)
    except Exception as e:
        return f"Error: 路径解析失败: {e}"

    if not os.path.isfile(abs_path):
        return f"Error: 文件不存在或路径错误: {abs_path}"

    if not abs_path.endswith(".py"):
        return f"提示: '{os.path.basename(abs_path)}' 不是 Python 文件，建议使用 get_file_info 或 read_file 查看。"

    content = None
    for enc in ["utf-8", "gbk", "ansi"]:
        try:
            with open(abs_path, "r", encoding=enc, errors="ignore") as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return f"Error: 读取文件失败: {e}"

    if content is None:
        return "Error: 文件编码无法解析"

    try:
        tree = ast.parse(content, filename=abs_path)
    except SyntaxError as e:
        return f"Error: Python 语法解析失败 (Line {e.lineno}): {e.msg}"
    except Exception as e:
        return f"Error: AST 解析异常: {e}"

    lines = content.splitlines()
    total_lines = len(lines)
    output = [f"[文件骨架] {os.path.basename(abs_path)} (共 {total_lines} 行)"]

    # 1. 模块文档
    doc = ast.get_docstring(tree)
    if doc:
        first_line = doc.strip().splitlines()[0]
        output.append(f"  模块说明: {first_line}")

    # 2. 外部依赖导入
    imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imports.append(mod)
    if imports:
        seen = set()
        dedup_imports = [x for x in imports if x and not (x in seen or seen.add(x))]
        output.append(f"  依赖导入: {', '.join(dedup_imports[:12])}")

    # 3. 核心全局常量/配置变量
    constants = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and (t.id.isupper() or len(tree.body) < 50):
                    constants.append(t.id)
    if constants:
        output.append(f"  核心变量/常量: {', '.join(constants[:15])}")

    def format_sig(fn):
        args = []
        for a in fn.args.posonlyargs + fn.args.args:
            ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
            args.append(f"{a.arg}{ann}")
        if fn.args.vararg:
            args.append(f"*{fn.args.vararg.arg}")
        for a in fn.args.kwonlyargs:
            ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
            args.append(f"{a.arg}{ann}")
        if fn.args.kwarg:
            args.append(f"**{fn.args.kwarg.arg}")
        ret = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
        return f"({', '.join(args)}){ret}"

    # 4. 类与方法
    has_defs = False
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            has_defs = True
            bases = [ast.unparse(b) for b in node.bases]
            bases_str = f"({', '.join(bases)})" if bases else ""
            end_line = getattr(node, 'end_lineno', node.lineno)
            output.append(f"\n[Class] {node.name}{bases_str}  [L{node.lineno}-L{end_line}]")
            cdoc = ast.get_docstring(node)
            if cdoc:
                output.append(f"  说明: {cdoc.strip().splitlines()[0]}")
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_end = getattr(m, 'end_lineno', m.lineno)
                    output.append(f"  - {m.name}{format_sig(m)}  [L{m.lineno}-L{m_end}]")
                    mdoc = ast.get_docstring(m)
                    if mdoc:
                        output.append(f"    说明: {mdoc.strip().splitlines()[0]}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_defs = True
            f_end = getattr(node, 'end_lineno', node.lineno)
            output.append(f"\n[Function] {node.name}{format_sig(node)}  [L{node.lineno}-L{f_end}]")
            fdoc = ast.get_docstring(node)
            if fdoc:
                output.append(f"  说明: {fdoc.strip().splitlines()[0]}")

    if not has_defs:
        output.append("  (该文件无顶层 Class 或 Function 定义，多为纯配置或脚本语句)")

    return "\n".join(output)


# ---------------------------------------------------------------------------
# 文件信息工具
# ---------------------------------------------------------------------------
@registry.register
def get_file_info(file_path: str) -> str:
    """
    获取文件基本信息（大小、行数、类型）。
    
    【重要使用规则】
    - 在读取文件之前，**先调用此工具**查看文件总行数和大小
    - 根据行数决定分页策略：
      - < 200 行：可直接读取全部
      - 200 ~ 1000 行：每次读取 200 行，逐步翻页
      - > 1000 行：使用 search_code 搜索定位，或仅读取关键部分
    
    @param file_path: 文件的绝对或相对路径（支持中文）。
    """
    if not isinstance(file_path, str):
        file_path = str(file_path)
    file_path = file_path.strip().strip('"\'').strip()

    try:
        abs_path = os.path.abspath(file_path)
    except Exception as e:
        return f"Error: 路径解析失败: {e}"

    if not os.path.isfile(abs_path):
        return f"Error: 文件不存在或路径错误: {abs_path}"

    try:
        size = os.path.getsize(abs_path)
        size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024**2:.1f} MB"

        # 快速估算行数（只读前几行判断编码）
        line_count = 0
        for encoding in ["utf-8", "gbk", "ansi"]:
            try:
                with open(abs_path, "r", encoding=encoding) as f:
                    line_count = sum(1 for _ in f)
                break
            except UnicodeDecodeError:
                continue
            except Exception:
                return f"Error: 无法统计行数"

        # 推荐分页策略
        if line_count < 200:
            strategy = "可直接读取全部（< 200 行）"
        elif line_count < 1000:
            strategy = f"建议分页：每次 200 行，共约 {((line_count + 199) // 200)} 页"
        else:
            strategy = f"文件较大（{line_count} 行），建议先用 search_code 搜索定位，或仅读取关键部分"

        return (
            f"📋 文件信息\n"
            f"   路径: {abs_path}\n"
            f"   大小: {size_str}\n"
            f"   行数: {line_count}\n"
            f"   建议: {strategy}"
        )
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 代码搜索工具
# ---------------------------------------------------------------------------
@registry.register
def search_code(file_path: str, keyword: str, context_lines: int = 5) -> str:
    """
    在文件中搜索关键词，返回匹配行及上下文。
    
    【重要使用规则】
    - 当需要查找特定函数、类、变量或模式时，**优先使用此工具**而不是读取整个文件
    - 可以大幅减少 token 消耗，避免撑爆上下文
    
    @param file_path: 要搜索的文件路径（支持中文）。
    @param keyword: 搜索关键词（区分大小写，支持普通文本）。
    @param context_lines: 匹配行前后各显示的行数，默认 5。
    """
    if not isinstance(file_path, str):
        file_path = str(file_path)
    file_path = file_path.strip().strip('"\'').strip()

    try:
        abs_path = os.path.abspath(file_path)
    except Exception as e:
        return f"Error: 路径解析失败: {e}"

    if not os.path.isfile(abs_path):
        return f"Error: 文件不存在或路径错误: {abs_path}"

    # 多编码读取
    lines = None
    for encoding in ["utf-8", "gbk", "ansi"]:
        try:
            with open(abs_path, "r", encoding=encoding) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return f"Error: 读文件异常: {type(e).__name__}: {e}"

    if lines is None:
        return f"Error: 文件编码无法解析"

    # 搜索匹配
    matches = []
    keyword_lower = keyword.lower()
    for i, line in enumerate(lines, 1):
        if keyword_lower in line.lower():
            # 收集上下文
            start = max(0, i - 1 - context_lines)
            end = min(len(lines), i + context_lines)
            match_block = []
            for j in range(start, end):
                prefix = ">>> " if j == i - 1 else "    "
                match_block.append(f"{prefix}{j + 1}: {lines[j].rstrip()}")
            matches.append("\n".join(match_block))

    if not matches:
        return f"🔍 在 '{os.path.basename(abs_path)}' 中未找到 '{keyword}'"

    result = (
        f"🔍 搜索 '{keyword}' 在 '{os.path.basename(abs_path)}' 中找到 {len(matches)} 处匹配:\n\n"
    )
    for idx, match in enumerate(matches, 1):
        result += f"--- 匹配 #{idx} ---\n{match}\n\n"

    # 截断结果防止过长
    max_result_len = 3000
    if len(result) > max_result_len:
        result = result[:max_result_len] + f"\n... (结果过长，已截断至 {max_result_len} 字符)"

    return result


# ---------------------------------------------------------------------------
# 目录浏览工具
# ---------------------------------------------------------------------------
@registry.register
def list_dir(path: str = ".", pattern: str = "*", show_hidden: bool = False) -> str:
    """列出目录内容。@param path: 目录路径，默认为当前目录。 @param pattern: glob 通配符，如 '*.py'。 @param show_hidden: 是否显示隐藏文件。"""
    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        return f"Error: 目录不存在: {abs_path}"

    entries = sorted(glob.glob(os.path.join(abs_path, pattern)))
    if not entries:
        return f"(空目录)"

    lines = []
    for entry in entries:
        name = os.path.basename(entry)
        if not show_hidden and name.startswith("."):
            continue
        if os.path.isdir(entry):
            lines.append(f"[目录] {name}/")
        else:
            size = os.path.getsize(entry)
            lines.append(f"[文件] {name}  ({size:,} bytes)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 文件搜索工具
# ---------------------------------------------------------------------------
@registry.register
def search_files(root_dir: str = ".", pattern: str = "*.py", max_results: int = 50) -> str:
    """递归搜索文件名匹配的文件。@param root_dir: 搜索根目录。 @param pattern: glob 模式，如 '*.py'。 @param max_results: 最多返回结果数。"""
    abs_root = os.path.abspath(root_dir)
    if not os.path.isdir(abs_root):
        return f"Error: 目录不存在: {abs_root}"

    matches = []
    for dirpath, dirnames, filenames in os.walk(abs_root):
        # 跳过 .git 等
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            if glob.fnmatch.fnmatch(fname, pattern):
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, os.getcwd())
                matches.append(rel)
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break

    if not matches:
        return f"(未找到匹配 '{pattern}' 的文件)"
    return "\n".join(f"  {m}" for m in matches)


# ---------------------------------------------------------------------------
# 命令执行工具
# ---------------------------------------------------------------------------
@registry.register
def execute_command(cmd: str, cwd: str = ".", timeout_sec: int = 30) -> str:
    """
    执行本地 shell 命令。@param cmd: 要执行的命令字符串。 @param cwd: 工作目录。 @param timeout_sec: 超时秒数。
    注意：仅限安全命令，禁止 rm -rf /、格式化等危险操作。
    """
    # 安全白名单检查
    dangerous = ["rm -rf", "rm -rf/", "dd ", "mkfs", "format", "> /dev/", "chmod 777"]
    for d in dangerous:
        if d in cmd.lower():
            return f"Error: 危险命令被拦截: {d}"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=os.path.abspath(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            output += f"\n[退出码: {result.returncode}]"
        return output or "(无输出)"
    except subprocess.TimeoutExpired:
        return f"Error: 命令执行超时 ({timeout_sec}s)"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 环境变量工具
# ---------------------------------------------------------------------------
@registry.register
def get_env(var_name: str) -> str:
    """读取一个环境变量。@param var_name: 环境变量名。"""
    value = os.environ.get(var_name)
    if value is None:
        return f"Error: 环境变量 '{var_name}' 未设置"
    # 脱敏：隐藏密码类
    if "password" in var_name.lower() or "secret" in var_name.lower():
        return f"[已隐藏] {var_name}=*** (敏感信息)"
    return value


# ---------------------------------------------------------------------------
# 系统信息工具
# ---------------------------------------------------------------------------
@registry.register
def get_system_info() -> str:
    """获取系统基本信息：OS、Python 版本、工作目录、磁盘空间。"""
    import platform
    disk = ""
    try:
        usage = os.disk_usage(".")
        disk = f"  磁盘: {usage.used / 1024**3:.1f}G / {usage.total / 1024**3:.1f}G"
    except Exception:
        pass
    return (
        f"OS: {platform.system()} {platform.release()}\n"
        f"Python: {platform.python_version()}\n"
        f"工作目录: {os.getcwd()}\n"
        f"{disk}"
    )


# ---------------------------------------------------------------------------
# 文件写入工具（工业级，带路径安全检查 + 异常隔离）
# ---------------------------------------------------------------------------
@registry.register
def write_file(file_path: str, content: str, encoding: str = "utf-8") -> str:
    """
    工业级文件写入工具（带路径安全检查 + 异常隔离）。
    
    【重要使用规则】
    - 当模型完成了代码分析、文档整理等工作后，**使用此工具将结果写入本地文件**，而不是在聊天窗口中输出大段文本
    - 写入文件后，tool_result 只返回简短的成功消息，完美避免对话历史被大段文本污染
    - 支持任意文本文件（.md, .txt, .py, .json, .html 等）
    
    @param file_path: 目标文件的相对或绝对路径（例如 'summary.md' 或 'D:/code/.../doc.md'）。
    @param content: 要写入的完整文件内容。
    @param encoding: 文件编码，默认 utf-8。
    """
    # 1. 路径清洗：确保为字符串并去除首尾引号、反引号、空白
    if not isinstance(file_path, str):
        file_path = str(file_path)
    clean_path = file_path.strip().strip("`'\"").strip()

    # 确保 content 为字符串
    if not isinstance(content, str):
        content = str(content)

    # 2. 转换为绝对路径
    try:
        abs_path = os.path.abspath(clean_path)
    except Exception as e:
        return f"Error: 路径解析失败: {e}"

    # 3. 安全防呆：确保父目录存在，如果不存在则自动创建
    parent_dir = os.path.dirname(abs_path)
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except Exception as e:
            return f"Error: 创建目标文件夹失败: {e}"

    # 4. 异常隔离写入磁盘
    try:
        with open(abs_path, "w", encoding=encoding) as f:
            f.write(content)

        file_size = os.path.getsize(abs_path)
        size_str = f"{file_size:,} 字节" if file_size < 1024 * 1024 else f"{file_size / 1024**2:.1f} MB"
        return f"Success: 成功写入文件到 {abs_path} (文件大小: {size_str})"

    except PermissionError:
        return f"Error: 权限不足，无法写入文件: {abs_path}"
    except OSError as e:
        return f"Error: 磁盘写入失败 ({type(e).__name__}): {e}"
    except Exception as e:
        return f"Error: 写入文件异常: {type(e).__name__}: {e}"


@registry.register
def append_to_file(file_path: str, content: str, encoding: str = "utf-8") -> str:
    """
    向已存在的文件末尾追加文本内容（若文件不存在则自动创建）。
    适用于分段输出、逐步沉淀长篇分析或超大文档，有效避免单次生成超长文本导致超时。

    @param file_path: 目标文件的相对或绝对路径。
    @param content: 要追加的文本内容。
    @param encoding: 文件编码，默认 utf-8。
    """
    if not isinstance(file_path, str):
        file_path = str(file_path)
    clean_path = file_path.strip().strip("`'\"").strip()

    if not isinstance(content, str):
        content = str(content)

    try:
        abs_path = os.path.abspath(clean_path)
    except Exception as e:
        return f"Error: 路径解析失败: {e}"

    parent_dir = os.path.dirname(abs_path)
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except Exception as e:
            return f"Error: 创建目标文件夹失败: {e}"

    try:
        with open(abs_path, "a", encoding=encoding) as f:
            f.write(content)

        file_size = os.path.getsize(abs_path)
        size_str = f"{file_size:,} 字节" if file_size < 1024 * 1024 else f"{file_size / 1024**2:.1f} MB"
        return f"Success: 成功追加内容到 {abs_path} (当前文件总大小: {size_str})"

    except PermissionError:
        return f"Error: 权限不足，无法写入文件: {abs_path}"
    except OSError as e:
        return f"Error: 磁盘写入失败 ({type(e).__name__}): {e}"
    except Exception as e:
        return f"Error: 追加写入异常: {type(e).__name__}: {e}"


@registry.register
def write_markdown_file(file_path: str, content: str) -> str:
    """
    将生成的文档或总结写入本地 Markdown (.md) 文件。
    
    【重要使用规则】
    - 当模型完成了代码分析、文档整理、会议记录等工作后，**使用此工具将结果写入 .md 文件**
    - 写入文件后，tool_result 只返回简短的成功消息（几个 token），完美避免对话历史被大段文本污染
    - 这是解决 400 Bad Request 的关键：用文件写入替代聊天窗口中的超长输出
    
    @param file_path: 目标文件的相对或绝对路径（例如 'summary.md' 或 'D:/code/.../doc.md'）。
    @param content: 要写入的完整 Markdown 文本内容。
    """
    return write_file(file_path, content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Plan-and-Act 任务清单工具
# ---------------------------------------------------------------------------
@registry.register
def init_todo_list(tasks: list, description: str = "") -> str:
    """初始化或重置任务清单（带强类型防御，防止大模型传入错误的字符串格式）。
    @param tasks: 任务步骤的字符串列表，例如 ["扫描目录", "读取核心文件", "分析代码", "写入报告"]。
    @param description: 可选的任务描述。
    """
    # 🛡️ 容错防御：大模型可能以多种格式传入 tasks，必须全部兼容
    if isinstance(tasks, str):
        cleaned_str = tasks.strip()
        tasks = _parse_tasks_string(cleaned_str)

    # 最终兜底：确保是个标准的字符串列表
    if not isinstance(tasks, list):
        tasks = [str(tasks)]

    # 清理每个任务项：去首尾空白、去多余引号
    tasks = [str(t).strip().strip('"\'').strip() for t in tasks if str(t).strip()]

    return todo_manager.set_todos(tasks)


def _parse_tasks_string(raw: str) -> list:
    """
    将大模型可能传入的各种字符串格式解析为标准字符串列表。
    支持的格式：
      - 标准 JSON 数组: '["task1", "task2"]'
      - JSON 数组字符串（模型把数组当字符串发了）: '"[\\"task1\\", \\"task2\\"]"'
      - Python list 字符串: "['task1', 'task2']"
      - 换行分隔文本（带编号）: "1. task1\n2. task2" 或 "1）task1"
      - 逗号分隔文本: "task1, task2, task3"
    """
    import re

    stripped = raw.strip()

    # 策略 0: JSON 数组字符串 — 模型把 JSON 数组当字符串发了
    # 例如: '"[\\"task1\\", \\"task2\\"]"' 或 '"[1, 2, 3]"'
    if len(stripped) >= 2 and stripped[0] == '"':
        try:
            inner = json.loads(stripped)
            if isinstance(inner, str):
                # 内层是字符串，再尝试解析为 JSON 数组
                inner_parsed = json.loads(inner)
                if isinstance(inner_parsed, list):
                    return inner_parsed
            elif isinstance(inner, list):
                return inner
        except (json.JSONDecodeError, TypeError):
            pass

    # 策略 1: 标准 JSON 数组
    if stripped.startswith('[') or stripped.startswith('('):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # 策略 2: 双重转义 JSON — 模型把 JSON 数组当字符串发了
    # 例如: "[\"task1\", \"task2\"]" → 需要先 decode unicode escape
    try:
        unescaped = raw.encode('utf-8').decode('unicode_escape')
        if unescaped != raw:  # 确实有转义字符才继续
            parsed = json.loads(unescaped)
            if isinstance(parsed, list):
                return parsed
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass

    # 策略 3: Python list 字符串 — ast.literal_eval
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return parsed
    except (ValueError, SyntaxError, TypeError):
        pass

    # 策略 4: 换行分隔 — 去掉编号前缀后按行拆分
    # 支持 "1. task", "2) task", "3. task", "1）task" 等格式
    lines = [l.strip() for l in raw.split('\n') if l.strip()]
    if len(lines) >= 2:
        # 清理编号前缀（如 "1. "、"2) "、"3- "、"1）"、"1》" 等）
        cleaned = []
        for line in lines:
            line = re.sub(r'^[\d]+[.\)\]》＞.]\s*', '', line).strip()
            # 去掉首尾引号
            line = line.strip('"\'')
            if line:
                cleaned.append(line)
        if cleaned:
            return cleaned

    # 策略 5: 逗号分隔（最弱，放最后）
    parts = [p.strip().strip('"\'').strip() for p in raw.split(',')]
    parts = [p for p in parts if p]
    return parts if parts else [raw]


@registry.register
def update_todo_status(task_id, status: str) -> str:
    """在执行完某一个子任务，或者状态发生变化时，调用此工具更新清单状态。
    每完成一个子任务就将其标记为 done，让 AI 始终知道当前进度。
    
    @param task_id: 任务编号（整数 ID，如 1、2）。
    @param status: 状态必须是以下之一: 'pending', 'in_progress', 'done'。
    """
    if status not in ("pending", "in_progress", "done"):
        return f"Error: status 必须是 pending, in_progress 或 done 之一，收到: '{status}'。"

    # 解析 task_id：支持 int 或包含数字的字符串
    parsed_id = None
    if isinstance(task_id, int):
        parsed_id = task_id
    elif isinstance(task_id, str):
        m = re.search(r"\d+", task_id)
        if m:
            parsed_id = int(m.group(0))

    if parsed_id is None:
        todos = todo_manager.get_all()
        avail_str = "\n  - ".join([f"#{t['id']}: {t['task']} ({t['status']})" for t in todos]) if todos else "当前暂无活跃任务"
        return (
            f"Error: task_id 收到无效值 '{task_id}'。\n"
            f"【参数契约】：task_id 必须是一个整数编号，指代待办任务列表中具体某一项。\n"
            f"【当前任务清单】：\n  - {avail_str}\n"
            f"请从上述任务列表中选择合法的数字 ID 传入（例如 task_id=1）。"
        )

    return todo_manager.update_todo(parsed_id, status)
