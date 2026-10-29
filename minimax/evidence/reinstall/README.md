# 重装验证记录（2026-10-29）

本目录记录一次**从零重装**的验证：删除旧虚拟环境 → 按 README 的命令重新创建并从**公开源**安装 →
用**全新的数据库数据目录**与**全新的 PowerContext 状态目录**跑完整流程。

## 做了什么

| 项 | 重装前 | 重装后 |
| --- | --- | --- |
| 虚拟环境 | `E:/OceanBase2026/.venvs/minimax312`（累积使用） | **删除后重建** `E:/OceanBase2026/.venvs/reinstall312` |
| 源码 | 开发工作树 | **全新克隆** `2026-competition-ecosystem` 分支（提交 `ac90b562`） |
| seekdb 数据目录 | 复用旧目录 | **全新空目录**（端口 18803） |
| PowerContext 状态目录 | 复用旧目录 | **全新空目录**（`$POWERCONTEXT_HOME`，端口 18802） |
| 数据库 | 复用旧库 | **全新库** `reinstall_sdd` |

安装命令与 README「Linux」一节完全一致（Windows 下用本机 seekdb 二进制代替容器）：

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@dab240063bfcfa7917898dc44da4baadb3747bd0"
```

> 本机 pip 镜像源在重装过程中出现过一次 `from versions: none`（同一版本用 `pip index versions` 能列出来），
> 换官方源 `--index-url https://pypi.org/simple --no-cache-dir` 后正常安装。这是本机镜像的问题，
> 不是交付物的依赖问题；README 已加上这条提示。

## 环境快照

见 `environment.txt`（Python / PyMySQL / powercontext / seekdb 的实际版本与来源）与 `pip-freeze.txt`（完整依赖）。

一个容易误读的点：**PyMySQL 1.2.0 这个发行包里 `pymysql.__version__` 字符串是过期的 `"2.2.8"`**，
真实版本看 `pymysql.VERSION == (1, 2, 0, 'final')` 与 `pip show pymysql`（均为 1.2.0）。
装的确实是 `requirements.txt` 钉住的 1.2.0。

## 重装后的验证结果

| 入口 | 结果 |
| --- | --- |
| `run_demo.py --recorded` | 15 步 PASS（存档 `evidence/run/3729a7adf522/`） |
| `run_demo.py`（实时调用 MiniMax API） | 15 步 PASS（存档 `evidence/run/2e8d57635521/`） |
| `verify_sample.py` | `before=1 / after=0` |
| `verify_context.py` | PASS（真实 seekdb 导入/查询、规格更新、PowerContext 空状态写入与跨进程复用） |
| `verify_platform_record.py` | PASS（平台记录重建的代码与交付快照逐字节一致） |
| `test_tooling.py` | 10/10 OK |
| `verify_acceptance.py` | 全部通过 |

## 三次实时调用的产出对比

重装验证中共做了三次真实 MiniMax API 调用，模型每次都**重新生成**（不是重放）：

| 时间 | 运行编号 | 响应 ID | usage | 产出 SHA-256 |
| --- | --- | --- | --- | --- |
| 2026-10-28（队友） | — | `07307cf6…` / `07307d0c…` | 1393 / 2010 | `8b9c31f7af6e8d3b…` |
| 2026-10-29 第一次 | `5b3abb06746b` | `07324d81…` / `07324d87…` | 1407 / 2039 | `8b9c31f7af6e8d3b…`（与上者逐字节相同） |
| 2026-10-29 第二次（重装环境） | `2e8d57635521` | `07325a1a…` | 2014 | `7f3785f54b6a1406…` |

第三份与前两份的差异**只有一行错误提示文案**：

```diff
-        raise ValueError("status must be either 'todo' or 'done'")
+        raise ValueError("status must be 'todo' or 'done'")
```

行为完全一致——三份实现跑**同一份**测试文件（SHA-256 `2c01d2de…`）均为 7 项全通过。
这正对应官方「MiniMax 的使用通过开发记录核对，不要求模型重新生成完全相同的补丁」。
