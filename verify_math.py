"""数学 few-shot 验证工具 —— 用书生 API 人工检查 domain_prompts.py 中的示例。

功能：
1. 自动解析 domain_prompts.py 提取所有 few-shot 题目+答案
2. 多种验证方法：数值比较、字符串匹配、LaTeX 归一化、符号匹配
3. 边界条件测试：不同温度(0.0/0.3/0.6)下答案一致性
4. 生成验证报告：通过/失败状态 + 差异详情

默认仅解析并预检，不访问 API：python verify_math.py
显式在线验证：python verify_math.py --execute --max-requests 21
"""
import argparse
import json
import re
import time
from pathlib import Path

from math_agent.answer_equivalence import normalize_answer as normalize_core_answer
from math_agent.domain_prompts import DOMAIN_PROMPTS
from math_agent.llm_client import InternChatClient


# ==================== 解析器：从 domain_prompts.py 提取 few-shot ====================

def parse_fewshot_examples():
    """自动从 DOMAIN_PROMPTS 中解析出所有 few-shot 题目和答案。"""
    examples = []
    for domain, prompt in DOMAIN_PROMPTS.items():
        marker = re.search(r"【Few-shot】\s*\n", prompt)
        if not marker:
            continue
        block = prompt[marker.end():]
        pattern = re.compile(
            r"^题[：:]\s*(?P<problem>.+?)\n"
            r"解[：:]\s*(?P<solution>.+?)\n"
            r"最终答案\s*[:：]\s*(?P<answer>[^\n]+)",
            re.MULTILINE | re.DOTALL,
        )
        for match in pattern.finditer(block):
            examples.append({
                "domain": domain,
                "problem": match.group("problem").strip(),
                "expected_answer": match.group("answer").strip(),
                "solution": match.group("solution").strip(),
            })
    return examples


# ==================== 验证器：多种方法比较答案 ====================

def normalize_answer(s: str) -> str:
    """使用运行时共享的保守归一化，避免验证入口单独漂移。"""
    return normalize_core_answer(s)


def to_numeric(s: str) -> float | None:
    """尝试转为数值——支持分数、小数、整数。"""
    if not s:
        return None
    s = normalize_answer(s)
    # 多解取第一个
    first = re.split(r"[,，;；\s]", s.strip())[0]
    try:
        if "/" in first:
            p = first.split("/")
            if len(p) == 2:
                return float(p[0]) / float(p[1])
        return float(first)
    except (ValueError, ZeroDivisionError):
        return None


def verify_numeric(expected: str, actual: str) -> bool:
    """方法1：数值比较——转换为 float 后比较。"""
    e = to_numeric(expected)
    a = to_numeric(actual)
    if e is not None and a is not None:
        return abs(e - a) < 0.01
    return False


def verify_string(expected: str, actual: str) -> bool:
    """方法2：字符串匹配——归一化后必须完全一致，避免子串误报。"""
    e = normalize_answer(expected).lower()
    a = normalize_answer(actual).lower()
    if not e or not a:
        return False
    return e == a


def verify_symbolic(expected: str, actual: str) -> bool:
    """方法3：保守符号匹配；无法证明等价时返回失败。"""
    e = normalize_answer(expected).replace(" ", "").lower()
    a = normalize_answer(actual).replace(" ", "").lower()
    return bool(e and a and e == a)


def verify_answer(expected: str, actual: str) -> tuple[bool, str]:
    """综合验证——依次尝试多种方法。"""
    if verify_numeric(expected, actual):
        return True, "数值匹配"
    if verify_string(expected, actual):
        return True, "字符串匹配"
    if verify_symbolic(expected, actual):
        return True, "符号匹配"
    return False, "不匹配"


# ==================== API 调用器 ====================

def ask_api(client: InternChatClient, problem: str, temperature: float = 0.0) -> str:
    """调用书生 API 解题，返回文本响应。"""
    resp = client.chat(
        messages=[
            {"role": "system", "content": "你是数学专家。请解题，最后用 \\boxed{} 给出最终答案。"},
            {"role": "user", "content": problem},
        ],
        temperature=temperature,
        max_tokens=2048,
        thinking_mode=False,
    )
    return resp


def extract_answer_from_response(resp: str) -> str:
    """从 API 响应中提取答案。"""
    if not resp:
        return ""
    # \boxed{xxx}
    m = re.search(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", resp)
    if m:
        return m.group(1).strip()
    # 最终答案：xxx
    m = re.search(r"最终答案\s*[:：]\s*(.+?)(?:\n|$)", resp)
    if m:
        return m.group(1).strip()
    # 答案是/为：xxx
    m = re.search(r"答案(?:是|为)?\s*[:：]?\s*(.+?)(?:\n|。|$)", resp)
    if m:
        return m.group(1).strip()
    # 最后一行
    lines = [l.strip() for l in resp.strip().split("\n") if l.strip()]
    return lines[-1][:200] if lines else ""


# ==================== 主验证流程 ====================

def run_verification(
    *,
    execute: bool = False,
    max_requests: int = 21,
    retry_failures: bool = False,
    sleep_seconds: float = 0.5,
):
    """验证 few-shot；默认 dry-run，只有 execute=True 时访问 API。"""
    if max_requests <= 0:
        raise ValueError("max_requests must be a positive integer")

    print("=" * 70)
    print("  数学 few-shot 验证工具 v2.0")
    print("  离线预检；显式 --execute 时才使用书生 API")
    print("=" * 70)
    print()

    # 1. 解析 few-shot
    examples = parse_fewshot_examples()
    print(f"解析到 {len(examples)} 个 few-shot 示例")
    print()
    if not examples:
        print("ERROR: 未解析到任何 few-shot 示例")
        return []

    if not execute:
        planned = min(len(examples), max_requests)
        print("DRY-RUN: 未访问 API，也未生成验证报告。")
        print(f"如使用 --execute，本次最多请求 {max_requests} 次，首轮计划 {planned} 次。")
        if retry_failures:
            print("失败项重试已启用，但仍受同一请求上限约束。")
        return examples

    # 2. 初始化 client
    try:
        client = InternChatClient()
    except Exception as e:
        print(f"ERROR: 无法初始化 API client: {e}")
        print("请确认 .env 中设置了 INTERN_API_KEY")
        return

    # 3. 逐个验证
    results = []
    pass_count = 0
    fail_count = 0
    request_count = 0

    print(f"{'#':>3} {'领域':<10} {'我们的答案':<25} {'API答案':<30} {'方法':<10} {'结果'}")
    print("-" * 100)

    for i, ex in enumerate(examples):
        domain = ex["domain"]
        problem = ex["problem"]
        expected = ex["expected_answer"]

        # 调用 API；请求上限覆盖首轮和所有重试。
        resp = ""
        if request_count >= max_requests:
            api_answer = "BUDGET_EXHAUSTED"
        else:
            request_count += 1
            try:
                resp = ask_api(client, problem, temperature=0.0)
                api_answer = extract_answer_from_response(resp)
            except Exception as e:
                api_answer = f"API_ERROR: {str(e)[:50]}"

        # 验证
        match, method = verify_answer(expected, api_answer)

        if match:
            pass_count += 1
            status = "PASS"
        else:
            fail_count += 1
            status = "*** FAIL ***"

        print(f"{i+1:3} {domain:<10} {expected:<25} {api_answer[:30]:<30} {method:<10} {status}")

        results.append({
            "domain": domain,
            "problem": problem[:100],
            "expected": expected,
            "api_answer": api_answer,
            "match": match,
            "method": method,
            "api_response": resp[:500] if resp else "",
            "_verification_problem": problem,
        })

        if resp and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    # 4. 边界条件测试：对失败的用不同温度重试
    failed = [r for r in results if not r["match"]]
    if failed and retry_failures and request_count < max_requests:
        print()
        print("-" * 100)
        print(f"边界条件测试：{len(failed)} 个失败项用温度 0.3 和 0.6 重试")
        print("-" * 100)
        
        for r in failed:
            for temp in [0.3, 0.6]:
                if request_count >= max_requests:
                    break
                request_count += 1
                try:
                    resp = ask_api(client, r["_verification_problem"], temperature=temp)
                    api_ans = extract_answer_from_response(resp)
                    match, method = verify_answer(r["expected"], api_ans)
                    if match:
                        r["match"] = True
                        r["method"] = f"温度{temp}时{method}"
                        pass_count += 1
                        fail_count -= 1
                        print(f"  {r['domain']:<10} 温度={temp} → PASS ({method})")
                        break
                    else:
                        print(f"  {r['domain']:<10} 温度={temp} → 仍不匹配 (API={api_ans[:40]})")
                except Exception as e:
                    print(f"  {r['domain']:<10} 温度={temp} → ERROR: {str(e)[:50]}")
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)

    # 5. 生成报告
    print()
    print("=" * 70)
    print("  验证报告")
    print("=" * 70)
    print(f"  总计: {len(examples)} 个示例")
    print(f"  通过: {pass_count}")
    print(f"  失败: {fail_count}")
    print(f"  通过率: {pass_count/len(examples)*100:.1f}%")
    print(f"  API 请求: {request_count}/{max_requests}")
    print()

    if fail_count > 0:
        print("  *** 失败详情 ***")
        for r in results:
            if not r["match"]:
                print(f"  {r['domain']}:")
                print(f"    题目: {r['problem'][:80]}")
                print(f"    我们的答案: {r['expected']}")
                print(f"    API答案: {r['api_answer'][:80]}")
                print()

    # 6. 保存报告到文件
    report_path = Path(__file__).parent / "verify_report.json"
    report_results = [
        {key: value for key, value in result.items() if not key.startswith("_")}
        for result in results
    ]
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_results, f, ensure_ascii=False, indent=2)
    print(f"  详细报告已保存: {report_path}")
    print()

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="离线预检或显式在线验证 domain_prompts.py 中的 few-shot。"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="显式允许访问真实 API；省略时只做离线解析。",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=21,
        help="首轮与重试共用的 API 请求硬上限（默认 21）。",
    )
    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="用温度 0.3/0.6 重试失败项，仍受请求上限约束。",
    )
    args = parser.parse_args()
    if args.max_requests <= 0:
        parser.error("--max-requests must be a positive integer")
    return args


if __name__ == "__main__":
    cli_args = parse_args()
    run_verification(
        execute=cli_args.execute,
        max_requests=cli_args.max_requests,
        retry_failures=cli_args.retry_failures,
    )
